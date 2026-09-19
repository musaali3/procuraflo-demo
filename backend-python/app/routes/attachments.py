import os,secrets
from pathlib import Path
from fastapi import APIRouter,File,HTTPException,UploadFile
from fastapi.responses import FileResponse
from ..audit import log_audit
from ..database import fetch_all,fetch_one,transaction
from ..security import User
from ..storage import upload_path

router=APIRouter(prefix='/api/attachments',tags=['attachments']);DOCS=upload_path('documents')
PROC=['SupplyChainManager','PurchaseManager','PurchaseOfficer'];WAREHOUSE=['SupplyChainManager','WarehouseManager','WarehouseSupervisor','Storekeeper'];ACCESS={'PR':PROC+['WarehouseManager','WarehouseSupervisor','Storekeeper'],'PO':PROC+['WarehouseManager','WarehouseSupervisor','Storekeeper'],'GRN':WAREHOUSE,'INVOICE':PROC,'ADJUSTMENT':WAREHOUSE,'MANUAL_APPROVAL':PROC,'RFQ':PROC,'QUOTATION':PROC,'AWARD':['SupplyChainManager','PurchaseManager']};UPLOAD={**ACCESS,'PO':PROC,'GRN':WAREHOUSE,'MANUAL_APPROVAL':['SupplyChainManager'],'RFQ':PROC,'QUOTATION':PROC,'AWARD':['SupplyChainManager','PurchaseManager']}
def exists(kind,row_id):return fetch_one(f"SELECT id FROM {'purchase_requisitions' if kind=='PR' else 'purchase_orders' if kind in ['PO','MANUAL_APPROVAL'] else 'grns' if kind=='GRN' else 'invoices' if kind=='INVOICE' else 'stock_adjustments' if kind=='ADJUSTMENT' else 'rfqs' if kind=='RFQ' else 'rfq_awards' if kind=='AWARD' else 'supplier_quotations'} WHERE id=?",(row_id,))
def check(kind,row_id,user,write=False):
    if kind not in ACCESS:raise HTTPException(400,'Invalid document type')
    if kind!='PR' and user['role'] not in (UPLOAD if write else ACCESS)[kind]:raise HTTPException(403,'Your role cannot upload this document type' if write else 'Your role cannot access this document type')
    if not exists(kind,row_id):raise HTTPException(404,'Document not found')
    if kind=='PR':
        from ..pr_workflow import require_pr_access
        row=require_pr_access(fetch_one('SELECT * FROM purchase_requisitions WHERE id=?',(row_id,)),user)
        if write and row.get('status')=='Draft':
            from ..pr_workflow import require_pr_draft_management
            require_pr_draft_management(row,user)
        if write and user['role'] not in UPLOAD['PR'] and row.get('requestor_id')!=user['id']:raise HTTPException(403,'You may only upload supporting documents to your own PR')
    if user['role'] in ['WarehouseManager','WarehouseSupervisor','Storekeeper']:
        if kind=='GRN' and not fetch_one(f"SELECT 1 ok FROM grn_items WHERE grn_id=? AND warehouse_id IN({','.join('?' for _ in user['warehouse_ids']) or 'NULL'}) LIMIT 1",(row_id,*user['warehouse_ids'])):raise HTTPException(404,'Document not found')
        if kind=='PO':
            from .procurement import require_po_access
            require_po_access(user,row_id)
        if kind=='ADJUSTMENT' and not fetch_one(f"SELECT 1 ok FROM stock_adjustments WHERE id=? AND warehouse_id IN({','.join('?' for _ in user['warehouse_ids']) or 'NULL'})",(row_id,*user['warehouse_ids'])):raise HTTPException(404,'Document not found')
        if kind not in ['PR','PO','GRN','ADJUSTMENT']:raise HTTPException(404,'Document not found')
def signature(data,mime):return (mime=='application/pdf' and data[:5]==b'%PDF-')or(mime=='image/png' and data[:8]==b'\x89PNG\r\n\x1a\n')or(mime=='image/jpeg' and data[:3]==b'\xff\xd8\xff')or(mime in['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','application/zip']and data[:2]==b'PK')
@router.get('/file/{attachment_id}')
def get_file(attachment_id:int,user:User):
    row=fetch_one('SELECT * FROM document_attachments WHERE id=?',(attachment_id,))
    if not row:raise HTTPException(404,'Attachment not found')
    check(row['document_type'],row['document_id'],user);target=(DOCS/Path(row['stored_name']).name).resolve()
    if target.parent!=DOCS.resolve() or not target.exists():raise HTTPException(404,'Attachment file is missing')
    return FileResponse(target,media_type=row['mime_type'],filename=row['original_name'],content_disposition_type='inline')
@router.get('/{kind}/{row_id}')
def list_files(kind:str,row_id:int,user:User):
    kind=kind.upper();check(kind,row_id,user);return fetch_all('SELECT da.*,u.full_name uploaded_by_name FROM document_attachments da LEFT JOIN users u ON u.id=da.uploaded_by WHERE document_type=? AND document_id=? ORDER BY uploaded_at DESC',(kind,row_id))
@router.post('/{kind}/{row_id}',status_code=201)
async def upload(kind:str,row_id:int,user:User,file:UploadFile=File(...)):
    kind=kind.upper();check(kind,row_id,user,True);data=await file.read(15*1024*1024+1)
    if len(data)>15*1024*1024 or file.content_type not in ['application/pdf','image/jpeg','image/png','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','application/zip'] or not signature(data,file.content_type):raise HTTPException(400,'A valid PDF, JPG, PNG, or XLSX file is required (maximum 15 MB)')
    name=secrets.token_hex(16);target=DOCS/name;target.write_bytes(data)
    try:
        with transaction(immediate=True) as c:
            cur=c.execute('INSERT INTO document_attachments(document_type,document_id,original_name,stored_name,mime_type,file_size,uploaded_by)VALUES(?,?,?,?,?,?,?)',(kind,row_id,file.filename,name,file.content_type,len(data),user['id']));log_audit(c,'document_attachments',cur.lastrowid,'CREATE',user['id'],after={'type':kind,'document_id':row_id,'original_name':file.filename});attachment_id=cur.lastrowid
    except Exception:target.unlink(missing_ok=True);raise
    return {'id':attachment_id,'original_name':file.filename,'url':f'/uploads/documents/{name}'}
