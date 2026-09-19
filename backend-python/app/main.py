import os,asyncio
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
load_dotenv()

from .database import ensure_company_employee_schema, initialize_database

initialize_database()
ensure_company_employee_schema()

from .routes.auth import router as auth_router
from .routes.masters import router as masters_router
from .routes.advanced import router as advanced_router
from .routes.dashboard import router as dashboard_router
from .routes.delegations import router as delegations_router
from .routes.inventory import router as inventory_router
from .routes.attachments import router as attachments_router
from .routes.reports import router as reports_router
from .routes.procurement import router as procurement_router
from .routes.warehouse import router as warehouse_router
from .routes.settings import router as settings_router
from .routes.workforce import router as workforce_router
from .routes.controls import router as controls_router
from .routes.clearance import router as clearance_router
from .backup_service import scheduler_loop
from .tenancy import migrate_registered_tenants, tenant_record
from .database import reset_database, use_database
from .security import decode_token
from .storage import upload_path
import jwt

migrate_registered_tenants()

app = FastAPI(title="Procuraflo", description="Supply Chain Control System", docs_url=None, redoc_url=None)
LOGO_DIRECTORY = upload_path('logos')
app.mount('/uploads/logos', StaticFiles(directory=LOGO_DIRECTORY), name='company-logos')

@app.exception_handler(HTTPException)
async def compatible_http_error(_request: Request, exc: HTTPException):
    return JSONResponse({'error': str(exc.detail)}, status_code=exc.status_code, headers=exc.headers)

origins = [value.strip() for value in os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://localhost:5174,http://localhost:5175,http://localhost:4173,"
    "http://127.0.0.1:5173,http://127.0.0.1:5174,http://127.0.0.1:5175,http://127.0.0.1:4173",
).split(",") if value.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(masters_router)
app.include_router(advanced_router)
app.include_router(dashboard_router)
app.include_router(delegations_router)
app.include_router(inventory_router)
app.include_router(attachments_router)
app.include_router(reports_router)
app.include_router(procurement_router)
app.include_router(warehouse_router)
app.include_router(settings_router)
app.include_router(workforce_router)
app.include_router(controls_router)
app.include_router(clearance_router)

@app.middleware("http")
async def tenant_database_boundary(request:Request,call_next):
    header_key=str(request.headers.get('x-company-key')or'').strip().lower();token_key=''
    authorization=str(request.headers.get('authorization')or'')
    if authorization.lower().startswith('bearer '):
        try:token_key=str(decode_token(authorization.split(' ',1)[1]).get('tenant_key')or'').lower()
        except jwt.PyJWTError:return JSONResponse({'error':'Invalid or expired token'},401)
    if header_key and token_key and header_key!=token_key:return JSONResponse({'error':'Session company does not match the requested company'},401)
    key=token_key or header_key;context_token=None
    if key:
        tenant=tenant_record(key)
        if not tenant:return JSONResponse({'error':'Company login ID was not found'},401)
        context_token=use_database(Path(tenant['database_path']))
    try:return await call_next(request)
    finally:
        if context_token is not None:reset_database(context_token)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    allowed_hosts = [host.strip().lower().removeprefix("http://").removeprefix("https://").rstrip("/")
                     for host in os.getenv("LICENSED_HOSTNAMES", "").split(",") if host.strip()]
    actual_host = request.headers.get("host", "").lower()
    if allowed_hosts and actual_host not in allowed_hosts:
        return JSONResponse({"error": "This Procuraflo installation is not licensed for this host."}, 403)
    public_write_paths = {'/api/auth/login','/api/auth/register-company','/api/settings/maintenance/status'}
    if request.method not in {'GET','HEAD','OPTIONS'} and request.url.path not in public_write_paths:
        from .database import fetch_one
        maintenance=fetch_one('SELECT active_yn FROM system_maintenance WHERE id=1')or{}
        if maintenance.get('active_yn'):
            return JSONResponse({'error':'SYSTEM MAINTENANCE — Month-End Backup in Progress. New transactions are temporarily disabled.'},503)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


@app.get("/api/health")
def health():
    return {"status": "ok", "system": "Procuraflo", "description": "Supply Chain Control System"}

@app.on_event('startup')
async def start_month_end_scheduler():
    app.state.backup_scheduler=asyncio.create_task(scheduler_loop())

@app.on_event('shutdown')
async def stop_month_end_scheduler():
    task=getattr(app.state,'backup_scheduler',None)
    if task:task.cancel()
