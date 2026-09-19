import { errorContext } from '../utils/errorGuidance';
import axios from 'axios';
const client = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api',
});
const REFRESH_EVENT = 'procuraflo:data-changed';
const WRITE_METHODS = new Set(['post', 'put', 'patch', 'delete']);
const READ_LIKE_MUTATION = /\/(preview|pricing|export|backup|template|similarity)(\/|$)|\/download|\/document$/i;
function shouldNotifyDataChanged(response) {
    const config = response?.config || {};
    const method = String(config.method || '').toLowerCase();
    const url = String(config.url || '');
    if (!WRITE_METHODS.has(method) || config.skipAutoRefresh)
        return false;
    if (READ_LIKE_MUTATION.test(url) || config.responseType === 'blob')
        return false;
    return response.status >= 200 && response.status < 300;
}
client.interceptors.request.use((config) => {
    config.errorGuidanceContext = errorContext();
    if(config.method==='get')config.errorGuidanceContext.action=null;
    if(String(config.url).includes('/settings/imports/') && config.data instanceof FormData){const section=config.errorGuidanceContext.action?.closest('section');if(section)config.errorGuidanceContext.scope=section;}
    const token = localStorage.getItem('procuraflow_token');
    if (token && !config.skipAuth)
        config.headers.Authorization = `Bearer ${token}`;
    const companyKey = localStorage.getItem('procuraflow_company_key');
    const hasCompanyHeader = typeof config.headers?.has === 'function'
        ? config.headers.has('X-Company-Key')
        : Object.keys(config.headers || {}).some((key) => key.toLowerCase() === 'x-company-key');
    if (companyKey && !config.skipTenant && !hasCompanyHeader)
        config.headers['X-Company-Key'] = companyKey;
    return config;
});
client.interceptors.response.use((res) => {
    if (shouldNotifyDataChanged(res)) {
        window.dispatchEvent(new CustomEvent(REFRESH_EVENT, {
            detail: {
                method: String(res.config?.method || '').toUpperCase(),
                url: res.config?.url,
                status: res.status,
            },
        }));
    }
    return res;
}, async (err) => {
    if(err.response?.data instanceof Blob){try{err.response.data=JSON.parse(await err.response.data.text());}catch{/* Keep the original error when the response is not JSON. */}}
    if (err.response?.status === 401) {
        // A rejected anonymous login is not an expired application session.
        // Only invalidate React's authoritative auth state when the rejected
        // request actually carried the stored bearer token.
        const authorization = err.config?.headers?.Authorization || err.config?.headers?.get?.('Authorization');
        if (authorization) {
            localStorage.removeItem('procuraflow_token');
            localStorage.removeItem('procuraflow_user');
            window.dispatchEvent(new CustomEvent('procuraflow:unauthorized', {
                detail: { message: err.response?.data?.error || 'Your session has expired. Please sign in again.' },
            }));
        }
    }
    const data=err.response?.data;
    let issues=Array.isArray(data?.detail)?data.detail:Array.isArray(data?.errors)?data.errors:[];
    const message=typeof data?.error==='string'?data.error:typeof data?.detail==='string'?data.detail:issues.length?issues.map(x=>x.msg||x.message).join('; '):err.response?'The request could not be completed.':'Unable to connect to the server. Check your connection and try again.';
    if(data && typeof data==='object' && !data.error)data.error=message;
    if(String(err.config?.url).includes('/settings/imports/') && [400,409,422].includes(err.response?.status) && err.config?.data instanceof FormData)issues=[{field:'file',message:message+' Correct the indicated data in the source file, then select the corrected file and import again.'}];
    window.dispatchEvent(new CustomEvent('procuraflo:api-error',{detail:{message,issues,context:err.config?.errorGuidanceContext||errorContext(),status:err.response?.status,focus:err.config?.method!=='get'}}));
    return Promise.reject(err);
});
export default client;
export { REFRESH_EVENT };
