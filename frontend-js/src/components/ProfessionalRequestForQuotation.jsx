import SupplierDetails from './SupplierDetails';
import { DocumentCompanyHeader, GeneratedByFooter } from './Branding';

export default function ProfessionalRequestForQuotation({rfq,supplier,company}) {
  return <article id="rfq-print-document" className="controlled-print-document rounded-lg border border-slate-200 bg-white p-7 text-slate-900">
    <DocumentCompanyHeader company={company} title="REQUEST FOR QUOTATION" reference={rfq.rfq_number} date={rfq.issue_date}/>
    <section className="my-5 grid grid-cols-2 gap-5 text-xs">
      <div className="rounded-md border border-slate-300 p-3"><h2 className="mb-2 font-bold">INVITED SUPPLIER</h2><SupplierDetails supplier={supplier}/></div>
      <div className="rounded-md border border-slate-300 p-3"><h2 className="mb-2 font-bold">RFQ DETAILS</h2><div>Source PR: {rfq.pr_number}</div><div>Status: {rfq.workflow_status}</div><div>Quotation closing: {rfq.closing_date || 'Not specified'}</div><div>Required delivery: {rfq.required_delivery_date || 'Not specified'}</div><div>Delivery warehouse: {rfq.delivery_warehouse_name || 'Not specified'}</div><div>Currency: {rfq.currency || company?.currency}</div></div>
    </section>
    <table className="w-full border-collapse text-xs"><thead><tr><th>Item Code</th><th>Description / Specification</th><th>RFQ Quantity</th><th>UOM</th><th>Required Date</th></tr></thead><tbody>{rfq.items.map(line=><tr key={line.pr_item_id || line.id}><td>{line.item_code}</td><td>{line.description}<div>{line.reason}</div></td><td>{line.quantity}</td><td>{line.transaction_uom || line.purchase_uom || line.uom}</td><td>{line.required_date || rfq.required_delivery_date}</td></tr>)}</tbody></table>
    <section className="my-5 grid grid-cols-2 gap-4 text-xs">{[['Payment Terms',rfq.payment_terms],['Incoterms',rfq.incoterms],['Commercial Terms',rfq.commercial_terms],['Technical Requirements',rfq.technical_requirements],['Contact Person',rfq.contact_person],['Notes',rfq.notes]].map(([label,value])=><div key={label} className="print-avoid-break"><strong>{label}</strong><p className="whitespace-pre-line">{value || 'Not specified'}</p></div>)}</section>
    <GeneratedByFooter note={`Private RFQ issued to ${supplier.name}. This is a request for quotation and does not authorize a purchase commitment.`}/>
  </article>;
}
