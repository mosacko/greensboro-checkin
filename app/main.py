# app/main.py

from fastapi import FastAPI, Request, Depends, Response, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse # Add PlainTextResponse
from sqlalchemy.orm import Session
from datetime import date, datetime, timezone # Import date
from zoneinfo import ZoneInfo
from collections import defaultdict # Import defaultdict
from starlette.middleware.sessions import SessionMiddleware # Add SessionMiddleware

# --- ADD THESE AUTH IMPORTS ---
from authlib.integrations.starlette_client import OAuth
from authlib.integrations.base_client.errors import OAuthError
from .models import Employee # Import Employee model
# -----------------------------

from .settings import settings
from .routers import attendance as attendance_router
from .routers import metrics as metrics_router
from .database import get_db
from .models import Attendance

import os

app = FastAPI(title="Greensboro Check-in")

# --- ADD SESSION MIDDLEWARE (Must be before routers) ---
SESSION_TIMEOUT_SECONDS = 8 * 60 * 60 # 8 hours in seconds

app.add_middleware(
    SessionMiddleware, 
    secret_key=settings.secret_key, 
    max_age=SESSION_TIMEOUT_SECONDS # Cookie expires after 8 hours
)
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
app.include_router(metrics_router.router, prefix="", tags=["metrics"]) # ADD THIS LINE

# --- ADD SSO ROUTES ---

@app.get("/login")
async def login(request: Request):
    """Redirects the user to Microsoft's login page."""
    
    # --- STORE INTENDED SITE ---
    # Check if the user came from a /scan URL with a site parameter
    referer = request.headers.get("referer")
    intended_site = settings.default_site # Default if not found
    if referer:
        try:
            from urllib.parse import urlparse, parse_qs
            parsed_url = urlparse(referer)
            if parsed_url.path == "/scan":
                query_params = parse_qs(parsed_url.query)
                site_list = query_params.get("site")
                if site_list and site_list[0] in settings.sites:
                    intended_site = site_list[0]
        except Exception:
            pass # Keep default site if parsing fails
            
    request.session["intended_site"] = intended_site
    print(f"Stored intended site in session: {intended_site}") # Add logging
    # --------------------------
    
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

    # Upsert employee record (keep this)
    emp = db.query(Employee).filter(Employee.email == email).first()
    if not emp:
        emp = Employee(email=email, display_name=name)
        db.add(emp)
    else: 
        emp.display_name = name
    db.commit() # Commit employee upsert first

    # --- AUTOMATIC CHECK-IN ---
    site_code = request.session.pop("intended_site", settings.default_site) 
    # Get name and email reliably from session
    user_session_data = request.session.get("user", {}) 
    name = user_session_data.get("name", "Unknown")
    email = user_session_data.get("email") # Get email
    print(f"Attempting check-in for site: {site_code}, User: {email or name}") 

    # --- Calculate current time and date in EST ---
    now_utc = datetime.now(timezone.utc)
    try:
        est_zone = ZoneInfo("America/New_York") 
        now_est = now_utc.astimezone(est_zone)
        local_date_str = now_est.strftime("%Y-%m-%d") 
    except Exception as e:
        print(f"Timezone conversion error: {e}. Falling back to UTC date.")
        local_date_str = now_utc.strftime("%Y-%m-%d")
    # ---------------------------------------------

    # Check if already checked in today before creating new record
    if email: # Only check if we have an email
        try:
            existing_checkin = db.query(Attendance).filter(
                Attendance.local_date == local_date_str,
                Attendance.user_email == email, # <-- Check by email
                Attendance.event_type == "check_in",
                Attendance.is_valid == True
            ).first()
            if existing_checkin:
                 print(f"User {email} already checked in today via callback ({local_date_str}).")
                 return RedirectResponse(url="/already-checked-in") 
        except Exception as e:
            print(f"Error checking existing check-in during callback: {e}")
            # Proceed if check fails? For now, yes.

    # Create the Attendance record directly
    new_checkin = Attendance(
        site=site_code,
        event_type="check_in",
        is_valid=True,
        source="sso_callback", 
        timestamp_utc=now_utc, 
        local_date=local_date_str, 
        user_name=name, 
        user_email=email # <-- Save the email
    )
    db.add(new_checkin)
    try:
        db.commit()
        print(f"Check-in successful for {email or name} at {site_code} on {local_date_str} (EST)") 
        return RedirectResponse(url="/checkin-success") 
    except Exception as e:
        db.rollback()
        print(f"ERROR during check-in commit: {e}") 
        return PlainTextResponse(f"Login successful, but check-in failed: {e}", status_code=500)
    # -------------------------

@app.get("/logout")
def logout(request: Request):
    """Clears the user's session cookie."""
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)

# ------------------------

@app.get("/checkin-success", response_class=HTMLResponse)
def checkin_success(request: Request):
    """Displays a simple success message after check-in."""
    return templates.TemplateResponse("checkin_success.html", {"request": request})

@app.get("/already-checked-in", response_class=HTMLResponse)
def already_checked_in(request: Request):
    """Displays a message that the user already checked in today."""
    return templates.TemplateResponse("already_checked_in.html", {"request": request})

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
    """Shows the main admin dashboard with attendance records grouped by date."""
    
    if request.cookies.get("admin_auth") != "super_secret_token":
        return RedirectResponse(url="/admin/login")
    
    # Fetch all valid check-in records, most recent first
    all_records = db.query(Attendance)\
                    .filter(Attendance.event_type == "check_in", Attendance.is_valid == True)\
                    .order_by(Attendance.timestamp_utc.desc())\
                    .all()

    # --- Format Timestamps for Display ---
    try:
        est_zone = ZoneInfo("America/New_York")
    except Exception:
        est_zone = timezone.utc # Fallback to UTC if zoneinfo fails
        print("WARNING: Could not load America/New_York timezone. Falling back to UTC.")

    formatted_records = []
    for rec in all_records:
        if rec.timestamp_utc:
            # Convert UTC time to EST/EDT
            timestamp_est = rec.timestamp_utc.astimezone(est_zone)
            # Create a formatted string
            est_str = timestamp_est.strftime('%Y-%m-%d %H:%M:%S %Z') # Includes timezone abbr (EST/EDT)
        else:
            est_str = 'N/A'

        # Create a dictionary or object copy to avoid modifying the original SQLAlchemy object
        formatted_rec = {
            "id": rec.id,
            "timestamp_utc": rec.timestamp_utc, # Keep original UTC if needed elsewhere
            "timestamp_display": est_str,      # Add the formatted string
            "site": rec.site,
            "event_type": rec.event_type,
            "user_name": rec.user_name,
            "device_local_id": rec.device_local_id,
            "geo_lat": rec.geo_lat,
            "geo_lon": rec.geo_lon,
            # Add other fields if your template uses them
        }
        formatted_records.append(formatted_rec)
    # ------------------------------------
    
    # --- Group records by date ---
    records_by_date = defaultdict(list)
    for rec in all_records:
        # Use local_date if available, otherwise derive from timestamp_utc
        record_date_str = rec.local_date 
        if not record_date_str and rec.timestamp_utc:
             # Assuming UTC, adjust if your server/users are in a specific timezone
            record_date_str = rec.timestamp_utc.strftime('%Y-%m-%d') 
        
        if record_date_str:
            try:
                # Convert string date to date object for sorting keys later
                record_date = date.fromisoformat(record_date_str) 
                records_by_date[record_date].append(rec)
            except ValueError:
                # Handle cases where local_date might be invalid format
                records_by_date["Invalid Date"].append(rec) 

    # Sort the dates so the most recent day appears first in the accordion
    sorted_dates = sorted(records_by_date.keys(), reverse=True)
    # -----------------------------
    
    # --- Logging (keep for now) ---
    print(f"--- /admin ---")
    if all_records:
        print(f"Total records fetched: {len(all_records)}")
        print(f"Data grouped into {len(sorted_dates)} dates.")
    else:
        print("No records found in database.")
    # -----------------------------
    
    return templates.TemplateResponse(
        "admin.html", 
        {
            "request": request, 
            # Pass the grouped data and sorted dates to the template
            "records_by_date": records_by_date, 
            "sorted_dates": sorted_dates, 
            "all_records": formatted_records
        }
    )
# -------------------------------------------------------------