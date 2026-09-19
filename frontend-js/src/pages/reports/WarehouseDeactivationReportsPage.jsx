import {useEffect,useState} from "react";
import client from "../../api/client";
import DataTable from "../../components/DataTable";
import Modal from "../../components/Modal";

export default function WarehouseDeactivationReportsPage(){
  const [rows,setRows]=useState([]),[detail,setDetail]=useState(null),[error,setError]=useState("");
  useEffect(()=>{client.get("/masters/warehouses/deactivation-reports").then(r=>setRows(r.data)).catch(e=>setError(e.response?.data?.error||"Unable to load deactivation reports"))},[]);
  async function open(id){try{setDetail((await client.get(`/masters/warehouses/deactivation-reports/${id}`)).data)}catch(e){setError(e.response?.data?.error||"Unable to load report")}}
  return <div><div className="mb-4"><h1 className="text-xl font-semibold">Warehouse Deactivation Reports</h1><p className="text-sm text-slate-500">Permanent audit snapshots created by the controlled warehouse-deactivation workflow.</p></div>{error&&<p data-error-message="true" role="alert" className="mb-3 text-sm text-rose-600">{error}</p>}<div className="card"><DataTable actionLabel="View Report" rows={rows} columns={[{key:"report_number",label:"Report"},{key:"warehouse_code",label:"Code"},{key:"warehouse_name",label:"Warehouse"},{key:"deactivated_at",label:"Deactivated"},{key:"deactivated_by_name",label:"Deactivated By"},{key:"stock_quantity",label:"Final Stock"},{key:"fifo_quantity",label:"Final FIFO"}]} actions={row=><button className="btn-secondary text-xs" onClick={()=>open(row.id)}>Open Report</button>}/></div>{detail&&<Modal wide title={`Warehouse Deactivation Report ${detail.report_number}`} onClose={()=>setDetail(null)}><div className="space-y-3"><div className="rounded-lg bg-slate-50 p-3 text-sm"><strong>{detail.warehouse_code} — {detail.warehouse_name}</strong><br/>{detail.deactivation_reason}</div>{Object.entries(detail.snapshot?.reports||{}).map(([name,data])=><section key={name}><h3 className="font-medium capitalize">{name.replaceAll("_"," ")} ({data.length})</h3></section>)}</div></Modal>}</div>
}
