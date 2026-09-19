from datetime import date,datetime,timedelta
import hashlib
import json
import os
import httpx
from fastapi import APIRouter,Depends,HTTPException,Request
from ..audit import log_audit
from ..database import fetch_all,fetch_one,transaction
from ..security import User,roles
router=APIRouter(prefix='/api/workforce',tags=['workforce']);admin=roles('SupplyChainManager')

EXCEPTION_STATUSES={'Unavailable','Leave','Sick','Training','Other'}

def time_minutes(value):
    try:hours,minutes=map(int,str(value).split(':')[:2]);assert 0<=hours<24 and 0<=minutes<60;return hours*60+minutes
    except (ValueError,TypeError,AssertionError):raise HTTPException(400,'Shift times must use HH:MM format')

def clock_time(minutes):
    minutes%=1440;return f'{minutes//60:02d}:{minutes%60:02d}'

def shift_coverage_end(shift):return clock_time(time_minutes(shift['end_time']))

def calendar_work_periods(day, start, end, assigned_shift):
    """Subtract only the assigned shift break, including overnight boundaries."""
    midnight = datetime.combine(date.fromisoformat(day), datetime.min.time())
    begin = midnight + timedelta(minutes=time_minutes(start))
    finish = begin + timedelta(minutes=(time_minutes(end)-time_minutes(start)) % 1440 or 1440)
    closures = []
    for shift in (assigned_shift,):
        duration = (time_minutes(shift['end_time'])-time_minutes(shift['start_time'])) % 1440 or 1440
        minutes = int(shift.get('break_minutes') or 0)
        if not minutes:
            continue
        for offset in (-1, 0, 1):
            break_start = midnight + timedelta(days=offset, minutes=time_minutes(shift['start_time']) + min(duration // 2, duration-minutes))
            break_end = break_start + timedelta(minutes=minutes)
            left, right = max(begin, break_start), min(finish, break_end)
            if left < right:
                closures.append((left, right))
    merged = []
    for left, right in sorted(closures):
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
        else:
            merged.append((left, right))
    working, cursor = [], begin
    for left, right in merged:
        if cursor < left:
            working.append((cursor, left))
        cursor = right
    if cursor < finish:
        working.append((cursor, finish))
    serialize = lambda periods: [{'start': left.isoformat(timespec='minutes'), 'end': right.isoformat(timespec='minutes')} for left, right in periods]
    return {'working_intervals': serialize(working), 'closed_breaks': serialize(merged),
            'working_minutes': int(sum((right-left).total_seconds()/60 for left, right in working))}

def continuous_shift_coverage(shifts):
    ordered=sorted(shifts,key=lambda item:(time_minutes(item['start_time']),item.get('id')or 0))
    return len(ordered)==3 and all(
        shift_coverage_end(ordered[index])==clock_time(time_minutes(ordered[(index+1)%len(ordered)]['start_time']))
        for index in range(len(ordered))
    )

def warehouse_window_coverage(shifts,start_time,end_time):
    if not shifts:return False
    window_start=time_minutes(start_time)
    ordered=sorted(shifts,key=lambda item:((time_minutes(item['start_time'])-window_start)%1440,item.get('id')or 0))
    if clock_time(time_minutes(ordered[0]['start_time']))!=clock_time(time_minutes(start_time)):return False
    offsets=[(time_minutes(item['start_time'])-window_start)%1440 for item in ordered]
    for index in range(len(ordered)-1):
        scheduled_end=offsets[index]+((time_minutes(ordered[index]['end_time'])-time_minutes(ordered[index]['start_time']))%1440 or 1440)
        next_start=offsets[index+1]
        if next_start>scheduled_end:return False
    final_scheduled_end=offsets[-1]+((time_minutes(ordered[-1]['end_time'])-time_minutes(ordered[-1]['start_time']))%1440 or 1440)
    window_duration=(time_minutes(end_time)-window_start)%1440 or 1440
    return final_scheduled_end>=window_duration if len(ordered)==1 else final_scheduled_end==window_duration

def procurement_configuration():
    rows={row['key']:row['value'] for row in fetch_all("SELECT key,value FROM settings WHERE key LIKE 'procurement_%'")}
    try:days=sorted(set(int(day)for day in json.loads(rows.get('procurement_operating_days','[0,1,2,3,4]'))))
    except(TypeError,ValueError):days=[0,1,2,3,4]
    return {'shifts_enabled_yn':int(rows.get('procurement_shifts_enabled','0')=='1'),'operating_start_time':rows.get('procurement_operating_start_time','08:00')[:5],'operating_end_time':rows.get('procurement_operating_end_time','17:00')[:5],'operating_days':days}

def holiday_bounds(holiday):
    try:
        official=date.fromisoformat(str(holiday['holiday_date']))
        start=date.fromisoformat(str(holiday.get('observed_date')or holiday['holiday_date']))
        end=date.fromisoformat(str(holiday.get('holiday_end_date')or start.isoformat()))
    except (KeyError,ValueError,TypeError):
        raise HTTPException(400,'Enter valid holiday start and end dates')
    if end<start or (holiday.get('holiday_end_date') and end<official):
        raise HTTPException(400,'Holiday end date cannot be before the start or observed date')
    return start,end

def refresh_holiday_range(holiday,user_id,trigger):
    start,end=holiday_bounds(holiday)
    # Also refresh shifts beginning the previous day that cross into the holiday.
    cursor=start-timedelta(days=1)
    totals={'created':0,'updated':0}
    while cursor<=end:
        last=min(end,cursor+timedelta(days=366))
        result=generate_calendar_range(cursor.isoformat(),last.isoformat(),user_id,trigger=trigger,reason=holiday.get('holiday_name'))
        for key in totals:totals[key]+=result[key]
        cursor=last+timedelta(days=1)
    return totals

def holiday_applies(holiday, day, warehouse, company):
    if not (holiday.get('observed_date') or holiday['holiday_date']) <= day <= (holiday.get('holiday_end_date') or holiday.get('observed_date') or holiday['holiday_date']):
        return False
    scope = str(holiday.get('applicability') or 'ALL').upper()
    if scope not in ('ALL', 'BOTH', 'COMPANY', 'WAREHOUSE' if warehouse else 'PROCUREMENT'):
        return False
    if holiday.get('warehouse_id') and (not warehouse or holiday['warehouse_id'] != warehouse['id']):
        return False
    location = warehouse or company
    if holiday.get('country_code') and holiday['country_code'] != location.get('country_code'):
        return False
    region = str(holiday.get('region') or '').strip().lower()
    return not region or region == str(location.get('region_province') or location.get('region') or '').strip().lower()

def validate_holiday_scope(body):
    if str(body.get('applicability') or 'ALL').upper() not in ('ALL','WAREHOUSE','PROCUREMENT'):
        raise HTTPException(400,'Select All locations, Warehouse, or Procurement holiday applicability')
    if body.get('warehouse_id') and str(body.get('applicability')or'ALL').upper()!='WAREHOUSE':
        raise HTTPException(400,'A specific warehouse requires Warehouse holiday applicability')
    if body.get('warehouse_id') and not fetch_one('SELECT id FROM warehouses WHERE id=? AND deleted_at IS NULL',(body['warehouse_id'],)):
        raise HTTPException(400,'Select an active warehouse for the holiday')
    if body.get('procurement_work_required') and not str(body.get('procurement_work_reason') or '').strip():
        raise HTTPException(400,'A reason is required to operate procurement on a holiday')

def location_work_periods(c, day, start, end, assigned_shift, warehouse, company, procurement, employee_id=None):
    periods=calendar_work_periods(day,start,end,assigned_shift)
    working=[];closures=[]
    for interval in periods['working_intervals']:
        left=datetime.fromisoformat(interval['start']);finish=datetime.fromisoformat(interval['end'])
        while left<finish:
            right=min(finish,datetime.combine(left.date()+timedelta(days=1),datetime.min.time()))
            local_day=left.date().isoformat();weekday=left.weekday()
            if warehouse:
                schedule=c.execute('SELECT is_open FROM warehouse_operating_schedules WHERE warehouse_id=? AND weekday=?',(warehouse['id'],weekday)).fetchone()
                closed=weekday not in json.loads(warehouse.get('operating_days_json')or'[]') or (schedule and not schedule['is_open'])
            else:closed=weekday not in procurement['operating_days']
            holidays=[dict(row) for row in c.execute('SELECT * FROM holidays WHERE active_yn=1 AND COALESCE(observed_date,holiday_date)<=? AND COALESCE(holiday_end_date,observed_date,holiday_date)>=?',(local_day,local_day))]
            matched=[holiday for holiday in holidays if holiday_applies(holiday,local_day,warehouse,company)]
            if matched:
                approved=[]
                for holiday in matched:
                    allowed=c.execute('SELECT 1 FROM holiday_work_exceptions WHERE holiday_id=? AND warehouse_id=? AND work_required=1 AND(employee_id IS NULL OR employee_id=?)',(holiday['id'],warehouse['id'],employee_id)).fetchone() if warehouse else holiday.get('procurement_work_required')
                    approved.append(bool(allowed))
                closed=not all(approved)
            segment={'start':left.isoformat(timespec='minutes'),'end':right.isoformat(timespec='minutes')}
            if closed:
                closures.append({**segment,'reason':matched[0]['holiday_name'] if matched else 'Off Day / Closed'})
            else:working.append(segment)
            left=right
    periods['working_intervals']=working
    periods['closed_periods']=closures
    periods['working_minutes']=int(sum((datetime.fromisoformat(item['end'])-datetime.fromisoformat(item['start'])).total_seconds()/60 for item in working))
    return periods

def generate_calendar_range(start:str,end:str,user_id:int,employee_id:int|None=None,trigger='AUTOMATIC_GENERATION',reason=None):
    try:start_date=date.fromisoformat(start);end_date=date.fromisoformat(end)
    except (TypeError,ValueError):raise HTTPException(400,'Calendar dates must use YYYY-MM-DD format')
    if end_date<start_date or (end_date-start_date).days>366:raise HTTPException(400,'Calendar range must be between 1 and 367 days')
    employees=fetch_all("""SELECT e.id,e.department_id,e.warehouse_id,COALESCE(e.approval_role,'Helper') role_code,d.name department_name
        FROM employees e JOIN departments d ON d.id=e.department_id
        WHERE e.status='Active' AND e.deleted_at IS NULL
        AND (e.employment_start_date IS NULL OR e.employment_start_date<=?)
        AND (e.employment_end_date IS NULL OR e.employment_end_date>=?)
        AND (? IS NULL OR (e.department_id=(SELECT department_id FROM employees WHERE id=?)
          AND COALESCE(e.approval_role,'Helper')=(SELECT COALESCE(approval_role,'Helper') FROM employees WHERE id=?)
          AND COALESCE(e.warehouse_id,-1)=COALESCE((SELECT warehouse_id FROM employees WHERE id=?),-1)))
        ORDER BY e.id""",(end,start,employee_id,employee_id,employee_id,employee_id))
    procurement=procurement_configuration()
    shifts=fetch_all("SELECT * FROM shifts WHERE active_yn=1 AND warehouse_id IS NULL ORDER BY start_time,id")
    valid_procurement=continuous_shift_coverage(shifts)if procurement['shifts_enabled_yn']else warehouse_window_coverage(shifts,procurement['operating_start_time'],procurement['operating_end_time'])
    if not valid_procurement:raise HTTPException(409,'Procurement shifts do not cover the configured procurement operating window without gaps or overlaps.')
    warehouse_shift_rows=fetch_all("SELECT * FROM shifts WHERE active_yn=1 AND warehouse_id IS NOT NULL ORDER BY warehouse_id,start_time,id")
    warehouse_shifts={}
    for row in warehouse_shift_rows:warehouse_shifts.setdefault(row['warehouse_id'],[]).append(row)
    warehouse_windows={row['id']:row for row in fetch_all("SELECT id,operating_start_time,operating_end_time,time_zone,country_code,region_province,operating_days_json FROM warehouses WHERE deleted_at IS NULL")}
    operating_schedules={(row['warehouse_id'],row['weekday']):row for row in fetch_all('SELECT * FROM warehouse_operating_schedules')}
    applicable_holidays=fetch_all("SELECT * FROM holidays WHERE active_yn=1 AND date(COALESCE(observed_date,holiday_date))<=? AND date(COALESCE(holiday_end_date,observed_date,holiday_date))>=?",(end,start))
    for warehouse_id,assigned in warehouse_shifts.items():
        window=warehouse_windows.get(warehouse_id)
        if window:assigned.sort(key=lambda item:((time_minutes(item['start_time'])-time_minutes(window['operating_start_time']))%1440,item['id']))
    for warehouse_id in {employee['warehouse_id'] for employee in employees if str(employee['department_name']).strip().lower()=='warehouse' and employee['warehouse_id'] is not None}:
        window=warehouse_windows.get(warehouse_id);assigned=warehouse_shifts.get(warehouse_id,[])
        if not window or not warehouse_window_coverage(assigned,window['operating_start_time'],window['operating_end_time']):
            raise HTTPException(409,f"Warehouse {warehouse_id} calendar cannot be generated because its shifts do not cover its operating window without gaps or overlaps.")
    company=fetch_one("SELECT * FROM company WHERE deleted_at IS NULL ORDER BY id DESC LIMIT 1")or{}
    holidays={row['holiday_date']:row for row in fetch_all("SELECT id,holiday_date FROM holidays WHERE active_yn=1 AND (? IS NULL OR country_code=?) AND holiday_date BETWEEN ? AND ?",(company.get('country_code'),company.get('country_code'),start,end))}
    created=updated=0
    with transaction(immediate=True)as c:
        cursor=start_date
        while cursor<=end_date:
            day=cursor.isoformat();holiday=holidays.get(day)
            day_exceptions={}
            available_groups={}
            for employee in employees:
                exception=c.execute("""SELECT availability_status,reason,remarks FROM employee_availability
                    WHERE employee_id=? AND date_from<=? AND date_to>=? AND availability_status<>'Available'
                    ORDER BY created_at DESC,id DESC LIMIT 1""",(employee['id'],day,day)).fetchone()
                day_exceptions[employee['id']]=exception
                if str(employee['department_name']).strip().lower()=='warehouse' and not exception:
                    key=(employee['department_id'],employee['warehouse_id'],employee['role_code'])
                    available_groups.setdefault(key,[]).append(employee['id'])
            for employee in employees:
                exception=day_exceptions[employee['id']]
                employee_shifts=warehouse_shifts.get(employee['warehouse_id'],[]) if str(employee['department_name']).strip().lower()=='warehouse' else shifts
                warehouse=warehouse_windows.get(employee['warehouse_id'])if str(employee['department_name']).strip().lower()=='warehouse' else None
                operating_day=operating_schedules.get((employee['warehouse_id'],cursor.weekday()))if warehouse else None
                warehouse_closed=bool(warehouse and (cursor.weekday() not in json.loads(warehouse.get('operating_days_json')or'[0,1,2,3,4,5,6]') or (operating_day and not operating_day['is_open'])))
                procurement_closed=bool(not warehouse and cursor.weekday()not in procurement['operating_days'])
                holiday=next((item for item in applicable_holidays if holiday_applies(item,day,warehouse,company)),None)
                holiday_exception=None
                if holiday and warehouse:
                    holiday_exception=c.execute('SELECT * FROM holiday_work_exceptions WHERE holiday_id=? AND warehouse_id=? AND work_required=1 AND(employee_id IS NULL OR employee_id=?) ORDER BY employee_id DESC LIMIT 1',(holiday['id'],warehouse['id'],employee['id'])).fetchone()
                elif holiday and holiday.get('procurement_work_required'):
                    holiday_exception={'shift_id':None}
                requirement=c.execute("""SELECT r.shift_id FROM role_shift_requirements r JOIN shifts s ON s.id=r.shift_id
                    WHERE r.active_yn=1 AND r.department_id=? AND r.role_code=? AND r.effective_from<=?
                    AND (r.effective_to IS NULL OR r.effective_to>=?) AND s.active_yn=1 ORDER BY s.start_time,r.id LIMIT 1""",(employee['department_id'],employee['role_code'],day,day)).fetchone()
                group_key=(employee['department_id'],employee['warehouse_id'],employee['role_code'])
                available_group=available_groups.get(group_key,[])
                rotating=str(employee['department_name']).strip().lower()=='warehouse' and len(available_group)>1 and employee['id'] in available_group and len(employee_shifts)>1
                if rotating:
                    employee_index=available_group.index(employee['id'])
                    week_index=(cursor.toordinal()-1)//7
                    shift_id=employee_shifts[(employee_index+week_index)%len(employee_shifts)]['id']
                else:
                    required_id=requirement['shift_id']if requirement and any(item['id']==requirement['shift_id'] for item in employee_shifts) else None
                    shift_id=required_id if required_id else(employee_shifts[0]['id']if employee_shifts else None)
                shift=next((item for item in employee_shifts if item['id']==shift_id),None)
                day_type='OFF'if exception else('HOLIDAY_WORKING'if holiday and holiday_exception else('HOLIDAY'if holiday else('OFF'if warehouse_closed or procurement_closed else'WORKDAY')))
                if day_type not in ('WORKDAY','HOLIDAY_WORKING'):shift_id=None;shift=None
                if day_type=='HOLIDAY_WORKING':
                    shift_id=holiday_exception['shift_id']or shift_id;shift=next((item for item in employee_shifts if item['id']==shift_id),None)
                remarks=(f"{exception['availability_status']}: {exception['reason'] or exception['remarks'] or 'Unavailable'}"if exception else(f"PUBLIC HOLIDAY{' – WORK REQUIRED'if day_type=='HOLIDAY_WORKING'else''}: {holiday['holiday_name']} ({holiday.get('holiday_type')or'Public Holiday'})"if holiday else('Warehouse Closed'if warehouse_closed else('Procurement Closed'if procurement_closed else('Automatic seven-day role rotation'if rotating else None)))))
                existing=c.execute('SELECT id,manual_override_yn,status,holiday_id FROM employee_work_calendar WHERE employee_id=? AND calendar_date=?',(employee['id'],day)).fetchone()
                if existing and day_type in ('OFF','HOLIDAY'):
                    previous=dict(c.execute('SELECT * FROM employee_work_calendar WHERE id=?',(existing['id'],)).fetchone())
                    if previous.get('shift_id') or previous.get('override_start_time') or previous.get('override_end_time'):
                        log_audit(c,'employee_work_calendar',existing['id'],'UPDATE',user_id,previous,{'day_type':day_type,'reason':remarks,'trigger':'OPERATING_CALENDAR_CLOSURE'})
                    c.execute('UPDATE employee_work_calendar SET override_start_time=NULL,override_end_time=NULL,manual_override_yn=0 WHERE id=?',(existing['id'],))
                if not existing:
                    c.execute("""INSERT INTO employee_work_calendar(employee_id,department_id,warehouse_id,role_code,calendar_date,day_type,shift_id,shift_start,shift_end,holiday_id,status,assignment_source,remarks,created_by,warehouse_time_zone,warehouse_open_time,warehouse_close_time)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,'AUTO',?,?,?,?,?)""",(employee['id'],employee['department_id'],employee['warehouse_id'],employee['role_code'],day,day_type,shift_id,shift['start_time']if shift else None,shift['end_time']if shift else None,holiday['id']if holiday else None,'PUBLISHED',remarks,user_id,warehouse.get('time_zone')if warehouse else None,operating_day.get('open_time')if operating_day else None,operating_day.get('close_time')if operating_day else None));created+=1
                elif (not existing['manual_override_yn'] and existing['status'] != 'LOCKED') or day_type in ('OFF','HOLIDAY') or (trigger=='HOLIDAY_UPDATED' and existing and existing['holiday_id']):
                    c.execute("""UPDATE employee_work_calendar SET department_id=?,warehouse_id=?,role_code=?,day_type=?,shift_id=?,shift_start=?,shift_end=?,holiday_id=?,status=CASE WHEN status='LOCKED' THEN status ELSE 'PUBLISHED' END,assignment_source='AUTO',remarks=?,warehouse_time_zone=?,warehouse_open_time=?,warehouse_close_time=?,updated_at=datetime('now'),updated_by=? WHERE id=?""",(employee['department_id'],employee['warehouse_id'],employee['role_code'],day_type,shift_id,shift['start_time']if shift else None,shift['end_time']if shift else None,holiday['id']if holiday else None,remarks,warehouse.get('time_zone')if warehouse else None,operating_day.get('open_time')if operating_day else None,operating_day.get('close_time')if operating_day else None,user_id,existing['id']));updated+=1
                if not existing or (not existing['manual_override_yn'] and existing['status'] != 'LOCKED') or day_type in ('OFF','HOLIDAY') or (trigger=='HOLIDAY_UPDATED' and existing and existing['holiday_id']):
                    periods = location_work_periods(c,day,shift['start_time'],shift['end_time'],shift,warehouse,company,procurement,employee['id']) if shift else {'working_intervals': [], 'closed_breaks': [], 'working_minutes': 0}
                    c.execute('UPDATE employee_work_calendar SET work_periods_json=? WHERE employee_id=? AND calendar_date=?', (json.dumps(periods), employee['id'], day))
            cursor+=timedelta(days=1)
        c.execute("UPDATE calendar_coverage_warnings SET warning_status='RESOLVED',resolved_at=datetime('now'),resolved_by=? WHERE warning_status='OPEN' AND calendar_date BETWEEN ? AND ?",(user_id,start,end))
        warning_count=0;requirements=c.execute("""SELECT r.department_id,r.role_code,r.shift_id,r.minimum_staff FROM role_shift_requirements r JOIN shifts s ON s.id=r.shift_id WHERE r.active_yn=1 AND r.effective_from<=? AND(r.effective_to IS NULL OR r.effective_to>=?)AND s.active_yn=1""",(end,start)).fetchall();cursor=start_date
        while cursor<=end_date:
            day=cursor.isoformat()
            for requirement in requirements:
                warehouse_rows=c.execute("SELECT DISTINCT warehouse_id FROM employee_work_calendar WHERE calendar_date=? AND department_id=? AND role_code=?",(day,requirement['department_id'],requirement['role_code'])).fetchall()or[{'warehouse_id':None}]
                for warehouse_row in warehouse_rows:
                    wid=warehouse_row['warehouse_id']
                    active_day=c.execute("SELECT 1 FROM employee_work_calendar WHERE calendar_date=? AND department_id=? AND COALESCE(warehouse_id,-1)=COALESCE(?,-1) AND day_type IN ('WORKDAY','HOLIDAY_WORKING') LIMIT 1",(day,requirement['department_id'],wid)).fetchone()
                    if not active_day:continue
                    scope_shifts=warehouse_shifts.get(wid,[]) if wid is not None else shifts
                    required_shift=next((shift for shift in scope_shifts if shift['id']==requirement['shift_id']),None)
                    if not required_shift:continue
                    required_periods=location_work_periods(c,day,required_shift['start_time'],required_shift['end_time'],required_shift,warehouse_windows.get(wid),company,procurement)['working_intervals']
                    staff=c.execute("SELECT * FROM employee_work_calendar WHERE calendar_date=? AND department_id=? AND role_code=? AND shift_id=? AND day_type IN('WORKDAY','HOLIDAY_WORKING') AND COALESCE(warehouse_id,-1)=COALESCE(?,-1)",(day,requirement['department_id'],requirement['role_code'],requirement['shift_id'],wid)).fetchall()
                    staff_periods=[]
                    for entry in staff:
                        entry=dict(entry)
                        periods=location_work_periods(c,day,entry.get('override_start_time')or entry.get('shift_start')or required_shift['start_time'],entry.get('override_end_time')or entry.get('shift_end')or required_shift['end_time'],required_shift,warehouse_windows.get(wid),company,procurement,entry['employee_id'])
                        staff_periods.append(periods['working_intervals'])
                    counts=[]
                    for period in required_periods:
                        points={period['start'],period['end']}
                        for intervals in staff_periods:
                            for interval in intervals:
                                points.update(point for point in interval.values() if period['start']<point<period['end'])
                        for point in sorted(points)[:-1]:
                            counts.append(sum(any(interval['start']<=point<interval['end'] for interval in intervals) for intervals in staff_periods))
                    available=min(counts) if counts else requirement['minimum_staff']
                    if available<requirement['minimum_staff']:
                        c.execute("""INSERT INTO calendar_coverage_warnings(calendar_date,department_id,warehouse_id,role_code,shift_id,required_staff,available_staff,reason)VALUES(?,?,?,?,?,?,?,?)""",(day,requirement['department_id'],wid,requirement['role_code'],requirement['shift_id'],requirement['minimum_staff'],available,'Minimum active staffing requirement is not met'));warning_count+=1
            cursor+=timedelta(days=1)
        c.execute("""INSERT INTO calendar_regeneration_audit(trigger_type,employee_id,affected_from,affected_to,reason,assignments_changed,coverage_warnings,details_json,created_by)
            VALUES(?,?,?,?,?,?,?,?,?)""",(trigger,employee_id,start,end,reason,created+updated,warning_count,json.dumps({'active_employees':len(employees),'created':created,'updated':updated,'coverage_warnings':warning_count}),user_id))
    return {'created':created,'updated':updated,'employees':len(employees),'coverage_warnings':warning_count,'from':start,'to':end}
@router.get('/reference')
def reference(_u:User):
    saved=fetch_one("SELECT value FROM settings WHERE key='helper_supervisor_roles'")
    helper_roles=[value for value in str((saved or{}).get('value')or'WarehouseManager,WarehouseSupervisor,Storekeeper').split(',')if value]
    procurement=procurement_configuration();visible_shifts=fetch_all("SELECT s.*,w.name warehouse_name FROM shifts s LEFT JOIN warehouses w ON w.id=s.warehouse_id WHERE s.active_yn=1 AND((s.warehouse_id IS NULL AND ?=1)OR(s.warehouse_id IS NOT NULL AND w.deleted_at IS NULL AND w.shifts_enabled_yn=1))ORDER BY COALESCE(w.name,'Company / Procurement'),s.start_time",(procurement['shifts_enabled_yn'],))
    return {'countries':fetch_all('SELECT * FROM countries WHERE active_yn=1 ORDER BY country_name'),'cities':fetch_all('SELECT * FROM cities WHERE active_yn=1 ORDER BY country_code,city_name'),'currencies':fetch_all('SELECT * FROM currencies WHERE active_yn=1 ORDER BY currency_code'),'exchange_rates':fetch_all('SELECT * FROM exchange_rates ORDER BY effective_date DESC'),'holidays':fetch_all('SELECT * FROM holidays ORDER BY holiday_date DESC'),'shifts':visible_shifts,'warehouses':fetch_all('SELECT id,warehouse_code,name,country_code,region_province,operating_start_time,operating_end_time,shifts_enabled_yn FROM warehouses WHERE deleted_at IS NULL ORDER BY name'),'company':fetch_one('SELECT country_code,region_province,base_currency,time_zone,name,logo_url FROM company WHERE deleted_at IS NULL ORDER BY id DESC LIMIT 1'),'helper_supervisor_roles':helper_roles,'shift_mode':{'procurement':procurement}}
def insert(table,fields,body,user):
    keys=[k for k in fields if k in body]
    with transaction(immediate=True)as c:cur=c.execute(f"INSERT INTO {table}({','.join(keys)},created_by)VALUES({','.join('?'for _ in keys)},?)",tuple(body[k]for k in keys)+(user['id'],));log_audit(c,table,cur.lastrowid,'CREATE',user['id'],after=body);rid=cur.lastrowid
    return {'id':rid}
@router.post('/countries',status_code=201)
def country(b:dict,u:dict=Depends(admin)):b['country_code']=str(b.get('country_code')or b.get('iso_alpha2')or'').upper();return insert('countries',['country_code','country_name','iso_alpha2','iso_alpha3','default_currency_code','phone_code','active_yn'],b,u)
@router.post('/cities',status_code=201)
def city(b:dict,u:dict=Depends(admin)):return insert('cities',['country_code','city_name','city_code','state_province_region','major_city_yn'],b,u)
@router.post('/currencies',status_code=201)
def currency(b:dict,u:dict=Depends(admin)):return insert('currencies',['currency_code','currency_name','currency_symbol','decimal_places','decimal_separator','thousand_separator','symbol_position','active_yn'],b,u)
@router.post('/exchange-rates',status_code=201)
def rate(b:dict,u:dict=Depends(admin)):
    from_currency=str(b.get('from_currency')or'').strip().upper();to_currency=str(b.get('to_currency')or'').strip().upper()
    try:conversion_rate=float(b.get('rate'));assert conversion_rate>0;effective_date=date.fromisoformat(str(b.get('effective_date'))).isoformat()
    except(TypeError,ValueError,AssertionError):raise HTTPException(400,'Manual exchange rates require a positive rate and valid effective date')
    if from_currency==to_currency:raise HTTPException(400,'Manual exchange rates require two different currencies')
    for currency in(from_currency,to_currency):
        if not fetch_one('SELECT id FROM currencies WHERE currency_code=? AND active_yn=1',(currency,)):raise HTTPException(400,f'{currency or "Currency"} is not an active currency')
    if fetch_one('SELECT id FROM exchange_rates WHERE from_currency=? AND to_currency=? AND effective_date=?',(from_currency,to_currency,effective_date)):raise HTTPException(409,'An exchange rate already exists for this currency pair and effective date')
    expiry_date=None
    if b.get('expiry_date'):
        try:expiry_date=date.fromisoformat(str(b['expiry_date'])).isoformat()
        except ValueError:raise HTTPException(400,'Expiry date must use YYYY-MM-DD format')
        if expiry_date<effective_date:raise HTTPException(400,'Expiry date cannot be before the effective date')
    source=f"Manual Rate — {str(b.get('source')or'Authorized Supply Chain Manager entry').strip()}"
    return insert('exchange_rates',['from_currency','to_currency','rate','effective_date','expiry_date','source','manual_yn','active_yn'],{**b,'from_currency':from_currency,'to_currency':to_currency,'rate':conversion_rate,'effective_date':effective_date,'expiry_date':expiry_date,'source':source,'manual_yn':1,'active_yn':1},u)

@router.delete('/exchange-rates/{rate_id}')
def delete_exchange_rate(rate_id:int,u:dict=Depends(admin)):
    before=fetch_one('SELECT * FROM exchange_rates WHERE id=?',(rate_id,))
    if not before:raise HTTPException(404,'Exchange rate not found')
    if not before['active_yn']:raise HTTPException(409,'Exchange rate is already inactive')
    with transaction(immediate=True)as c:c.execute('UPDATE exchange_rates SET active_yn=0 WHERE id=?',(rate_id,));after=c.execute('SELECT * FROM exchange_rates WHERE id=?',(rate_id,)).fetchone();log_audit(c,'exchange_rates',rate_id,'DELETE',u['id'],before,dict(after))
    return {'success':True,'id':rate_id,'message':'Exchange rate deactivated. Historical evidence was retained.'}
@router.post('/exchange-rates/synchronize')
def synchronize_exchange_rate(b:dict,u:dict=Depends(admin)):
    country_code=str(b.get('country_code')or'').strip().upper()
    country=fetch_one('SELECT default_currency_code FROM countries WHERE active_yn=1 AND (upper(country_code)=? OR upper(iso_alpha2)=? OR upper(iso_alpha3)=?)',(country_code,country_code,country_code))if country_code else None
    company=fetch_one("SELECT COALESCE(base_currency,currency,'SAR') base_currency FROM company WHERE deleted_at IS NULL ORDER BY id DESC LIMIT 1")or{'base_currency':'SAR'}
    from_currency=str(b.get('from_currency')or(country or{}).get('default_currency_code')or'').strip().upper();to_currency=str(b.get('to_currency')or company['base_currency']).strip().upper()
    if not fetch_one('SELECT id FROM currencies WHERE currency_code=? AND active_yn=1',(from_currency,))or not fetch_one('SELECT id FROM currencies WHERE currency_code=? AND active_yn=1',(to_currency,)):raise HTTPException(400,'Select active source and target currencies')
    effective_date=str(b.get('effective_date')or date.today().isoformat());expiry_date=str(b.get('expiry_date')or'').strip()or None
    try:date.fromisoformat(effective_date)
    except ValueError:raise HTTPException(400,'Effective date must use YYYY-MM-DD format')
    if expiry_date:
        try:date.fromisoformat(expiry_date)
        except ValueError:raise HTTPException(400,'Expiry date must use YYYY-MM-DD format')
        if expiry_date<effective_date:raise HTTPException(400,'Expiry date cannot be before the effective date')
    if from_currency==to_currency:conversion_rate=1.0;source='System parity rate'
    else:
        api_key=os.getenv('EXCHANGE_RATE_API_KEY','').strip();base_url=os.getenv('EXCHANGE_RATE_API_URL','https://v6.exchangerate-api.com/v6').rstrip('/')
        if not api_key:raise HTTPException(503,'Authenticated exchange-rate synchronization requires EXCHANGE_RATE_API_KEY on the FastAPI server')
        try:
            response=httpx.get(f'{base_url}/{api_key}/pair/{from_currency}/{to_currency}',timeout=15.0,headers={'Accept':'application/json','User-Agent':'Procuraflo/1.0'});response.raise_for_status();payload=response.json()
            if payload.get('result')!='success' or float(payload.get('conversion_rate')or 0)<=0:raise ValueError(str(payload.get('error-type')or'Invalid exchange-rate response'))
            conversion_rate=float(payload['conversion_rate']);source='ExchangeRate-API v6 (authenticated)'
        except (httpx.HTTPError,ValueError,TypeError)as exc:raise HTTPException(502,f'Authenticated exchange-rate synchronization failed; existing rates were retained. ({type(exc).__name__})')
    if not b.get('confirm'):
        return {'preview':True,'from_currency':from_currency,'to_currency':to_currency,'rate':conversion_rate,'effective_date':effective_date,'expiry_date':expiry_date,'source':source,'country_code':country_code or None,'message':'Exchange rate retrieved and validated. Review it, then confirm to make it available for new transactions.'}
    try:expected_rate=float(b.get('expected_rate'))
    except(TypeError,ValueError):raise HTTPException(409,'Preview the current provider rate before confirming it')
    if abs(expected_rate-conversion_rate)>max(1e-12,abs(conversion_rate)*1e-9):raise HTTPException(409,'The provider rate changed after preview. Preview the updated rate before confirming.')
    before=fetch_one('SELECT * FROM exchange_rates WHERE from_currency=? AND to_currency=? AND effective_date=?',(from_currency,to_currency,effective_date))
    with transaction(immediate=True)as c:
        c.execute("""INSERT INTO exchange_rates(from_currency,to_currency,rate,effective_date,expiry_date,source,manual_yn,active_yn,created_by,synchronized_at,synchronized_by)
          VALUES(?,?,?,?,?,?,0,1,?,datetime('now'),?) ON CONFLICT(from_currency,to_currency,effective_date) DO UPDATE SET rate=excluded.rate,expiry_date=excluded.expiry_date,source=excluded.source,manual_yn=0,active_yn=1,synchronized_at=datetime('now'),synchronized_by=excluded.synchronized_by""",(from_currency,to_currency,conversion_rate,effective_date,expiry_date,source,u['id'],u['id']))
        row=c.execute('SELECT * FROM exchange_rates WHERE from_currency=? AND to_currency=? AND effective_date=?',(from_currency,to_currency,effective_date)).fetchone();log_audit(c,'exchange_rates',row['id'],'UPDATE'if before else'CREATE',u['id'],before,dict(row))
    return {**dict(row),'confirmed':True,'country_code':country_code or None,'message':f'{from_currency} to {to_currency} confirmed at {conversion_rate:g} from {source}.'}
@router.post('/holidays',status_code=201)
def holiday(b:dict,u:dict=Depends(admin)):
    validate_holiday_scope(b)
    holiday_bounds(b)
    required=('country_code','holiday_name','holiday_date','holiday_type');missing=[key for key in required if not str(b.get(key)or'').strip()]
    if missing:raise HTTPException(400,f"Required holiday fields: {', '.join(missing)}")
    if not fetch_one('SELECT country_code FROM countries WHERE country_code=? AND active_yn=1',(b['country_code'],)):raise HTTPException(400,'Select an active country')
    try:official=date.fromisoformat(str(b['holiday_date']));observed=date.fromisoformat(str(b.get('observed_date')or b['holiday_date']))
    except ValueError:raise HTTPException(400,'Holiday and observed dates must use YYYY-MM-DD format')
    if b.get('day_scope')not in(None,'FULL_DAY','PARTIAL_DAY'):raise HTTPException(400,'Holiday day scope must be FULL_DAY or PARTIAL_DAY')
    if b.get('day_scope')=='PARTIAL_DAY'and(not b.get('start_time')or not b.get('end_time')):raise HTTPException(400,'Partial-day holidays require start and end times')
    if fetch_one("SELECT id FROM holidays WHERE country_code=? AND lower(holiday_name)=lower(?) AND holiday_date=? AND COALESCE(region,'')=COALESCE(?, '') AND active_yn=1",(b['country_code'],str(b['holiday_name']).strip(),official.isoformat(),b.get('region'))):raise HTTPException(409,'An active holiday with this country, region, name, and date already exists')
    b={**b,'holiday_end_date':b.get('holiday_end_date')or None,'applicability':b.get('applicability')or'ALL','holiday_date':official.isoformat(),'observed_date':observed.isoformat(),'calendar_year':official.year,'government_yn':int(bool(b.get('government_yn',1))),'statutory_yn':int(bool(b.get('statutory_yn',1))),'active_yn':int(bool(b.get('active_yn',1)))}
    record=insert('holidays',['country_code','region','holiday_name','holiday_date','holiday_end_date','observed_date','calendar_year','holiday_type','day_scope','start_time','end_time','government_yn','statutory_yn','paid_holiday_yn','recurring_yn','applicability','source','notes','active_yn','warehouse_id','procurement_work_required','procurement_work_reason'],b,u)
    record['calendar_update']=refresh_holiday_range(b,u['id'],'HOLIDAY_ACTIVATED');return record

@router.put('/holidays/{holiday_id}')
def update_holiday(holiday_id:int,b:dict,u:dict=Depends(admin)):
    b={**b,**({'holiday_end_date':b.get('holiday_end_date')or None} if 'holiday_end_date' in b else {})}
    before=fetch_one('SELECT * FROM holidays WHERE id=?',(holiday_id,))
    if not before:raise HTTPException(404,'Holiday not found')
    validate_holiday_scope({**before,**b})
    if 'holiday_date' in b and 'observed_date' not in b and (not before.get('observed_date') or before.get('observed_date')==before['holiday_date']):
        b={**b,'observed_date':b['holiday_date']}
    merged={**before,**b}
    holiday_bounds(merged)
    try:
        date.fromisoformat(str(merged['holiday_date']));date.fromisoformat(str(merged.get('observed_date')or merged['holiday_date']))
    except (ValueError,TypeError):raise HTTPException(400,'Holiday and observed dates must use YYYY-MM-DD format')
    fields=['region','holiday_name','holiday_date','holiday_end_date','observed_date','holiday_type','day_scope','start_time','end_time','government_yn','statutory_yn','paid_holiday_yn','recurring_yn','applicability','source','notes','active_yn','warehouse_id','procurement_work_required','procurement_work_reason'];keys=[key for key in fields if key in b]
    if not keys:raise HTTPException(400,'No holiday fields supplied')
    with transaction(immediate=True)as c:c.execute(f"UPDATE holidays SET {','.join(key+'=?'for key in keys)},updated_by=?,updated_at=datetime('now') WHERE id=?",tuple(b[key]for key in keys)+(u['id'],holiday_id));log_audit(c,'holidays',holiday_id,'UPDATE',u['id'],before,b)
    after=fetch_one('SELECT * FROM holidays WHERE id=?',(holiday_id,))
    for holiday_record in (before,after):
        refresh_holiday_range(holiday_record,u['id'],'HOLIDAY_UPDATED')
    return fetch_one('SELECT * FROM holidays WHERE id=?',(holiday_id,))

@router.post('/holiday-work-exceptions',status_code=201)
def holiday_work_exception(b:dict,u:dict=Depends(admin)):
    holiday_row=fetch_one('SELECT * FROM holidays WHERE id=? AND active_yn=1',(b.get('holiday_id'),));warehouse=fetch_one('SELECT id FROM warehouses WHERE id=? AND deleted_at IS NULL',(b.get('warehouse_id'),))
    if not holiday_row or not warehouse or not str(b.get('reason')or'').strip():raise HTTPException(400,'Select an active holiday, warehouse, and provide an operational reason')
    if b.get('shift_id') and not fetch_one('SELECT id FROM shifts WHERE id=? AND warehouse_id=? AND active_yn=1',(b['shift_id'],warehouse['id'])):
        raise HTTPException(400,'Holiday work must use an active shift belonging to the selected warehouse')
    record=insert('holiday_work_exceptions',['holiday_id','warehouse_id','employee_id','shift_id','work_required','reason','approved_by'],{**b,'work_required':1,'approved_by':u['id']},u)
    record['calendar_update']=refresh_holiday_range(holiday_row,u['id'],'HOLIDAY_WORK_EXCEPTION');return record
@router.get('/availability')
def availability(_u:dict=Depends(admin)):return fetch_all('SELECT a.*,e.employee_code,e.name employee_name,d.name department_name FROM employee_availability a JOIN employees e ON e.id=a.employee_id LEFT JOIN departments d ON d.id=e.department_id ORDER BY a.date_from DESC')
@router.post('/availability',status_code=201)
def add_availability(b:dict,u:dict=Depends(admin)):
    status=str(b.get('availability_status')or'Unavailable')
    if status not in EXCEPTION_STATUSES:raise HTTPException(400,'Only unavailable employee exceptions are entered manually')
    if not str(b.get('reason')or'').strip():raise HTTPException(400,'A reason is required for employee unavailability')
    if not fetch_one("SELECT id FROM employees WHERE id=? AND status='Active' AND deleted_at IS NULL",(b.get('employee_id'),)):raise HTTPException(400,'Select a valid active employee')
    try:
        if date.fromisoformat(str(b.get('date_to')))<date.fromisoformat(str(b.get('date_from'))):raise HTTPException(400,'Unavailability end date cannot be before its start date')
    except (TypeError,ValueError):raise HTTPException(400,'Valid unavailability start and end dates are required')
    b['availability_status']=status;record=insert('employee_availability',['employee_id','date_from','date_to','availability_status','reason','remarks'],b,u)
    record['calendar_update']=generate_calendar_range(b.get('date_from'),b.get('date_to'),u['id'],b.get('employee_id'),'EMPLOYEE_UNAVAILABLE',b.get('reason'));return record
@router.get('/coverage')
def coverage(_u:dict=Depends(admin)):return fetch_all('SELECT r.*,d.name department_name,s.shift_code,s.shift_label FROM role_shift_requirements r JOIN departments d ON d.id=r.department_id JOIN shifts s ON s.id=r.shift_id WHERE r.active_yn=1 ORDER BY d.name,r.role_code,s.start_time')
@router.post('/coverage',status_code=201)
def add_coverage(b:dict,u:dict=Depends(admin)):
    department=fetch_one('SELECT name FROM departments WHERE id=? AND deleted_at IS NULL',(b.get('department_id'),));shift_row=fetch_one('SELECT id FROM shifts WHERE id=? AND active_yn=1',(b.get('shift_id'),));role=str(b.get('role_code')or'')
    if not department or not any(word in department['name'].lower()for word in('warehouse','procurement','purchas')):raise HTTPException(400,'Coverage is limited to Warehouse and Procurement departments')
    allowed={'WarehouseManager','WarehouseSupervisor','Storekeeper','Helper','SupplyChainManager'}if'warehouse'in department['name'].lower()else{'PurchaseManager','PurchaseOfficer','SupplyChainManager'}
    if role not in allowed or not shift_row or int(b.get('minimum_staff')or 0)<1:raise HTTPException(400,'Select a valid role, active shift, and minimum staff of at least one')
    if fetch_one("SELECT id FROM role_shift_requirements WHERE department_id=? AND role_code=? AND shift_id=? AND active_yn=1",(b.get('department_id'),role,b.get('shift_id'))):raise HTTPException(409,'An active coverage requirement already exists for this department, role, and shift')
    b['minimum_staff']=int(b['minimum_staff']);b['effective_from']=b.get('effective_from')or date.today().isoformat();return insert('role_shift_requirements',['department_id','role_code','shift_id','minimum_staff','effective_from'],b,u)
def calendar_period_detail(row):
    result=dict(row)
    working=result.get('day_type') in ('WORKDAY','HOLIDAY_WORKING')
    holiday_type=result.get('holiday_type')or'Public Holiday'
    if result.get('holiday_id'):
        result['operating_status']='Closed' if holiday_type=='Emergency Closure' else ('Statutory Holiday' if 'statutory' in holiday_type.lower() else 'Public Holiday' if 'public' in holiday_type.lower() or 'national' in holiday_type.lower() else holiday_type)
        result['display_label']=result.get('holiday_name')or result['operating_status']
        if working:result['display_label']+=' - Work Required'
    elif not working:
        result['operating_status']='Off Day / Closed'
        result['display_label']='Off Day / Closed'
    else:
        result['operating_status']='Working Day';result['display_label']=result.get('shift_label')or'Working Day'
    if not working:
        result.update({key:None for key in ('shift_start','shift_end','override_start_time','override_end_time','shift_label','shift_code')})
        periods={'working_intervals':[],'closed_breaks':[],'working_minutes':0}
        result.update(periods);result['work_periods_json']=json.dumps(periods)
        return result
    if result.get('shift_id') and result.get('day_type') in ('WORKDAY','HOLIDAY_WORKING'):
        shift=fetch_one('SELECT * FROM shifts WHERE id=?',(result['shift_id'],))
        if shift:
            warehouse=fetch_one('SELECT * FROM warehouses WHERE id=?',(shift.get('warehouse_id'),)) if shift.get('warehouse_id') else None
            company=fetch_one('SELECT * FROM company WHERE deleted_at IS NULL ORDER BY id DESC LIMIT 1')or{}
            with transaction() as c:
                periods=location_work_periods(c,result['calendar_date'],result.get('override_start_time')or result.get('shift_start')or shift['start_time'],result.get('override_end_time')or result.get('shift_end')or shift['end_time'],shift,warehouse,company,procurement_configuration(),result['employee_id'])
            result.update(periods)
            result['work_periods_json']=json.dumps(periods)
    else:
        result.update({'working_intervals': [], 'closed_breaks': [], 'working_minutes': None})
    return result

@router.get('/calendar')
def calendar(request:Request,user:User):
    q=request.query_params;period=q.get('period','current');today=date.today();default_start=today+timedelta(days=15 if period=='next'else 0);default_end=default_start+timedelta(days=14);start=q.get('from')or default_start.isoformat();end=q.get('to')or default_end.isoformat();scope=q.get('scope','');wid=int(q.get('warehouse_id')or 0)
    if wid and user['role']!='SupplyChainManager'and wid not in user['warehouse_ids']:raise HTTPException(403,'Warehouse calendar access denied')
    generation=generate_calendar_range(start,end,user['id']);rows=fetch_all("SELECT c.*,e.employee_code,e.name employee_name,d.name department_name,s.shift_code,s.shift_label,h.holiday_name,h.holiday_type,h.notes holiday_notes,w.warehouse_code,w.name warehouse_name,m.name reports_to_name,m.approval_role reports_to_role,COALESCE((SELECT a.availability_status FROM employee_availability a WHERE a.employee_id=c.employee_id AND a.date_from<=c.calendar_date AND a.date_to>=c.calendar_date AND a.availability_status<>'Available' ORDER BY a.created_at DESC,a.id DESC LIMIT 1),'Available')availability_status FROM employee_work_calendar c JOIN employees e ON e.id=c.employee_id JOIN departments d ON d.id=c.department_id LEFT JOIN employees m ON m.id=e.reports_to_employee_id LEFT JOIN warehouses w ON w.id=c.warehouse_id LEFT JOIN shifts s ON s.id=c.shift_id LEFT JOIN holidays h ON h.id=c.holiday_id WHERE c.calendar_date BETWEEN ? AND ? AND e.deleted_at IS NULL AND e.status='Active' AND(?=''OR lower(d.name)=lower(?))AND(?=0 OR c.warehouse_id=?)AND(c.status='PUBLISHED'OR ?='SupplyChainManager') ORDER BY c.calendar_date,s.start_time,e.name",(start,end,scope,scope,wid,wid,user['role']));warehouses=fetch_all('SELECT id,warehouse_code,name FROM warehouses WHERE deleted_at IS NULL ORDER BY name')if user['role']=='SupplyChainManager'else fetch_all(f"SELECT id,warehouse_code,name FROM warehouses WHERE deleted_at IS NULL AND id IN({','.join('?'for _ in user['warehouse_ids'])or'NULL'}) ORDER BY name",user['warehouse_ids']);return {'range':{'from':start,'to':end},'warehouse_id':wid,'rows':[calendar_period_detail(row) for row in rows],'generation':generation,'warehouses':warehouses}

def set_calendar_status(b:dict,u:dict):
    status=str(b.get('status')or'')
    if status not in {'PROVISIONAL','PUBLISHED','LOCKED'}:raise HTTPException(400,'Select Provisional, Published, or Locked status')
    with transaction(immediate=True)as c:
        cur=c.execute("UPDATE employee_work_calendar SET status=?,updated_at=datetime('now'),updated_by=? WHERE calendar_date BETWEEN ? AND ? AND(?=''OR department_id=(SELECT id FROM departments WHERE lower(name)=lower(?)LIMIT 1))AND(?=0 OR warehouse_id=?)",(status,u['id'],b.get('from'),b.get('to'),b.get('scope',''),b.get('scope',''),b.get('warehouse_id')or 0,b.get('warehouse_id')or 0));log_audit(c,'employee_work_calendar',0,'UPDATE',u['id'],after={**b,'operation':'BULK_STATUS','updated':cur.rowcount})
    return {'updated':cur.rowcount,'status':status}

@router.put('/calendar/bulk-status')
def bulk_status(b:dict,u:dict=Depends(admin)):return set_calendar_status(b,u)
@router.put('/calendar/{entry_id}')
def update_calendar(entry_id:int,b:dict,u:dict=Depends(admin)):
    before=fetch_one('SELECT * FROM employee_work_calendar WHERE id=?',(entry_id,));
    if not before:raise HTTPException(404,'Calendar entry not found')
    if not str(b.get('reason')or'').strip():raise HTTPException(400,'Adjustment reason is required')
    if before.get('status')=='LOCKED'and not b.get('unlock'):raise HTTPException(409,'Locked calendar entries require controlled unlock confirmation')
    if b.get('day_type')=='WORKDAY'and not b.get('shift_id'):raise HTTPException(400,'A workday requires an assigned shift')
    target_warehouse=b.get('warehouse_id',before.get('warehouse_id'))
    if 'warehouse_id'in b:
        assigned=fetch_one("""SELECT 1 ok FROM employee_warehouse_assignments WHERE employee_id=? AND active_yn=1
          AND(all_warehouses_yn=1 OR warehouse_id=?)AND effective_from<=?AND(effective_to IS NULL OR effective_to>=?)""",(before['employee_id'],target_warehouse,before['calendar_date'],before['calendar_date']))
        if not assigned:raise HTTPException(403,'The employee is not assigned to the selected warehouse for this workday')
        warehouse=fetch_one('SELECT id,time_zone FROM warehouses WHERE id=? AND deleted_at IS NULL',(target_warehouse,))
        if not warehouse:raise HTTPException(400,'Select an active warehouse')
        schedule=fetch_one('SELECT is_open,open_time,close_time FROM warehouse_operating_schedules WHERE warehouse_id=? AND weekday=?',(target_warehouse,date.fromisoformat(before['calendar_date']).weekday()))
        if b.get('day_type','WORKDAY')=='WORKDAY'and schedule and not schedule['is_open']:raise HTTPException(409,'The selected warehouse is closed on this local workday')
        b={**b,'warehouse_time_zone':warehouse['time_zone'],'warehouse_open_time':schedule.get('open_time')if schedule else None,'warehouse_close_time':schedule.get('close_time')if schedule else None}
    if b.get('shift_id'):
        selected_shift=fetch_one('SELECT id,warehouse_id FROM shifts WHERE id=? AND active_yn=1',(b['shift_id'],))
        if not selected_shift:raise HTTPException(400,'The selected shift is inactive or does not exist')
        if selected_shift.get('warehouse_id')!=target_warehouse:raise HTTPException(400,'The selected shift does not belong to this employee warehouse')
    requested_type=b.get('day_type',before['day_type'])
    if requested_type in ('WORKDAY','HOLIDAY_WORKING'):
        employee=fetch_one('SELECT d.name department_name FROM employees e JOIN departments d ON d.id=e.department_id WHERE e.id=?',(before['employee_id'],))or{}
        warehouse=fetch_one('SELECT * FROM warehouses WHERE id=? AND deleted_at IS NULL',(target_warehouse,)) if str(employee.get('department_name')).lower()=='warehouse' else None
        day=before['calendar_date'];weekday=date.fromisoformat(day).weekday()
        company=fetch_one('SELECT * FROM company WHERE deleted_at IS NULL ORDER BY id DESC LIMIT 1')or{}
        applicable=fetch_all("SELECT * FROM holidays WHERE active_yn=1 AND COALESCE(observed_date,holiday_date)<=? AND COALESCE(holiday_end_date,observed_date,holiday_date)>=?",(day,day))
        matched=[item for item in applicable if holiday_applies(item,day,warehouse,company)]
        for holiday in matched:
            approved=(fetch_one('SELECT * FROM holiday_work_exceptions WHERE holiday_id=? AND warehouse_id=? AND work_required=1 AND(employee_id IS NULL OR employee_id=?)',(holiday['id'],warehouse['id'],before['employee_id'])) if warehouse else holiday.get('procurement_work_required'))
            if not approved:raise HTTPException(409,'This location is closed for '+holiday['holiday_name']+'. Configure an approved holiday-work exception first.')
        if matched:b={**b,'day_type':'HOLIDAY_WORKING'}
        if warehouse:
            schedule=fetch_one('SELECT * FROM warehouse_operating_schedules WHERE warehouse_id=? AND weekday=?',(warehouse['id'],weekday))
            closed=weekday not in json.loads(warehouse.get('operating_days_json')or'[]') or (schedule and not schedule['is_open'])
        else:closed=weekday not in procurement_configuration()['operating_days']
        if closed and not matched:raise HTTPException(409,'This location is closed on the selected weekday. Update its operating calendar before scheduling work.')
    fields=['warehouse_id','warehouse_time_zone','warehouse_open_time','warehouse_close_time','day_type','shift_id','override_start_time','override_end_time','status','remarks'];keys=[k for k in fields if k in b]
    if not keys:raise HTTPException(400,'No calendar adjustment fields were supplied')
    with transaction(immediate=True)as c:
        c.execute(f"UPDATE employee_work_calendar SET {','.join(k+'=?'for k in keys)},assignment_source='MANUAL',manual_override_yn=1,schedule_version=schedule_version+1,updated_at=datetime('now'),updated_by=? WHERE id=?",tuple(b[k]for k in keys)+(u['id'],entry_id));after=c.execute('SELECT * FROM employee_work_calendar WHERE id=?',(entry_id,)).fetchone();c.execute('INSERT INTO calendar_overrides(calendar_entry_id,old_values,new_values,adjustment_reason,remarks,changed_by)VALUES(?,?,?,?,?,?)',(entry_id,json.dumps(before,default=str),json.dumps(dict(after),default=str),str(b['reason']).strip(),b.get('remarks'),u['id']));log_audit(c,'employee_work_calendar',entry_id,'UPDATE',u['id'],before,{**b,'controlled_unlock':bool(b.get('unlock'))})
        entry=dict(after)
        selected=fetch_one('SELECT * FROM shifts WHERE id=?',(entry.get('shift_id'),))
        if selected and entry['day_type'] in ('WORKDAY','HOLIDAY_WORKING'):
            start=entry.get('override_start_time')or selected['start_time'];end=entry.get('override_end_time')or selected['end_time']
            periods=location_work_periods(c,entry['calendar_date'],start,end,selected,warehouse,company,procurement_configuration(),entry['employee_id'])
            if not periods['working_intervals']:raise HTTPException(409,'The selected hours are closed for a scheduled break')
        else:periods={'working_intervals':[],'closed_breaks':[],'working_minutes':0}
        c.execute('UPDATE employee_work_calendar SET work_periods_json=? WHERE id=?',(json.dumps(periods),entry_id))
    return {'success':True}
@router.get('/coverage-warnings')
def warnings(_u:dict=Depends(admin)):return fetch_all('SELECT cw.*,d.name department_name,w.name warehouse_name,s.shift_label FROM calendar_coverage_warnings cw LEFT JOIN departments d ON d.id=cw.department_id LEFT JOIN warehouses w ON w.id=cw.warehouse_id LEFT JOIN shifts s ON s.id=cw.shift_id ORDER BY cw.calendar_date DESC,cw.id DESC')
@router.post('/calendar/export-audit',status_code=201)
def export_audit(b:dict,u:User):return insert('calendar_download_audit',['action_type','format','department_scope','warehouse_id','date_from','date_to'],b,u)
@router.post('/calendar/generate')
def generate(b:dict|None=None,u:dict=Depends(admin)):
    b=b or{}
    start=b.get('from')or datetime.now().date().isoformat();end=b.get('to')or(datetime.now().date()+timedelta(days=30)).isoformat();result=generate_calendar_range(start,end,u['id'],trigger='MANUAL_REGENERATION');return {**result,'message':'Active employees were scheduled automatically; recorded unavailability exceptions were applied.'}
@router.post('/holidays/synchronize')
def synchronize(b:dict,u:dict=Depends(admin)):
    country_code=str(b.get('country_code')or'').strip().upper()
    try:year=int(b.get('year'));assert 2000<=year<=2049
    except(TypeError,ValueError,AssertionError):raise HTTPException(400,'Calendarific supports calendar years from 2000 through 2049')
    country=fetch_one('SELECT country_code,iso_alpha2 FROM countries WHERE active_yn=1 AND (upper(country_code)=? OR upper(iso_alpha2)=?)',(country_code,country_code))
    if not country:raise HTTPException(400,'Select an active country before synchronizing official holidays')
    provider=os.getenv('CALENDARIFIC_API_URL','https://calendarific.com/api/v2').rstrip('/')
    fallback_provider=os.getenv('NAGER_HOLIDAY_API_URL','https://date.nager.at/api/v3').rstrip('/')
    api_key=os.getenv('CALENDARIFIC_API_KEY','').strip()
    records=[];source='Calendarific Holiday API';fallback_reason=None
    if api_key:
        try:
            response=httpx.get(f"{provider}/holidays",params={'api_key':api_key,'country':country['iso_alpha2'],'year':year,'type':'national,local,religious'},timeout=15.0,headers={'Accept':'application/json','User-Agent':'Procuraflo/1.0'})
            response.raise_for_status();payload=response.json();meta=payload.get('meta')or{}
            if int(meta.get('code')or response.status_code)!=200:raise ValueError(str(meta.get('error_detail')or meta.get('error_type')or'Calendarific rejected the request'))
            records=((payload.get('response')or{}).get('holidays'))
            if not isinstance(records,list):raise ValueError('Calendarific returned an invalid response')
            if not records:fallback_reason='Calendarific returned no holiday records'
        except (httpx.HTTPError,ValueError) as exc:fallback_reason=f'Calendarific {type(exc).__name__}'
    else:fallback_reason='Calendarific API key is not configured'
    if fallback_reason:
        try:
            response=httpx.get(f"{fallback_provider}/PublicHolidays/{year}/{country['iso_alpha2']}",timeout=15.0,headers={'Accept':'application/json','User-Agent':'Procuraflo/1.0'})
            response.raise_for_status();fallback_records=response.json()
            if not isinstance(fallback_records,list)or not fallback_records:raise ValueError('Nager.Date returned no holiday records')
            records=[{'name':item.get('localName')or item.get('name'),'description':'Fallback public-holiday record from Nager.Date.','date':{'iso':item.get('date')},'type':item.get('types')or['Public']}for item in fallback_records]
            source='Nager.Date Public Holidays API'
        except (httpx.HTTPError,ValueError) as exc:raise HTTPException(502,f'Both official holiday providers are unavailable; existing manual holiday records were retained. ({fallback_reason}; Nager.Date {type(exc).__name__})')
    candidates=[]
    for item in records:
        holiday_date=str((item.get('date')or{}).get('iso')or'')[:10]
        try:official=date.fromisoformat(holiday_date)
        except ValueError:continue
        name=str(item.get('name')or'').strip()
        if official.year!=year or not name:continue
        holiday_types=[str(value).lower()for value in(item.get('type')or[])]
        holiday_type='Religious Public Holiday'if any('religious'in value for value in holiday_types)else('Regional / Provincial / State Holiday'if any(value in('local','state')for value in holiday_types)else'Government Public Holiday')
        candidates.append({'holiday_name':name,'holiday_date':holiday_date,'holiday_type':holiday_type,'description':str(item.get('description')or'').strip()})
    candidates=sorted({(item['holiday_name'],item['holiday_date']):item for item in candidates}.values(),key=lambda item:(item['holiday_date'],item['holiday_name']))
    fingerprint=hashlib.sha256(json.dumps(candidates,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    existing=sum(1 for item in candidates if fetch_one('SELECT id FROM holidays WHERE country_code=? AND holiday_name=? AND holiday_date=?',(country['country_code'],item['holiday_name'],item['holiday_date'])))
    if not b.get('confirm'):
        return {'preview':True,'country_code':country['country_code'],'year':year,'provider':source,'fallback_used':source.startswith('Nager.Date'),'fallback_reason':fallback_reason if source.startswith('Nager.Date')else None,'candidate_count':len(candidates),'existing':existing,'new_count':len(candidates)-existing,'fingerprint':fingerprint,'holidays':candidates,'message':f'{len(candidates)} official holidays retrieved from {source}; {len(candidates)-existing} are new. Review and confirm before calendar changes are made.'}
    if not b.get('expected_fingerprint')or b.get('expected_fingerprint')!=fingerprint:raise HTTPException(409,'The provider holiday data changed after preview. Preview the updated holidays before confirming.')
    created=0;affected=[]
    with transaction(immediate=True)as c:
        for item in candidates:
            holiday_date=item['holiday_date'];name=item['holiday_name']
            found=c.execute('SELECT id FROM holidays WHERE country_code=? AND holiday_name=? AND holiday_date=?',(country['country_code'],name,holiday_date)).fetchone()
            if found:continue
            holiday_type=item['holiday_type']
            region=None
            cursor=c.execute("""INSERT INTO holidays(country_code,region,holiday_name,holiday_date,observed_date,calendar_year,holiday_type,day_scope,
                government_yn,statutory_yn,paid_holiday_yn,recurring_yn,applicability,source,notes,active_yn,created_by)
                VALUES(?,?,?,?,?,?,'Government Public Holiday','FULL_DAY',1,1,1,0,'ALL',?,?,1,?)""",
                (country['country_code'],region,name,holiday_date,holiday_date,year,source,f"Confirmed synchronization from {source}. {item['description']}".strip(),u['id']))
            c.execute('UPDATE holidays SET holiday_type=? WHERE id=?',(holiday_type,cursor.lastrowid))
            log_audit(c,'holidays',cursor.lastrowid,'CREATE',u['id'],after={'country_code':country['country_code'],'holiday_name':name,'holiday_date':holiday_date,'region':region,'source':source});created+=1;affected.append(holiday_date)
    calendar_updates=0
    for holiday_date in sorted(set(affected)):
        result=generate_calendar_range(holiday_date,holiday_date,u['id'],trigger='OFFICIAL_HOLIDAY_SYNCHRONIZED',reason=source);calendar_updates+=result['created']+result['updated']
    return {'confirmed':True,'country_code':country['country_code'],'year':year,'created':created,'existing':existing,'calendar_updates':calendar_updates,'provider':source,'fallback_used':source.startswith('Nager.Date'),'fallback_reason':fallback_reason if source.startswith('Nager.Date')else None,'message':f'Official holidays confirmed using {source}: {created} added, {existing} already retained.'}
@router.put('/helper-supervisor-roles')
def helper_roles(b:dict,u:dict=Depends(admin)):
    value=','.join(b.get('roles')or[])
    with transaction(immediate=True)as c:c.execute('INSERT INTO settings(key,value)VALUES(\'helper_supervisor_roles\',?)ON CONFLICT(key)DO UPDATE SET value=excluded.value',(value,))
    return {'roles':b.get('roles')or[]}
@router.put('/shift-mode/procurement')
def procurement_shift_mode(b:dict,u:dict=Depends(admin)):
    enabled=int(bool(b.get('shifts_enabled_yn')));start=clock_time(time_minutes(b.get('operating_start_time')or'08:00'));end=clock_time(time_minutes(b.get('operating_end_time')or'17:00'))
    duration=(time_minutes(end)-time_minutes(start))%1440 or 1440
    try:days=sorted(set(int(day)for day in b.get('operating_days',[0,1,2,3,4])));assert days and all(0<=day<=6 for day in days)
    except(TypeError,ValueError,AssertionError):raise HTTPException(400,'Select at least one valid procurement operating day')
    before=procurement_configuration()
    with transaction(immediate=True)as c:
        for key,value in {'procurement_shifts_enabled':str(enabled),'procurement_operating_start_time':start,'procurement_operating_end_time':end,'procurement_operating_days':json.dumps(days)}.items():c.execute('INSERT INTO settings(key,value)VALUES(?,?)ON CONFLICT(key)DO UPDATE SET value=excluded.value',(key,value))
        standard=c.execute("SELECT id FROM shifts WHERE warehouse_id IS NULL AND schedule_mode='STANDARD'").fetchone()
        break_minutes=30 if duration>=360 else(15 if duration>=240 else 0);scheduled_end=end;values=(start,scheduled_end,int(time_minutes(start)+duration>=1440),break_minutes,int(not enabled))
        if standard:c.execute('UPDATE shifts SET start_time=?,end_time=?,cross_midnight_yn=?,break_minutes=?,active_yn=? WHERE id=?',values+(standard['id'],))
        else:c.execute("""INSERT INTO shifts(shift_code,shift_label,start_time,end_time,cross_midnight_yn,break_minutes,department_scope,active_yn,warehouse_id,schedule_mode)
          VALUES('PROC-STANDARD','Procurement Standard Hours',?,?,?,?,'Procurement',?,NULL,'STANDARD')""",values)
        c.execute("UPDATE shifts SET active_yn=? WHERE warehouse_id IS NULL AND schedule_mode='MULTI'",(enabled,))
        log_audit(c,'settings',0,'UPDATE',u['id'],before,{**b,'shifts_enabled_yn':enabled,'operating_start_time':start,'operating_end_time':end,'operating_days':days})
    return {'procurement':procurement_configuration(),'message':'Procurement multi-shift scheduling enabled.'if enabled else'Procurement now uses one standard shift matching its operating hours.'}
@router.put('/shifts/batch')
def update_shift_batch(b:dict,u:dict=Depends(admin)):
    changes=b.get('shifts')or[]
    if not isinstance(changes,list)or not changes:raise HTTPException(400,'Add at least one temporary shift change before confirming')
    try:ids=[int(item['id'])for item in changes];assert len(ids)==len(set(ids))
    except(KeyError,TypeError,ValueError,AssertionError):raise HTTPException(400,'Each shift change must identify one unique shift')
    rows=fetch_all(f"SELECT * FROM shifts WHERE id IN({','.join('?'for _ in ids)})",ids)
    if len(rows)!=len(ids):raise HTTPException(404,'One or more shifts no longer exist')
    warehouse_id=rows[0].get('warehouse_id')
    if any(row.get('warehouse_id')!=warehouse_id or not row['active_yn']for row in rows):raise HTTPException(400,'Confirm changes for active shifts from one warehouse or procurement schedule at a time')
    active=fetch_all('SELECT * FROM shifts WHERE active_yn=1 AND COALESCE(warehouse_id,-1)=COALESCE(?,-1) ORDER BY start_time,id',(warehouse_id,))
    supplied={int(item['id']):item for item in changes};candidate=[];normalized={}
    for row in active:
        item=supplied.get(row['id'],{});start=clock_time(time_minutes(item.get('start_time')or row['start_time']));end=clock_time(time_minutes(item.get('end_time')or row['end_time']));duration=(time_minutes(end)-time_minutes(start))%1440 or 1440
        break_minutes=int(item.get('break_minutes',row.get('break_minutes',30)));working_duration=duration-break_minutes
        maximum=1440 if row.get('schedule_mode')=='STANDARD'else 720
        if working_duration<60 or working_duration>maximum:raise HTTPException(400,f"{row['shift_label']} working time must be between 1 and {maximum//60} hours, excluding its break")
        if break_minutes<0 or break_minutes>120:raise HTTPException(400,'Break time must be between 0 and 120 minutes')
        normalized[row['id']]={**row,**item,'start_time':start,'end_time':end,'break_minutes':break_minutes,'duration':duration,'working_duration':working_duration};candidate.append(normalized[row['id']])
    if warehouse_id is not None:
        window=fetch_one('SELECT operating_start_time,operating_end_time,name FROM warehouses WHERE id=? AND deleted_at IS NULL',(warehouse_id,));valid=bool(window)and warehouse_window_coverage(candidate,window['operating_start_time'],window['operating_end_time']);scope=window['name']if window else'warehouse'
    else:
        config=procurement_configuration();valid=continuous_shift_coverage(candidate)if config['shifts_enabled_yn']else warehouse_window_coverage(candidate,config['operating_start_time'],config['operating_end_time']);scope='procurement'
    if not valid:raise HTTPException(409,f'Temporary changes still create a gap or overlap in the {scope} operating window. Update the adjoining shift start/end times before confirming; no changes were saved.')
    effective_from=b.get('effective_from')or date.today().isoformat();assignments=0
    with transaction(immediate=True)as c:
        for shift_id,item in normalized.items():
            if shift_id not in supplied:continue
            before=next(row for row in rows if row['id']==shift_id);cross=int(time_minutes(item['start_time'])+item['duration']>=1440)
            c.execute("UPDATE shifts SET shift_label=?,start_time=?,end_time=?,cross_midnight_yn=?,break_minutes=?,updated_at=datetime('now'),updated_by=? WHERE id=?",(item.get('shift_label')or before['shift_label'],item['start_time'],item['end_time'],cross,item['break_minutes'],u['id'],shift_id))
            assignments+=c.execute("UPDATE employee_work_calendar SET shift_start=?,shift_end=?,updated_at=datetime('now'),updated_by=? WHERE shift_id=? AND calendar_date>=date('now') AND manual_override_yn=0 AND status<>'LOCKED'",(item['start_time'],item['end_time'],u['id'],shift_id)).rowcount
            c.execute("""INSERT INTO shift_versions(shift_id,shift_label,start_time,end_time,cross_midnight_yn,break_minutes,effective_from,created_by)VALUES(?,?,?,?,?,?,?,?)
              ON CONFLICT(shift_id,effective_from)DO UPDATE SET shift_label=excluded.shift_label,start_time=excluded.start_time,end_time=excluded.end_time,cross_midnight_yn=excluded.cross_midnight_yn,break_minutes=excluded.break_minutes,created_at=datetime('now'),created_by=excluded.created_by""",(shift_id,item.get('shift_label')or before['shift_label'],item['start_time'],item['end_time'],cross,item['break_minutes'],effective_from,u['id']))
            after=dict(c.execute('SELECT * FROM shifts WHERE id=?',(shift_id,)).fetchone());log_audit(c,'shifts',shift_id,'UPDATE',u['id'],before,{**after,'batch_confirmation':True,'continuous_coverage':True})
    return {'success':True,'updated':len(changes),'assignments_updated':assignments,'continuous_coverage':True,'message':f'{len(changes)} shift change(s) applied. The complete {scope} operating window is gapless.'}
@router.put('/shifts/{shift_id}')
def shift(shift_id:int,b:dict,u:dict=Depends(admin)):
    current=fetch_one('SELECT * FROM shifts WHERE id=?',(shift_id,))
    if not current:raise HTTPException(404,'Shift not found')
    start=time_minutes(b.get('start_time')or current['start_time']);requested_end=clock_time(time_minutes(b.get('end_time')or current['end_time']))
    duration=(time_minutes(requested_end)-start)%1440 or 1440
    break_minutes=int(b.get('break_minutes',current.get('break_minutes',30)));working_duration=duration-break_minutes
    maximum=1440 if current.get('schedule_mode')=='STANDARD'else 720
    if working_duration<60 or working_duration>maximum:raise HTTPException(400,f'Shift working time must be between 1 and {maximum//60} hours, excluding its break')
    if break_minutes<0 or break_minutes>120:raise HTTPException(400,'Break time must be between 0 and 120 minutes')
    active=fetch_all('SELECT id,start_time,end_time,break_minutes,warehouse_id FROM shifts WHERE active_yn=1 AND COALESCE(warehouse_id,-1)=COALESCE(?,-1) ORDER BY start_time,id',(current.get('warehouse_id'),))
    candidate=[{**item,'start_time':clock_time(start),'end_time':requested_end,'break_minutes':break_minutes}if item['id']==shift_id else item for item in active]
    if current.get('warehouse_id') is not None:
        window=fetch_one('SELECT operating_start_time,operating_end_time,name FROM warehouses WHERE id=? AND deleted_at IS NULL',(current['warehouse_id'],))
        valid=bool(window)and warehouse_window_coverage(candidate,window['operating_start_time'],window['operating_end_time'])
        error=f"This change would leave a gap or overlap inside {window['name'] if window else 'the warehouse'} operating window. No other shift was changed."
    else:
        procurement=procurement_configuration();valid=continuous_shift_coverage(candidate)if procurement['shifts_enabled_yn']else warehouse_window_coverage(candidate,procurement['operating_start_time'],procurement['operating_end_time']);error='This change would create a procurement operating-hours gap or overlap. No other shift was changed.'
    if current['active_yn']and not valid:raise HTTPException(409,error)
    with transaction(immediate=True)as c:
        c.execute("""UPDATE shifts SET shift_label=?,start_time=?,end_time=?,cross_midnight_yn=?,break_minutes=?,
            updated_at=datetime('now'),updated_by=? WHERE id=?""",(b.get('shift_label')or current['shift_label'],clock_time(start),requested_end,int((start%1440)+duration>=1440),break_minutes,u['id'],shift_id))
        assignments=c.execute("""UPDATE employee_work_calendar SET shift_start=?,shift_end=?,updated_at=datetime('now'),updated_by=?
            WHERE shift_id=? AND calendar_date>=date('now') AND manual_override_yn=0 AND status<>'LOCKED'""",(clock_time(start),requested_end,u['id'],shift_id)).rowcount
        effective_from=b.get('effective_from')or date.today().isoformat()
        c.execute("""INSERT INTO shift_versions(shift_id,shift_label,start_time,end_time,cross_midnight_yn,break_minutes,effective_from,created_by)
            VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(shift_id,effective_from) DO UPDATE SET shift_label=excluded.shift_label,
            start_time=excluded.start_time,end_time=excluded.end_time,cross_midnight_yn=excluded.cross_midnight_yn,
            break_minutes=excluded.break_minutes,created_at=datetime('now'),created_by=excluded.created_by""",
            (shift_id,b.get('shift_label')or current['shift_label'],clock_time(start),requested_end,int((start%1440)+duration>=1440),break_minutes,effective_from,u['id']))
        active=[dict(row)for row in c.execute('SELECT id,start_time,end_time,break_minutes FROM shifts WHERE active_yn=1 AND COALESCE(warehouse_id,-1)=COALESCE(?,-1) ORDER BY start_time,id',(current.get('warehouse_id'),)).fetchall()]
        continuous=warehouse_window_coverage(active,window['operating_start_time'],window['operating_end_time'])if current.get('warehouse_id')is not None else(continuous_shift_coverage(active)if procurement_configuration()['shifts_enabled_yn']else warehouse_window_coverage(active,procurement_configuration()['operating_start_time'],procurement_configuration()['operating_end_time']))
        after=dict(c.execute('SELECT * FROM shifts WHERE id=?',(shift_id,)).fetchone())
        log_audit(c,'shifts',shift_id,'UPDATE',u['id'],current,{**after,'continuous_coverage':continuous,'selected_shift_only':True})
    message=f"{current['shift_code']} updated. No other shift times were changed."
    return {'success':True,'effective_from':effective_from,'start_time':clock_time(start),'end_time':requested_end,'duration_minutes':duration,'working_minutes':working_duration,'break_minutes':break_minutes,'continuous_coverage':continuous,'assignments_updated':assignments,'message':message}
@router.get('/kpis')
def kpis(_u:dict=Depends(admin)):return {'active_employees':(fetch_one("SELECT COUNT(*)n FROM employees WHERE status='Active'AND deleted_at IS NULL")or{})['n'],'coverage_warnings':(fetch_one("SELECT COUNT(*)n FROM calendar_coverage_warnings WHERE warning_status='OPEN'")or{})['n'],'unpublished_entries':(fetch_one("SELECT COUNT(*)n FROM employee_work_calendar WHERE status<>'PUBLISHED'")or{})['n']}
