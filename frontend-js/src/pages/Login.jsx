import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import client from '../api/client';
import { useAuth } from '../contexts/AuthContext';
import { PRODUCT_BRAND } from '../config/brand';
import { ProductBrand } from '../components/Branding';

const registrationInitial={company_name:'',company_key:'',company_email:'',admin_name:'',admin_email:'',username:'',password:'',confirm_password:''};

export default function Login(){
  const {login}=useAuth();const navigate=useNavigate();
  const [mode,setMode]=useState('login');const [companyKey,setCompanyKey]=useState(localStorage.getItem('procuraflow_company_key')||'');const [username,setUsername]=useState('');const [password,setPassword]=useState('');
  const [registration,setRegistration]=useState(registrationInitial);const [error,setError]=useState('');const [message,setMessage]=useState('');const [loading,setLoading]=useState(false);
  const [registrationOpen,setRegistrationOpen]=useState(false);
  useEffect(()=>{client.get('/auth/registration-status',{skipAuth:true,skipTenant:true}).then(({data})=>{const open=Boolean(data?.registration_enabled);setRegistrationOpen(open);if(!open)setMode('login');}).catch(()=>setRegistrationOpen(false));},[]);
  async function handleLogin(event){event.preventDefault();setError('');setLoading(true);try{await login(companyKey,username,password);navigate('/');}catch(err){const detail=err?.response?.data?.error;if(detail)setError(String(detail));else if(err?.request)setError('Unable to connect to Procuraflo. Please try again.');else setError(err?.message||'Sign in could not be completed.');}finally{setLoading(false);}}
  async function handleRegistration(event){event.preventDefault();setError('');setMessage('');if(!registrationOpen){setMode('login');setError('Company registration is closed for this installation.');return;}if(registration.password!==registration.confirm_password){setError('Passwords do not match');return;}setLoading(true);try{const payload={...registration};delete payload.confirm_password;const {data}=await client.post('/auth/register-company',payload,{skipAuth:true,skipTenant:true});setCompanyKey(data.company_key);setUsername(registration.username);setPassword('');setRegistration(registrationInitial);setRegistrationOpen(false);setMode('login');setMessage(`${data.company_name} was registered. Sign in with company ID "${data.company_key}".`);}catch(err){const detail=err?.response?.data?.error||err?.response?.data?.detail;if(detail)setError(String(detail));else if(err?.request)setError('The registration service could not be reached. Check the backend URL and allow this website in the backend CORS_ORIGINS setting.');else setError(err?.message||'Company registration failed');}finally{setLoading(false);}}
  const update=(key,value)=>setRegistration(current=>({...current,[key]:value, ...(key==='company_name'&&!current.company_key?{company_key:value.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'')}:{})}));
  return <div className="login-shell min-h-screen px-5 py-6 sm:px-8 lg:px-12">
    <div className="login-page mx-auto flex min-h-[calc(100vh-3rem)] w-full max-w-7xl flex-col">
      <header className="login-header flex items-center justify-between">
        <ProductBrand compact />
        <div className="hidden text-sm font-medium text-white/70 sm:block">{PRODUCT_BRAND.tagline}</div>
      </header>
      <main className="login-panel grid flex-1 items-center gap-10 py-8 lg:grid-cols-[1.05fr_0.95fr] lg:gap-16">
        <aside className="login-promo-card order-2 mx-auto w-full max-w-[42rem] p-7 lg:order-1 lg:p-10">
          <h2 className="mt-4 max-w-xl text-4xl font-semibold leading-tight tracking-tight text-white sm:text-5xl">Procurement, warehouse, and inventory work in one place.</h2>
          <div className="login-simple-card mt-8">
            <div>
              <span>Daily focus</span>
              <strong>Approve. Receive. Issue. Reconcile.</strong>
            </div>
            <p>Keep procurement and warehouse teams aligned without chasing spreadsheets or disconnected records.</p>
          </div>
          <div className="login-simple-points">
            <span>Purchase control</span>
            <span>Warehouse visibility</span>
            <span>Audit ready</span>
          </div>
          <div className="login-promo-actions">
            <button type="button" className="login-promo-link" onClick={()=>setMode(registrationOpen?'register':'login')}>{registrationOpen?'Create workspace':'Workspace access'} &rarr;</button>
            <span>Built for controlled procurement teams</span>
          </div>
        </aside>
        <section className="login-form-panel order-1 mx-auto w-full max-w-[38rem] lg:order-2">
          <div>
            <div className="login-form-kicker">{mode==='login'?'Secure access':'Workspace setup'}</div>
            <h1 className="login-title mt-3 text-4xl font-semibold leading-tight tracking-tight text-white sm:text-5xl">Welcome to your ProcuraFlo workspace</h1>
            <p className="mt-4 max-w-md text-sm leading-6 text-white/72">{mode==='login'?'Use your company login ID and employee credentials to continue.':'Create the first protected company workspace and administrator account.'}</p>
          </div>
          <div className={`login-mode-switch mt-8 grid ${registrationOpen?'grid-cols-2':'grid-cols-1'}`}>
            <button type="button" className={mode==='login'?'is-active':''} onClick={()=>{setMode('login');setError('');}}>Log in</button>
            {registrationOpen&&<button type="button" className={mode==='register'?'is-active':''} onClick={()=>{setMode('register');setError('');}}>Register</button>}
          </div>
          {message&&<div className="mt-5 rounded-md border border-emerald-200/40 bg-emerald-300/15 p-3 text-sm text-emerald-50">{message}</div>}
          {error&&<div data-error-message="true" role="alert" className="mt-5 rounded-md border border-rose-200/40 bg-rose-300/15 p-3 text-sm text-rose-50">{error}</div>}
          {mode==='login'?<form onSubmit={handleLogin} className="mt-6 space-y-5">
            <div>
              <label className="login-label">Company login ID</label>
              <div className="login-domain-input mt-2">
                <input data-field={"companyKey"} value={companyKey} onChange={e=>setCompanyKey(e.target.value.toLowerCase())} placeholder="your-company" autoFocus required/>
                <span>.procuraflo.com</span>
              </div>
            </div>
            <div>
              <label className="login-label">Username</label>
              <input data-field={"username"} className="login-input mt-2" value={username} onChange={e=>setUsername(e.target.value)} autoComplete="username" required/>
            </div>
            <div>
              <label className="login-label">Password</label>
              <input data-field={"password"} className="login-input mt-2" type="password" value={password} onChange={e=>setPassword(e.target.value)} autoComplete="current-password" required/>
            </div>
            <button className="login-submit w-full" disabled={loading}>{loading?'Signing in...':'Log in'}</button>
          </form>
          :<form onSubmit={handleRegistration} className="mt-6 grid gap-4 sm:grid-cols-2">
            <div><label className="login-label">Company Name</label><input data-field={"company_name"} className="login-input mt-2" value={registration.company_name} onChange={e=>update('company_name',e.target.value)} required/></div>
            <div><label className="login-label">Company Login ID</label><input data-field={"company_key"} className="login-input mt-2" value={registration.company_key} onChange={e=>update('company_key',e.target.value.toLowerCase().replace(/[^a-z0-9-]/g,''))} pattern="[a-z0-9][a-z0-9-]{2,47}" required/></div>
            <div><label className="login-label">Company Email</label><input data-field={"company_email"} className="login-input mt-2" type="email" value={registration.company_email} onChange={e=>update('company_email',e.target.value)}/></div>
            <div><label className="login-label">Administrator Name</label><input data-field={"admin_name"} className="login-input mt-2" value={registration.admin_name} onChange={e=>update('admin_name',e.target.value)} required/></div>
            <div><label className="login-label">Administrator Email</label><input data-field={"admin_email"} className="login-input mt-2" type="email" value={registration.admin_email} onChange={e=>update('admin_email',e.target.value)}/></div>
            <div><label className="login-label">Administrator Username</label><input data-field={"username"} className="login-input mt-2" value={registration.username} onChange={e=>update('username',e.target.value)} required/></div>
            <div><label className="login-label">Password</label><input data-field={"password"} className="login-input mt-2" type="password" minLength="10" value={registration.password} onChange={e=>update('password',e.target.value)} required/></div>
            <div><label className="login-label">Confirm Password</label><input data-field={"confirm_password"} className="login-input mt-2" type="password" minLength="10" value={registration.confirm_password} onChange={e=>update('confirm_password',e.target.value)} required/></div>
            <div className="sm:col-span-2"><button className="login-submit w-full" disabled={loading}>{loading?'Creating workspace...':'Register company'}</button></div>
          </form>}
          <div className="login-footer mt-10 border-t border-white/18 pt-5 text-sm text-white/68">
            <span>Need access?</span>
            <button type="button" onClick={()=>setMode(registrationOpen?'register':'login')}>{registrationOpen?'Register a company workspace':'Contact your administrator'}</button>
          </div>
        </section>
      </main>
    </div>
  </div>;
}
