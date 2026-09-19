import asyncio
import calendar
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .audit import log_audit
from . import database
from .storage import backup_path

BACKUPS=backup_path()
CRITICAL_TABLES=('users','employees','items','warehouses','inventory_stock','inventory_layers','stock_ledger','audit_log')

def setting(connection,key,default):
    row=connection.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
    return str(row['value'])if row else default

def backup_schedule(now_utc=None):
    now_utc=now_utc or datetime.now(timezone.utc)
    with database.connect() as c:
        enabled=setting(c,'automatic_month_end_backup','1')=='1';zone_name=setting(c,'backup_time_zone','Asia/Riyadh');backup_time=setting(c,'backup_time','16:00')
    try:zone=ZoneInfo(zone_name)
    except ZoneInfoNotFoundError:zone=ZoneInfo('UTC');zone_name='UTC'
    local=now_utc.astimezone(zone);last_day=calendar.monthrange(local.year,local.month)[1];hours,minutes=map(int,backup_time.split(':'))
    scheduled_local=local.replace(day=last_day,hour=hours,minute=minutes,second=0,microsecond=0)
    return {'enabled':enabled,'cycle_id':f'{local.year:04d}-{local.month:02d}-MONTH-END','time_zone':zone_name,'scheduled_local':scheduled_local,'scheduled_utc':scheduled_local.astimezone(timezone.utc),'now_utc':now_utc}

def notify(connection,cycle_id,kind,message,when_column):
    users=connection.execute("SELECT id FROM users WHERE is_active=1 AND deleted_at IS NULL AND lower(role)<>'finance'").fetchall()
    for user in users:connection.execute('INSERT OR IGNORE INTO notifications(user_id,type,message,event_key,expires_at)VALUES(?,?,?,?,datetime(?,\'+2 days\'))',(user['id'],kind,message,f'{cycle_id}:{kind}',datetime.now(timezone.utc).isoformat()))
    connection.execute(f'UPDATE backup_cycles SET {when_column}=COALESCE({when_column},datetime(\'now\')),updated_at=datetime(\'now\') WHERE cycle_id=?',(cycle_id,))
    log_audit(connection,'backup_cycles',None,'UPDATE',None,after={'cycle_id':cycle_id,'event':kind,'recipients':len(users)})

def verify_backup(path,source_counts):
    if not path.exists()or path.stat().st_size<4096:raise RuntimeError('Backup file is missing or empty')
    connection=sqlite3.connect(path);connection.row_factory=sqlite3.Row
    try:
        if connection.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('SQLite integrity verification failed')
        if connection.execute('PRAGMA foreign_key_check').fetchall():raise RuntimeError('Foreign-key verification failed')
        tables={row[0]for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not set(CRITICAL_TABLES)<=tables:raise RuntimeError('Critical tables are missing')
        for table,count in source_counts.items():
            if connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]!=count:raise RuntimeError(f'Record-count verification failed for {table}')
    finally:connection.close()
    return 'integrity=ok; foreign_keys=0; critical_counts=matched'

def execute_month_end_backup(schedule=None,fail_for_test=False):
    schedule=schedule or backup_schedule();cycle=schedule['cycle_id'];target=BACKUPS/f"procuraflo-month-end-{cycle}-{secrets.token_hex(4)}.db"
    with database.transaction(immediate=True)as c:
        row=c.execute('SELECT status FROM backup_cycles WHERE cycle_id=?',(cycle,)).fetchone()
        if row and row['status']in('RUNNING','COMPLETED'):return {'cycle_id':cycle,'status':row['status'],'duplicate_prevented':True}
        c.execute("INSERT INTO backup_cycles(cycle_id,scheduled_at_utc,backup_time_zone,status,started_at)VALUES(?,?,?,'RUNNING',datetime('now')) ON CONFLICT(cycle_id)DO UPDATE SET status='RUNNING',started_at=datetime('now'),error_message=NULL",(cycle,schedule['scheduled_utc'].isoformat(),schedule['time_zone']))
        c.execute("UPDATE system_maintenance SET active_yn=1,reason='Month-End Backup in Progress',cycle_id=?,scheduled_at_utc=?,started_at=datetime('now'),completed_at=NULL,result=NULL,session_epoch=session_epoch+1,updated_at=datetime('now') WHERE id=1",(cycle,schedule['scheduled_utc'].isoformat()))
        log_audit(c,'backup_cycles',None,'UPDATE',None,after={'cycle_id':cycle,'event':'MAINTENANCE_ACTIVATED_AND_SESSIONS_INVALIDATED'})
    try:
        if fail_for_test:raise RuntimeError('Simulated backup failure')
        source=database.connect();destination=None
        try:
            source_counts={table:source.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]for table in CRITICAL_TABLES};destination=sqlite3.connect(target);source.backup(destination)
        finally:
            if destination:destination.close()
            source.close()
        verification=verify_backup(target,source_counts)
        with database.transaction(immediate=True)as c:
            c.execute("UPDATE backup_cycles SET status='COMPLETED',completed_at=datetime('now'),backup_reference=?,verification_result=?,updated_at=datetime('now') WHERE cycle_id=?",(target.name,verification,cycle))
            c.execute("INSERT INTO backup_restore_history(backup_reference,backup_type,database_included,attachments_included,configuration_included,backup_status,restore_tested,restore_test_date,restore_result,notes)VALUES(?,'AUTOMATIC_MONTH_END',1,0,1,'SUCCESS',1,datetime('now'),?,'Verified scheduled month-end SQLite backup')",(target.name,verification))
            c.execute("UPDATE system_maintenance SET active_yn=0,completed_at=datetime('now'),result='SUCCESS',updated_at=datetime('now') WHERE id=1")
            notify(c,cycle,'BACKUP_COMPLETE','MONTH-END BACKUP COMPLETE — Procuraflo is available. Sign in again to resume work.','completed_at')
            log_audit(c,'backup_cycles',None,'CREATE',None,after={'cycle_id':cycle,'event':'BACKUP_VERIFIED_AND_MAINTENANCE_ENDED','backup_reference':target.name,'verification':verification})
        return {'cycle_id':cycle,'status':'COMPLETED','backup_reference':target.name,'verification':verification}
    except Exception as error:
        try:target.unlink(missing_ok=True)
        except OSError:pass
        with database.transaction(immediate=True)as c:
            c.execute("UPDATE backup_cycles SET status='FAILED',completed_at=datetime('now'),error_message=?,verification_result='FAILED',updated_at=datetime('now') WHERE cycle_id=?",(str(error),cycle))
            c.execute("UPDATE system_maintenance SET active_yn=0,completed_at=datetime('now'),result='FAILED',updated_at=datetime('now') WHERE id=1")
            notify(c,cycle,'BACKUP_FAILED','MONTH-END BACKUP FAILED — Procuraflo data remains protected by the last verified backup. Authorized management should review the status.','completed_at')
            log_audit(c,'backup_cycles',None,'UPDATE',None,after={'cycle_id':cycle,'event':'BACKUP_FAILED_AND_MAINTENANCE_ENDED','error':str(error)})
        return {'cycle_id':cycle,'status':'FAILED','error':str(error)}

def scheduler_tick(now_utc=None):
    schedule=backup_schedule(now_utc)
    if not schedule['enabled']:return {'status':'DISABLED',**schedule}
    remaining=(schedule['scheduled_utc']-schedule['now_utc']).total_seconds()
    with database.transaction(immediate=True)as c:
        c.execute("INSERT OR IGNORE INTO backup_cycles(cycle_id,scheduled_at_utc,backup_time_zone,status)VALUES(?,?,?,'SCHEDULED')",(schedule['cycle_id'],schedule['scheduled_utc'].isoformat(),schedule['time_zone']))
        row=c.execute('SELECT * FROM backup_cycles WHERE cycle_id=?',(schedule['cycle_id'],)).fetchone()
        for minutes,column in ((30,'warning_30_at'),(20,'warning_20_at'),(10,'warning_10_at')):
            if 0<remaining<=minutes*60 and not row[column]:notify(c,schedule['cycle_id'],f'BACKUP_WARNING_{minutes}',f'SYSTEM BACKUP NOTICE — Month-end backup begins in {minutes} minutes. Save and complete current work; all sessions will be signed out.',column);row=c.execute('SELECT * FROM backup_cycles WHERE cycle_id=?',(schedule['cycle_id'],)).fetchone()
    if remaining<=0 and remaining>-86400:return execute_month_end_backup(schedule)
    return {'status':'SCHEDULED','cycle_id':schedule['cycle_id'],'scheduled_at_utc':schedule['scheduled_utc'].isoformat(),'seconds_remaining':max(0,int(remaining)),'time_zone':schedule['time_zone']}

async def scheduler_loop():
    while True:
        try:await asyncio.to_thread(scheduler_tick)
        except Exception:pass
        await asyncio.sleep(30)
