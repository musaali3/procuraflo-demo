import { jsx as _jsx } from "react/jsx-runtime";
import { createContext, useContext, useEffect, useState } from 'react';
import client from '../api/client';
const AuthContext = createContext(undefined);
function clearStoredSession() {
    localStorage.removeItem('procuraflow_token');
    localStorage.removeItem('procuraflow_user');
}
export function AuthProvider({ children }) {
    const [user, setUser] = useState(null);
    const [status, setStatus] = useState('initializing');
    useEffect(() => {
        const token = localStorage.getItem('procuraflow_token');
        const companyKey = localStorage.getItem('procuraflow_company_key');
        if (!token || !companyKey) {
            clearStoredSession();
            setStatus('unauthenticated');
            return;
        }
        let active = true;
        // Never publish the cached user to protected routes. The signed token
        // and backend tenant boundary must be validated first.
        client.get('/auth/me').then(({ data }) => {
            if (!active)
                return;
            localStorage.setItem('procuraflow_user', JSON.stringify(data));
            setUser(data);
            setStatus('authenticated');
        }).catch(() => {
            if (!active)
                return;
            clearStoredSession();
            setUser(null);
            setStatus('unauthenticated');
        });
        const rejectSession = () => {
            if (!active)
                return;
            clearStoredSession();
            setUser(null);
            setStatus('unauthenticated');
        };
        window.addEventListener('procuraflow:unauthorized', rejectSession);
        return () => {
            active = false;
            window.removeEventListener('procuraflow:unauthorized', rejectSession);
        };
    }, []);
    async function login(companyKey, username, password) {
        const normalizedCompanyKey = String(companyKey || '').trim().toLowerCase();
        clearStoredSession();
        setUser(null);
        setStatus('unauthenticated');
        const { data } = await client.post('/auth/login', { company_key: normalizedCompanyKey, username, password }, { headers: { 'X-Company-Key': normalizedCompanyKey }, skipTenant: true, skipAuth: true });
        if (!data?.token || !data?.user || data.user.tenant_key !== normalizedCompanyKey)
            throw new Error('The server returned an invalid authentication response.');
        localStorage.setItem('procuraflow_company_key', normalizedCompanyKey);
        localStorage.setItem('procuraflow_token', data.token);
        localStorage.setItem('procuraflow_user', JSON.stringify(data.user));
        setUser(data.user);
        setStatus('authenticated');
    }
    function logout() {
        client.post('/dashboard/activity/logout').catch(() => undefined).finally(() => {
            localStorage.removeItem('procuraflow_token');
            localStorage.removeItem('procuraflow_user');
            setUser(null);
            setStatus('unauthenticated');
        });
    }
    return _jsx(AuthContext.Provider, { value: { user, status, loading: status === 'initializing', login, logout }, children: children });
}
export function useAuth() {
    const ctx = useContext(AuthContext);
    if (!ctx)
        throw new Error('useAuth must be used within AuthProvider');
    return ctx;
}
