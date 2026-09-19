export default function RfqItemSelection({ lines, onChange, loading }) {
  const update=(id,key,value)=>onChange(lines.map(line=>line.pr_item_id===id?{...line,[key]:value}:line));
  return <section className="form-section">
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><div><h3 className="form-section-title">Review PR Items & RFQ Quantities</h3><p className="text-xs text-slate-500">Select the items to source. RFQ quantity uses the purchasing UOM and cannot exceed the remaining approved balance.</p></div>
      {!!lines.length&&<div className="flex gap-2"><button type="button" className="btn-secondary" onClick={()=>onChange(lines.map(line=>({...line,selected:true})))}>Select All</button><button type="button" className="btn-secondary" onClick={()=>onChange(lines.map(line=>({...line,selected:false})))}>Clear Selection</button></div>}</div>
    {loading?<p role="status">Loading approved PR items…</p>:!lines.length?<p className="text-sm text-slate-500">Select an approved PR to review its available items.</p>:<div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th>Include</th><th>Item / Specification</th><th>PR Requested</th><th>PR Approved</th><th>Remaining for RFQ</th><th>RFQ Quantity</th><th>Required Date</th></tr></thead><tbody>{lines.map(line=><tr key={line.pr_item_id}>
      <td><input aria-label={`Include ${line.item_code}`} type="checkbox" checked={line.selected} onChange={e=>update(line.pr_item_id,'selected',e.target.checked)}/></td>
      <td><strong>{line.item_code}</strong><div>{line.description}</div><small>{line.reason}</small></td>
      <td>{line.requested_quantity} {line.pr_uom}</td><td>{line.approved_quantity} {line.pr_uom}</td>
      <td>{Number(line.available_quantity).toLocaleString()} {line.transaction_uom}</td>
      <td><input data-field={"quantity"} aria-label={`RFQ quantity for ${line.item_code}`} className="input min-w-24" type="number" min="0.000001" max={line.available_quantity} step="any" disabled={!line.selected} value={line.quantity} onChange={e=>update(line.pr_item_id,'quantity',e.target.value)}/><small>{line.transaction_uom}</small></td>
      <td>{line.required_date || '—'}</td>
    </tr>)}</tbody></table></div>}
  </section>;
}
