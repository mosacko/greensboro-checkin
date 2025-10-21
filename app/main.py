# app/main.py

from fastapi import FastAPI, Request, Depends, Response, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse # Add PlainTextResponse
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware # Add SessionMiddleware

# --- ADD THESE AUTH IMPORTS ---
from authlib.integrations.starlette_client import OAuth
from authlib.integrations.base_client.errors import OAuthError
from .models import Employee # Import Employee model
# -----------------------------

from .settings import settings
from .routers import attendance as attendance_router
from .database import get_db
from .models import Attendance # Keep this import

import os

app = FastAPI(title="Greensboro Check-in")

# --- ADD SESSION MIDDLEWARE (Must be before routers) ---
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)
# --------------------------------------------------------

# Remove or comment out the StaticFiles line if you don't have an app/static folder
# app.mount("/static", StaticFiles(directory="app/static"), name="static") 
# Build path relative to the current file (main.py)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# --- ADD OAUTH SETUP ---
oauth = OAuth()
oauth.register(
    name="azure",
    server_metadata_url=f"https://login.microsoftonline.com/{settings.oidc_tenant}/v2.0/.well-known/openid-configuration",
    client_id=settings.oidc_client_id,
    client_secret=settings.oidc_client_secret,
    client_kwargs={"scope": "openid profile email offline_access"},
)
# ------------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    user = request.session.get("user") # Pass user info to template
    return templates.TemplateResponse("home.html", {"request": request, "sites": settings.sites, "user": user})

app.include_router(attendance_router.router, prefix="", tags=["attendance"])

# --- ADD SSO ROUTES ---

@app.get("/login")
async def login(request: Request):
    """Redirects the user to Microsoft's login page."""
    redirect_uri = settings.oidc_redirect_uri or str(request.url_for("auth_callback"))
    return await oauth.azure.authorize_redirect(request, redirect_uri)

@app.get("/auth/callback")
async def auth_callback(request: Request, db: Session = Depends(get_db)):
    """Handles the response back from Microsoft after login."""
    if not oauth.azure.client_id:
        return PlainTextResponse("SSO not configured (missing client_id)", status_code=400)

    try:
        token = await oauth.azure.authorize_access_token(request)
    except OAuthError as e:
        return PlainTextResponse(f"SSO error: {e.error} - {e.description}", status_code=400)
    except Exception as e:
        return PlainTextResponse(f"Auth callback exception: {repr(e)}", status_code=400)

    user_info = token.get("userinfo") or {}
    email = user_info.get("email") or user_info.get("preferred_username") or user_info.get("upn") or ""
    name = user_info.get("name") or (email.split("@")[0] if email else "Unknown")

    # --- ADD LOGGING HERE ---
    print(f"--- /auth/callback ---")
    print(f"User Info received from Azure: {user_info}")
    print(f"Extracted Email: {email}")
    print(f"Extracted Name: {name}")
    # ---

    if not email:
        return PlainTextResponse("No email found in token/claims", status_code=400)

    # Optional: Check domain allowlist
    if settings.allowed_domains:
        domain = email.split("@")[-1].lower()
        if domain not in [d.lower() for d in settings.allowed_domains]:
            return PlainTextResponse(f"Unauthorized domain: {domain}", status_code=403)

    # Store user info in the session
    session_data = {"email": email, "name": name} # Store in a variable first
    request.session["user"] = {"email": email, "name": name}

    # Upsert employee record
    emp = db.query(Employee).filter(Employee.email == email).first()
    if not emp:
        emp = Employee(email=email, display_name=name)
        db.add(emp)
    else: 
        emp.display_name = name # Update name if needed
    db.commit()

    return RedirectResponse(url="/") # Redirect to homepage

@app.get("/logout")
def logout(request: Request):
    """Clears the user's session cookie."""
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)

# ------------------------

# --- Admin Authentication (Keep your existing admin routes) ---
@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request):
    return templates.TemplateResponse("admin_login.html", {"request": request})

@app.post("/admin/login")
def process_admin_login(response: Response, password: str = Form(...)):
    if password == settings.admin_password:
        response = RedirectResponse(url="/admin", status_code=303)
        response.set_cookie(key="admin_auth", value="super_secret_token", httponly=True, samesite="lax")
        return response
    else:
        return RedirectResponse(url="/admin/login", status_code=303)

@app.get("/admin/logout")
def admin_logout(response: Response):
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(key="admin_auth")
    return response

# Inside app/main.py

@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    """Shows the main admin dashboard with all attendance records."""

    if request.cookies.get("admin_auth") != "super_secret_token":
        return RedirectResponse(url="/admin/login")

    # Fetch records
    records = db.query(Attendance).order_by(Attendance.timestamp_utc.desc()).all()

    # --- ADD LOGGING HERE ---
    print(f"--- /admin ---")
    if records:
        print(f"First record fetched: ID={records[0].id}, Name={records[0].user_name}") 
        print(f"Number of records fetched: {len(records)}")
    else:
        print("No records found in database.")
    # ------------------------

    return templates.TemplateResponse(
        "admin.html", 
        {"request": request, "records": records}
    )
# -------------------------------------------------------------