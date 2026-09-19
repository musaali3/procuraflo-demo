import { useState } from "react";
import client from "../../api/client";

const templates = {
  vendors: "name,contact_person,phone,email,address,payment_terms\nExample Supplier,John Doe,+971501234567,contact@example.com,Warehouse City,Net 30\n",
  items: "description,category,subcategory,uom,purchase_uom,issue_uom,conversion_factor,consumable_returnable,high_value_flag,always_approval_yn,tool_control_yn,batch_control_yn,expiry_control_yn,inspection_required_yn,min_stock,max_stock,reorder_level,standard_cost\nExample Steel Bar,Raw Material,Steel,KG,TON,KG,1000,Consumable,0,0,0,1,0,1,100,1000,250,12.5\n",
  opening: "description,category,subcategory,uom,purchase_uom,issue_uom,conversion_factor,consumable_returnable,high_value_flag,always_approval_yn,tool_control_yn,batch_control_yn,expiry_control_yn,inspection_required_yn,min_stock,max_stock,reorder_level,standard_cost,warehouse,location,quantity,unit_cost,received_date,batch,expiry_date\nExample Steel Bar,Raw Material,Steel,KG,TON,KG,1000,Consumable,0,0,0,1,0,1,100,1000,250,12.5,WH-001,WH-001-BN-0003,100,5.2,2026-01-01,BATCH-001,\n",
};

export default function ImportDataPage() {
  const [files, setFiles] = useState({});
  const [importing, setImporting] = useState(false);
  const [message, setMessage] = useState("");

  async function upload(type) {
    if (!files[type]) return;
    const body = new FormData();
    body.append("file", files[type]);
    setImporting(true);
    setMessage("");
    try {
      const endpoint = type === "vendors" ? "vendors" : type === "items" ? "items" : "opening-balances";
      const response = await client.post(`/settings/imports/${endpoint}`, body, { headers: { "Content-Type": "multipart/form-data" } });
      const count = response.data.imported ?? response.data.created ?? 0;
      setMessage(type === "opening" ? `Imported ${count} opening balance row(s). ${response.data.new_items_created || 0} new Item Master record(s) created automatically.` : `Imported ${count} ${type === "vendors" ? "supplier" : "item"} record(s).`);
    } catch (error) {
      setMessage(error?.response?.data?.error || "Import failed. Correct the mandatory data and try again.");
    } finally {
      setImporting(false);
    }
  }

  async function downloadTemplate(type, format) {
    const filenameType = type === "opening" ? "opening-balances" : type;
    if (format === "xlsx") {
      try {
        const response = await client.get(`/settings/imports/${filenameType}/template`, { responseType: "blob" });
        const url = URL.createObjectURL(response.data);
        const link = document.createElement("a");
        link.href = url;
        link.download = `${filenameType}-template.xlsx`;
        link.click();
        URL.revokeObjectURL(url);
      } catch (error) {
        let detail = "";
        try {
          const payload = error?.response?.data instanceof Blob
            ? JSON.parse(await error.response.data.text())
            : error?.response?.data;
          detail = payload?.error || payload?.detail || "";
        } catch { /* The response was not JSON. */ }
        setMessage(error?.response?.status === 404
          ? "Excel template service is not active yet. Restart the Python/Uvicorn backend, then try again."
          : detail || "Excel template download failed. Check your connection and try again.");
      }
      return;
    }
    const url = URL.createObjectURL(new Blob([templates[type]], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `Procuraflo-${filenameType}-template.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  const cards = [
    ["vendors", "Import Suppliers", "Supplier codes and performance ratings are generated automatically; do not include them in the file."],
    ["items", "Import New Items", "Every Item Master field in the template is mandatory. Category and subcategory values are added to the classification master."],
    ["opening", "Import Opening Balances", "Creates missing Item Master records automatically, then posts stock, FIFO layers and permanent ledger entries in one transaction."],
  ];
  return <div>
    <h1 className="text-xl font-semibold text-slate-900">Import Data</h1>
    <p className="mt-1 text-sm text-slate-500">Generated codes must not be entered manually. Download the current controlled template before every import.</p>
    <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">Mandatory item fields must be completed in every row. Opening balances additionally require warehouse, active Bin, quantity, unit cost and received date. One invalid row rejects the complete file without partial posting.</div>
    <div className="mt-4 grid gap-5 lg:grid-cols-3">
      {cards.map(([type, title, description]) => <section className="card p-5" key={type}>
        <h2 className="font-semibold text-blue-950">{title}</h2>
        <p className="mt-1 min-h-16 text-sm text-slate-500">{description}</p>
        <input data-field="file" aria-label={title + " file"} className="input mt-3" type="file" accept=".csv,.xlsx" onChange={event => setFiles(current => ({ ...current, [type]: event.target.files?.[0] }))} />
        <div className="mt-3 flex flex-wrap gap-2"><button className="btn-secondary text-xs" onClick={() => downloadTemplate(type, "csv")}>CSV Template</button><button className="btn-secondary text-xs" onClick={() => downloadTemplate(type, "xlsx")}>Excel Template</button><button className="btn-primary" disabled={!files[type] || importing} onClick={() => upload(type)}>{importing ? "Importing…" : "Import"}</button></div>
      </section>)}
    </div>
    {message && <div className={`card mt-4 p-4 text-sm ${/failed|missing|invalid|cannot|already/i.test(message) ? "text-rose-700" : "text-emerald-700"}`}>{message}</div>}
  </div>;
}
