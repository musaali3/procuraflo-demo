import { useEffect, useState } from 'react';
import client from '../../api/client';
import DataTable from '../../components/DataTable';
import useAutoRefresh from '../../hooks/useAutoRefresh';

export default function VendorScorecardPage() {
  const [scores, setScores] = useState([]);
  const [loading, setLoading] = useState(true);
  const load = () => { setLoading(true); client.get('/advanced/vendor-scorecards').then(result => setScores(result.data)).finally(() => setLoading(false)); };
  useAutoRefresh(load);
  useEffect(load, []);
  return <div>
    <div className="mb-4 flex items-end justify-between"><div><h1 className="text-xl font-semibold text-slate-900">Vendor Performance Scorecard</h1><p className="text-sm text-slate-500">Automatically calculated from receipt timeliness, accepted quantity, rejection, and quality outcomes.</p></div><button className="btn-secondary" onClick={load}>Refresh Scores</button></div>
    <div className="card"><DataTable loading={loading} rows={scores} columns={[
      { key: 'supplier_name', label: 'Supplier' }, { key: 'purchase_orders', label: 'POs' }, { key: 'receipts', label: 'Receipts' },
      { key: 'delivery_accuracy', label: 'On-Time / 5' }, { key: 'quality', label: 'Quality / 5' },
      { key: 'rejected_quantity', label: 'Rejected Qty' },
      { key: 'overall_score', label: 'Overall / 5', render: row => <strong className={Number(row.overall_score) >= 4 ? 'text-emerald-700' : Number(row.overall_score) >= 3 ? 'text-amber-700' : 'text-rose-700'}>{Number(row.overall_score || 0).toFixed(2)}</strong> },
    ]} /></div>
  </div>;
}
