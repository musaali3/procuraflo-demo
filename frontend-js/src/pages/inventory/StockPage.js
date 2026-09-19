import { jsx, jsxs } from "react/jsx-runtime";
import { useEffect, useRef, useState } from "react";
import client from "../../api/client";
import DataTable from "../../components/DataTable";
import useAutoRefresh from "../../hooks/useAutoRefresh";
function StockPage() {
  const [warehouses, setWarehouses] = useState([]);
  const [warehouseId, setWarehouseId] = useState("");
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const requestId = useRef(0);
  useEffect(() => {
    let active = true;
    client.get("/masters/warehouses").then(({ data }) => {
      if (!active) return;
      setWarehouses(data);
      setWarehouseId(data.length ? String(data[0].id) : "");
      if (!data.length) setLoading(false);
    }).catch((failure) => {
      if (!active) return;
      setError(failure?.response?.data?.error || "Unable to load warehouses");
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, []);
  function load() {
    if (!warehouseId) return;
    const currentRequest = ++requestId.current;
    setLoading(true);
    setError("");
    client.get("/inventory/stock", { params: { warehouse_id: Number(warehouseId) } }).then(({ data }) => {
      if (currentRequest === requestId.current) setRows(data);
    }).catch((failure) => {
      if (currentRequest === requestId.current) {
        setRows([]);
        setError(failure?.response?.data?.error || "Unable to load inventory");
      }
    }).finally(() => {
      if (currentRequest === requestId.current) setLoading(false);
    });
  }
  useAutoRefresh(load);
  useEffect(() => {
    setRows([]);
    load();
  }, [warehouseId]);
  return /* @__PURE__ */ jsxs("div", { children: [
    /* @__PURE__ */ jsxs("div", { className: "mb-4 flex flex-wrap items-end justify-between gap-3", children: [
      /* @__PURE__ */ jsxs("div", { children: [
        /* @__PURE__ */ jsx("h1", { className: "mb-1 text-xl font-semibold text-slate-900", children: "Real-Time Inventory" }),
        /* @__PURE__ */ jsx("p", { className: "text-sm text-slate-500", children: "Live on-hand quantity for the selected warehouse, by item and location." })
      ] }),
      /* @__PURE__ */ jsxs("label", { className: "min-w-56 text-sm font-medium text-slate-700", children: [
        "Warehouse",
        /* @__PURE__ */ jsxs("select", { className: "input mt-1", value: warehouseId, onChange: (event) => {
          requestId.current += 1;
          setRows([]);
          setWarehouseId(event.target.value);
        }, children: [
          !warehouseId && /* @__PURE__ */ jsx("option", { value: "", children: "Select warehouse..." }),
          warehouses.map((warehouse) => /* @__PURE__ */ jsx("option", { value: warehouse.id, children: [warehouse.warehouse_code, warehouse.name].filter(Boolean).join(" \u2014 ") }, warehouse.id))
        ] })
      ] })
    ] }),
    error && /* @__PURE__ */ jsx("div", { role: "alert", className: "mb-3 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700", children: error }),
    /* @__PURE__ */ jsx("div", { className: "card", children: /* @__PURE__ */ jsx(DataTable, { loading, emptyLabel: warehouseId ? "No stock in this warehouse" : "Select a warehouse", columns: [
      { key: "item_code", label: "Item Code" },
      { key: "description", label: "Description" },
      { key: "warehouse_name", label: "Warehouse" },
      { key: "location_code", label: "Location" },
      { key: "location_label", label: "Location Description" },
      { key: "quantity", label: "Quantity" },
      { key: "available_quantity", label: "Available Qty" },
      { key: "uom", label: "UOM" }
    ], rows }, warehouseId) })
  ] });
}
export {
  StockPage as default
};
