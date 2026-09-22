import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { PRODUCT_BRAND } from '../config/brand';

export function resolveCompanyAssetUrl(source) {
  if (!source || /^(data:|blob:|https?:\/\/)/i.test(source)) return source;
  const apiBase = import.meta.env.VITE_API_URL || '/api';
  if (/^https?:\/\//i.test(apiBase)) {
    try { return new URL(source, new URL(apiBase).origin).toString(); } catch { return source; }
  }
  return source;
}

export function ProductBrand({ compact = false, inverse = false }) {
  return _jsxs("div", {
    className: `product-brand flex min-w-0 items-center gap-2 rounded-lg ${compact ? 'px-1.5 py-1' : 'px-2 py-1.5'}`,
    children: [
      _jsx("img", {
        src: PRODUCT_BRAND.logo,
        alt: `${PRODUCT_BRAND.name} logo`,
        className: `${compact ? 'h-8 w-8' : 'h-12 w-12'} shrink-0 object-contain`,
        draggable: "false",
      }),
      _jsxs("span", {
        className: "product-wordmark min-w-0 leading-none",
        children: [
          _jsx("span", { className: `block font-semibold tracking-tight ${compact ? 'text-base' : 'text-2xl'} ${inverse ? 'text-white' : 'text-slate-950'}`, children: PRODUCT_BRAND.name }),
          !compact && _jsx("span", { className: `mt-1 block text-[11px] font-medium uppercase tracking-[0.18em] ${inverse ? 'text-slate-300' : 'text-slate-500'}`, children: PRODUCT_BRAND.tagline })
        ]
      })
    ]
  });
}

export function CompanyLogo({ company, src, size = 'document', className = '' }) {
  const source = resolveCompanyAssetUrl(src || company?.logo_url);
  if (!source) return null;
  const sizes = { nav: 'h-8 w-12', compact: 'h-9 w-14', dashboard: 'h-16 w-24', document: 'h-20 w-28', report: 'h-16 w-24' };
  return _jsx("img", {
    src: source,
    alt: `${company?.name || company?.company_name || 'Company'} logo`,
    className: `company-logo ${sizes[size]} shrink-0 object-contain ${className}`,
    onError: event => { event.currentTarget.style.display = 'none'; }
  });
}

export function CompanyBrand({ company, compact = false, inverse = false }) {
  return _jsxs("div", {
    className: "flex min-w-0 items-center gap-3",
    children: [
      company?.logo_url ? _jsx(CompanyLogo, { company: company, size: compact ? 'compact' : 'report', className: "rounded bg-white p-1" }) : _jsx("div", { className: `${compact ? 'h-9 w-9' : 'h-16 w-16'} shrink-0 rounded-lg bg-white/10 flex items-center justify-center font-bold ${inverse ? 'text-white' : 'text-blue-700'}`, children: String(company?.name || company?.company_name || 'C').charAt(0) }),
      _jsxs("div", { className: "min-w-0", children: [
        _jsx("div", { className: `truncate font-semibold ${inverse ? 'text-white' : 'text-slate-900'}`, children: company?.name || company?.company_name || 'Company Name' }),
        !compact && company?.address && _jsx("div", { className: `text-xs whitespace-pre-line ${inverse ? 'text-slate-300' : 'text-slate-600'}`, children: company.address })
      ] })
    ]
  });
}

export function CompanyContact({ company }) {
  const contacts = [company?.phone, company?.email, company?.website].filter(Boolean);
  return _jsxs(_Fragment, {
    children: [
      contacts.length > 0 && _jsx("div", { className: "text-xs text-slate-600", children: contacts.join(' | ') }),
      (company?.tax_info || company?.registration_number) && _jsx("div", { className: "text-xs text-slate-600", children: [company.tax_info && `Tax/VAT: ${company.tax_info}`, company.registration_number && `Registration: ${company.registration_number}`].filter(Boolean).join(' | ') }),
      company?.branch_info && _jsxs("div", { className: "text-xs text-slate-600", children: ["Branch: ", company.branch_info] })
    ]
  });
}

export function DocumentCompanyHeader({ company, title, reference, date, fiscalYear }) {
  return _jsxs("header", {
    className: "flex justify-between gap-6 border-b-2 border-blue-700 pb-5",
    children: [
      _jsxs("div", { children: [
        _jsx(ProductBrand, {}),
        _jsx("div", { className: "mt-3", children: _jsx(CompanyBrand, { company: company }) }),
        _jsx("div", { className: "mt-2", children: _jsx(CompanyContact, { company: company }) })
      ] }),
      _jsxs("div", { className: "w-1/2 shrink-0 text-right", children: [
        _jsx("div", { className: "text-2xl font-bold tracking-wide text-blue-950", children: title }),
        reference && _jsx("div", { className: "mt-2 text-sm font-semibold", children: reference }),
        date && _jsxs("div", { className: "text-xs text-slate-600", children: ["Date: ", date] }),
        _jsxs("div", { className: "text-xs text-slate-600", children: ["Fiscal Year: ", fiscalYear || company?.financial_year || 'Not configured'] })
      ] })
    ]
  });
}

export function GeneratedByFooter({ note }) {
  return note ? _jsx("div", { className: "document-notes print-avoid-break mt-4 text-[10px]", children: note }) : null;
}
