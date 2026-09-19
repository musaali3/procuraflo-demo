export default function SupplierDetails({ supplier, document: doc = {} }) {
  const source = supplier || doc.supplier || {};
  const field = key => source[key] || doc[key === 'supplier_code' ? key : `supplier_${key}`];
  return <div className="supplier-document-details space-y-1 text-xs">
    <div className="text-sm font-bold">{field('name') || 'Supplier name not recorded'}</div>
    {field('supplier_code') && <div>Supplier Code: {field('supplier_code')}</div>}
    <div className="whitespace-pre-line">{field('address') || 'Address not recorded'}</div>
    {[['contact_person','Contact'],['phone','Phone'],['email','Email'],['country_code','Country']].map(([key,label]) => field(key) ? <div key={key} className="break-words">{label}: {field(key)}</div> : null)}
  </div>;
}
