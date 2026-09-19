import WorkforceSetupPage from "./WorkforceSetupPage";

export default function ReferenceDataPage() {
  return (
    <div className="split-setup-page">
      <h1 className="text-2xl font-bold">Reference Data</h1>
      <p className="mb-4 text-sm text-slate-500">
        Company-wide geographic, currency, and exchange-rate reference records.
      </p>
      <WorkforceSetupPage section="reference" />
    </div>
  );
}
