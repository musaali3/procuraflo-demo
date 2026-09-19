"""Supplier identity for tenant-scoped document reads, including historical suppliers."""
from .database import fetch_one


def supplier_document_fields(supplier_id):
    supplier = fetch_one('SELECT * FROM suppliers WHERE id=?', (supplier_id,)) or {}
    fields = {f'supplier_{key}': supplier.get(key) for key in
              ('name', 'address', 'contact_person', 'phone', 'email', 'country_code')}
    fields['supplier_code'] = supplier.get('supplier_code')
    fields['supplier'] = {key: supplier.get(key) for key in
                          ('id', 'supplier_code', 'name', 'address', 'contact_person', 'phone', 'email', 'country_code')}
    return fields
