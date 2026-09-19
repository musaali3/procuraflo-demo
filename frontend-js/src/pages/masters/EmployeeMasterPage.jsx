import { useSearchParams } from "react-router-dom";
import EmployeesPage from "./EmployeesPage";
import GeneralEmployeesPage from "./GeneralEmployeesPage";

const tabs = [
  {
    id: "supply-chain",
    label: "Supply Chain Employees",
    description: "Warehouse and Procurement employees",
  },
  {
    id: "company",
    label: "Company Employees",
    description: "Production, Quality, Laboratory, and other departments",
  },
];

export default function EmployeeMasterPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab =
    searchParams.get("tab") === "company" ? "company" : "supply-chain";

  return (
    <div className="space-y-4">
      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="mb-3">
          <h1 className="text-xl font-semibold text-slate-900">
            Employee Master
          </h1>
          <p className="text-sm text-slate-500">
            Maintain supply-chain system users separately from the wider company
            workforce.
          </p>
        </div>
        <div
          className="grid gap-2 md:grid-cols-2"
          role="tablist"
          aria-label="Employee master directories"
        >
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={activeTab === tab.id}
              onClick={() =>
                setSearchParams(
                  tab.id === "company" ? { tab: "company" } : {},
                  { replace: true },
                )
              }
              className={`rounded-xl border px-4 py-3 text-left transition ${activeTab === tab.id ? "border-blue-500 bg-blue-50 text-blue-950 shadow-sm ring-1 ring-blue-200" : "border-slate-200 bg-slate-50 text-slate-600 hover:border-blue-300 hover:bg-white"}`}
            >
              <span className="block text-sm font-semibold">{tab.label}</span>
              <span className="mt-0.5 block text-xs opacity-75">
                {tab.description}
              </span>
            </button>
          ))}
        </div>
      </section>
      <div role="tabpanel">
        {activeTab === "company" ? <GeneralEmployeesPage /> : <EmployeesPage />}
      </div>
    </div>
  );
}
