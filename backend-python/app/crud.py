from fastapi import APIRouter, Depends, HTTPException

from .audit import log_audit
from .database import fetch_all, fetch_one, transaction
from .security import User, roles

def crud_router(prefix, table, allowed_fields, *, soft_delete=False, order_by='id DESC', write_roles=None,
                auto_code=None, duplicate_fields=(), immutable_fields=()):
    router = APIRouter(prefix=prefix)
    write_dependency = roles(*(write_roles or [])) if write_roles else None

    @router.get('')
    def list_rows(_user: User):
        where = ' WHERE deleted_at IS NULL' if soft_delete else ''
        if table=='items':
            return fetch_all('SELECT i.*,COALESCE((SELECT SUM(quantity) FROM inventory_stock WHERE item_id=i.id),0) available_stock,COALESCE((SELECT SUM(quantity_remaining*unit_cost)/NULLIF(SUM(quantity_remaining),0) FROM inventory_layers WHERE item_id=i.id AND quantity_remaining>0),0) stock_unit_cost FROM items i'+where+f' ORDER BY {order_by}')
        return fetch_all(f'SELECT * FROM {table}{where} ORDER BY {order_by}')

    @router.get('/{row_id}')
    def get_row(row_id: int, _user: User):
        row = fetch_one(f'SELECT * FROM {table} WHERE id=?', (row_id,))
        if not row: raise HTTPException(404, 'Not found')
        return row

    def guard(user):
        if write_roles and user['role'] not in write_roles:
            raise HTTPException(403, f"Role '{user['role']}' is not permitted to perform this action")

    def validate_item(values):
        required=['description','category','subcategory','uom','purchase_uom','issue_uom','consumable_returnable']
        missing=[field for field in required if not str(values.get(field)or'').strip()]
        if missing:raise HTTPException(400,f"Required item fields: {', '.join(field.replace('_',' ') for field in missing)}")
        try:
            conversion=float(values.get('conversion_factor')or 0)
            minimum=float(values.get('min_stock')or 0)
            maximum=float(values.get('max_stock')or 0)
            reorder=float(values.get('reorder_level')or 0)
            standard_cost=float(values.get('standard_cost')or 0)
        except (TypeError,ValueError):
            raise HTTPException(400,'Item conversion, stock levels, and standard cost must be numeric')
        if conversion<=0:raise HTTPException(400,'Conversion factor must be greater than zero')
        if min(minimum,maximum,reorder,standard_cost)<0:raise HTTPException(400,'Stock levels and standard cost cannot be negative')
        if maximum and minimum>maximum:raise HTTPException(400,'Minimum stock cannot exceed maximum stock')
        category=fetch_one('SELECT id FROM item_categories WHERE name=? COLLATE NOCASE AND active_yn=1',(str(values['category']).strip(),))
        if not category or not fetch_one('SELECT id FROM item_subcategories WHERE category_id=? AND name=? COLLATE NOCASE AND active_yn=1',(category['id'],str(values['subcategory']).strip())):
            raise HTTPException(400,'Select a valid active item category and subcategory')

    @router.post('', status_code=201)
    def create(body: dict, user: User):
        guard(user)
        body = dict(body or {})
        if auto_code and str(body.get(auto_code[0]) or '').strip():
            raise HTTPException(400, f"{auto_code[0].replace('_',' ').title()} is generated automatically and cannot be entered manually")
        if auto_code:body.pop(auto_code[0],None)
        if table=='items':
            validate_item(body)
        unknown = [key for key in body if key not in allowed_fields]
        if unknown: raise HTTPException(400, f"Unknown fields: {', '.join(unknown)}")
        keys = [key for key in body if key in allowed_fields]
        if not keys: raise HTTPException(400, 'No fields provided')
        for field in duplicate_fields:
            suffix = ' AND deleted_at IS NULL' if soft_delete else ''
            if body.get(field) is not None and fetch_one(f'SELECT id FROM {table} WHERE lower({field})=lower(?){suffix}', (str(body[field]).strip(),)):
                raise HTTPException(409, f"Duplicate {field.replace('_',' ')} already exists")
        with transaction(immediate=True) as connection:
            if auto_code:
                rows=connection.execute(f"SELECT {auto_code[0]} code FROM {table} WHERE {auto_code[0]} LIKE ?",(auto_code[1]+'-%',)).fetchall()
                numbers=[int(str(row['code']).rsplit('-',1)[-1])for row in rows if str(row['code']).rsplit('-',1)[-1].isdigit()]
                body[auto_code[0]]=f"{auto_code[1]}-{(max(numbers)if numbers else 0)+1:04d}"
                keys.append(auto_code[0])
            cursor = connection.execute(f"INSERT INTO {table}({','.join(keys)}) VALUES({','.join('?' for _ in keys)})", tuple(body[key] for key in keys))
            log_audit(connection, table, cursor.lastrowid, 'CREATE', user['id'], after=body)
            row_id = cursor.lastrowid
        return fetch_one(f'SELECT * FROM {table} WHERE id=?', (row_id,))

    @router.put('/{row_id}')
    def update(row_id: int, body: dict, user: User):
        guard(user)
        before = fetch_one(f'SELECT * FROM {table} WHERE id=?', (row_id,))
        if not before: raise HTTPException(404, 'Not found')
        unknown = [key for key in body if key not in allowed_fields]
        if unknown: raise HTTPException(400, f"Unknown fields: {', '.join(unknown)}")
        keys = [key for key in body if key in allowed_fields and key not in immutable_fields]
        if not keys: raise HTTPException(400, 'No fields provided')
        if table=='items':
            merged=dict(before)
            merged.update({key:body[key] for key in keys})
            validate_item(merged)
        for field in duplicate_fields:
            suffix = ' AND deleted_at IS NULL' if soft_delete else ''
            if field in body and fetch_one(f'SELECT id FROM {table} WHERE lower({field})=lower(?) AND id<>?{suffix}',(str(body[field]).strip(),row_id)):
                raise HTTPException(409,f"Duplicate {field.replace('_',' ')} already exists")
        with transaction(immediate=True) as connection:
            connection.execute(f"UPDATE {table} SET {','.join(key+'=?' for key in keys)} WHERE id=?", tuple(body[key] for key in keys) + (row_id,))
            log_audit(connection, table, row_id, 'UPDATE', user['id'], before, body)
        return fetch_one(f'SELECT * FROM {table} WHERE id=?', (row_id,))

    @router.delete('/{row_id}')
    def delete(row_id: int, user: User):
        guard(user)
        before = fetch_one(f'SELECT * FROM {table} WHERE id=?', (row_id,))
        if not before: raise HTTPException(404, 'Not found')
        with transaction(immediate=True) as connection:
            connection.execute(f"UPDATE {table} SET deleted_at=datetime('now') WHERE id=?" if soft_delete else f'DELETE FROM {table} WHERE id=?', (row_id,))
            log_audit(connection, table, row_id, 'DELETE', user['id'], before=before)
        return {'success': True, 'softDeleted': soft_delete}
    return router
