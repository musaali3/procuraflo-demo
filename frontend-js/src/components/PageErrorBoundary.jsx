import React from "react";

export default class PageErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("Procuraflo page rendering failed", error, info);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <main className="min-h-screen bg-slate-100 p-6">
        <section role="alert" className="mx-auto max-w-2xl rounded-2xl border border-rose-200 bg-white p-6 shadow-lg">
          <h1 className="text-xl font-semibold text-rose-800">This page could not be displayed</h1>
          <p className="mt-2 text-sm text-slate-600">
            Your data was not changed. Reload the current page; if the problem continues, return to the dashboard.
          </p>
          {import.meta.env.DEV && <p className="mt-3 rounded-lg bg-rose-50 px-3 py-2 font-mono text-xs text-rose-800">
            {String(this.state.error?.message || "Unknown rendering error")}
          </p>}
          <div className="mt-5 flex flex-wrap gap-2">
            <button type="button" autoFocus className="btn-primary error-action-highlight" onClick={() => window.location.reload()}>
              Reload Page
            </button>
            <button type="button" className="btn-secondary" onClick={() => { window.location.href = "/"; }}>
              Return to Dashboard
            </button>
          </div>
        </section>
      </main>
    );
  }
}
