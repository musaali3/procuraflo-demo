import { jsx as _jsx } from "react/jsx-runtime";
import { createContext, useCallback, useContext, useState } from 'react';
import client from '../api/client';
import { PRODUCT_BRAND } from '../config/brand';
import { setStoredCurrency } from '../utils/currency';
const fallback = { company_name: 'Company Name', logo_url: null };
const BrandingContext = createContext({ company: fallback, product: PRODUCT_BRAND, refresh: async () => { } });
export function BrandingProvider({ children }) {
    const [company, setCompany] = useState(fallback);
    const refresh = useCallback(async function refresh() { try {
        const { data } = await client.get('/settings/branding');
        setCompany(data);
        setStoredCurrency(data.base_currency || data.currency);
        document.title = `${PRODUCT_BRAND.name} | ${data.company_name || PRODUCT_BRAND.description}`;
    }
    catch {
        document.title = `${PRODUCT_BRAND.name} | Supply Chain Management`;
    } }, []);
    return _jsx(BrandingContext.Provider, { value: { company, product: PRODUCT_BRAND, refresh }, children: children });
}
export const useBranding = () => useContext(BrandingContext);
