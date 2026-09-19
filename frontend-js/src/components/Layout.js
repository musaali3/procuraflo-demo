import HorizontalScroll from './HorizontalScroll';
import PrintBrandFooter from './PrintBrandFooter';
import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import client from "../api/client";
import Sidebar from "./Sidebar";
import Topbar from "./Topbar";
import TableSortingEnhancer from "./TableSortingEnhancer";
import ButtonThemeEnhancer from "./ButtonThemeEnhancer";
import { useAuth } from "../contexts/AuthContext";
export default function Layout({ children }) {
  const location = useLocation();
  const {user,logout}=useAuth();
  const [backup,setBackup]=useState(null);
  const [backupSeconds,setBackupSeconds]=useState(0);
  const [delegations,setDelegations]=useState([]);
  useEffect(() => {
    const heartbeat = () =>
      client
        .post("/dashboard/activity/heartbeat", { page_path: location.pathname })
        .catch(() => undefined);
    heartbeat();
    const timer = window.setInterval(heartbeat, 15000);
    return () => window.clearInterval(timer);
  }, [location.pathname]);
  useEffect(()=>{const refresh=()=>client.get('/settings/maintenance/status',{params:{warehouse_id:user?.warehouse_id||undefined}}).then(({data})=>{setBackup(data);setBackupSeconds(data.seconds_remaining||0);if(data.active_yn)logout();}).catch(()=>undefined);refresh();const timer=window.setInterval(refresh,30000);return()=>window.clearInterval(timer);},[user?.warehouse_id]);
  useEffect(()=>{const timer=window.setInterval(()=>setBackupSeconds(value=>Math.max(0,value-1)),1000);return()=>window.clearInterval(timer);},[]);
  useEffect(()=>{if(user?.role==='SupplyChainManager'){setDelegations([]);return;}const refresh=()=>client.get('/delegations/mine').then(({data})=>setDelegations(data.filter(row=>row.effective_status==='Active'))).catch(()=>setDelegations([]));refresh();const timer=window.setInterval(refresh,60000);return()=>window.clearInterval(timer);},[user?.role]);
  const countdown=backup?.warning_active?`${String(Math.floor(backupSeconds/60)).padStart(2,'0')}:${String(backupSeconds%60).padStart(2,'0')}`:null;
  return _jsxs("div", {
    className: "app-workspace flex min-h-screen bg-transparent",
    children: [
      _jsx(PrintBrandFooter, {}),
      _jsx(TableSortingEnhancer, {}),
      _jsx(ButtonThemeEnhancer, {}),
      _jsx(Sidebar, {}),
      _jsxs("div", {
        className: "relative z-[1] flex-1 min-w-0",
        children: [
          _jsx(Topbar, {}),
          delegations.length>0&&_jsxs("div",{className:"border-b border-blue-200 bg-blue-50 px-5 py-2 text-sm text-blue-950",children:[_jsx("strong",{children:"Temporary Delegated Authority Active: "}),delegations.map((row,index)=>_jsxs("span",{children:[index?" · ":"",row.authority_label," — ",row.scope_type.replaceAll('_',' ')," — valid until ",new Date(row.effective_until).toLocaleString()]},row.id))]}),
          countdown&&_jsxs("div",{className:"sticky top-0 z-40 border-b border-amber-300 bg-amber-100 px-4 py-2 text-center text-sm font-semibold text-amber-950",children:["SYSTEM BACKUP NOTICE · Month-End Backup in ",countdown," · Save and complete current work. Scheduled local time: ",new Date(backup.scheduled_at).toLocaleString()," (",backup.display_time_zone,"). All sessions will be signed out at backup time."]}),
          _jsx("main", {
            className: "app-main p-6 max-w-7xl mx-auto",
            children: _jsx(HorizontalScroll,{children}),
          }),
        ],
      }),
    ],
  });
}
