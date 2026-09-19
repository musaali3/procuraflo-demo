import { Link } from "react-router-dom";

const sections = [
  ["Procurement: Requisition to Finance Evidence", "from-blue-700 to-blue-600", [
    ["Demand and sourcing", "Create and submit the PR, generate the RFQ, record complete quotations, and compare landed cost, lead time, quality and the automatically calculated supplier rating."],
    ["Purchase commitment", "Create the PO from approved demand, follow approval limits and segregation rules, then print the approved document. Approved quantities remain receivable until fully accepted."],
    ["Invoice verification", "Match supplier invoice, approved PO and cumulative accepted GRNs. The Supply Chain Manager controls the external Ready for Finance handoff; Finance has no Procuraflo access."],
  ]],
  ["Warehouse: Receipt to Stock Accountability", "from-emerald-700 to-cyan-600", [
    ["Receive approved material", "Create the GRN from an approved or printed PO, record received/accepted/rejected quantities and the destination Bin. Accepted stock updates balance, FIFO and ledger atomically."],
    ["Issue, return and move", "Use assigned warehouse scope for material issues, returns, transfers and BIN transfers. Posted movements remain immutable and corrections use controlled workflows."],
    ["Warehouse timetable", "Save each warehouse operating start/end time as an 8, 16 or 24-hour window. Consecutive eight-hour shifts and employee calendars follow that warehouse timetable without gaps or overlaps."],
  ]],
  ["Master Data & Controlled Imports", "from-cyan-700 to-blue-600", [
    ["Item Master", "Item codes are generated on save. Complete classification, UOM conversion, stock thresholds, cost and control flags. Add a missing category or subcategory in the form; it is saved immediately to the database."],
    ["Item and opening-balance imports", "Download the current template, complete every mandatory field and omit generated codes. Opening balances create missing items and post stock, FIFO and permanent ledger rows in one transaction; one invalid row rejects the complete file."],
    ["Supplier Master", "Supplier codes are generated on save. Ratings cannot be entered manually; Procuraflo recalculates performance from accepted quality, quantity fulfillment and on-time delivery when GRNs are posted."],
    ["Warehouse locations", "Create the warehouse, then its Zone, Aisle, Rack, Shelf and Bin hierarchy. Physical IDs are generated automatically and parent locations must belong to the same warehouse."],
  ]],
];

export default function QuickStartPage() {
  return <div className="space-y-5">
    <header className="rounded-xl border border-slate-200 bg-white px-5 py-4 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-[.22em] text-cyan-700">Procuraflo Operations</div>
      <h1 className="mt-1 text-2xl font-bold text-slate-900">Procurement & Warehouse Quick Start</h1>
      <p className="mt-1 max-w-4xl text-sm leading-6 text-slate-600">Current operating guidance for controlled purchasing, receiving, master data, warehouse scheduling and auditable inventory.</p>
      <div className="mt-4 flex flex-wrap gap-2"><Link className="btn-primary" to="/help">Open Full Help Center</Link><Link className="btn-secondary" to="/reports">Open Reports</Link></div>
    </header>
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{[["Start every day","Open the role-based dashboard and task list."],["Use source records","Review the original PR, PO, GRN or approval before acting."],["Protect history","Never alter posted documents, FIFO or ledger records."],["Use assigned scope","Warehouse processing remains restricted to authorized sites and locations."]].map(([title,text])=><div className="card p-4" key={title}><strong>{title}</strong><p className="mt-1 text-sm text-slate-600">{text}</p></div>)}</div>
    {sections.map(([title,tone,cards])=><section className="card overflow-hidden" key={title}><div className={`bg-gradient-to-r ${tone} p-5 text-white`}><h2 className="text-lg font-semibold">{title}</h2></div><div className="grid gap-4 p-5 lg:grid-cols-2">{cards.map(([heading,text],index)=><article className="rounded-xl border border-slate-200 bg-slate-50 p-4" key={heading}><h3 className="font-semibold text-slate-900">{index+1}. {heading}</h3><p className="mt-2 text-sm leading-6 text-slate-600">{text}</p></article>)}</div></section>)}
  </div>;
}
