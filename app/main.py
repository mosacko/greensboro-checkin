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

app = FastAPI(title="Greenville Check-in")

# --- ADD SESSION MIDDLEWARE (Must be before routers) ---
SESSION_TIMEOUT_SECONDS = 8 * 60 * 60 # 8 hours in seconds

app.add_middleware(
    SessionMiddleware, 
    secret_key=settings.secret_key, 
    max_age=SESSION_TIMEOUT_SECONDS # Cookie expires after 8 hours
)
# --------------------------------------------------------

# Remove or comment out the StaticFiles line if you don't have an app/static folder
app.mount("/static", StaticFiles(directory="app/static"), name="static") 
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
    """
    Handles the response back from Microsoft after login.
    Saves user info to session, upserts employee record,
    and redirects user back to the /scan page.
    """
    # 1. Check if SSO is configured
    if not oauth.azure.client_id:
        return PlainTextResponse("SSO not configured (missing client_id)", status_code=400)

    # 2. Get the authorization token from Microsoft
    try:
        token = await oauth.azure.authorize_access_token(request)
    except OAuthError as e:
        print(f"OAuthError during token fetch: {e.error} - {e.description}") # Add logging
        return PlainTextResponse(f"SSO error: {e.error} - {e.description}", status_code=400)
    except Exception as e:
        print(f"Exception during token fetch: {repr(e)}") # Add logging
        return PlainTextResponse(f"Auth callback exception: {repr(e)}", status_code=400)

    # 3. Extract user information from the token
    user_info = token.get("userinfo") or {}
    email = user_info.get("email") or user_info.get("preferred_username") or user_info.get("upn") or ""
    name = user_info.get("name") or (email.split("@")[0] if email else "Unknown")

    print(f"--- /auth/callback ---") # Keep logging
    print(f"User Info received from Azure: {user_info}")
    print(f"Extracted Email: {email}")
    print(f"Extracted Name: {name}")

    if not email:
        print("ERROR: No email found in token/claims") # Add logging
        return PlainTextResponse("No email found in token/claims", status_code=400)

    # 4. Optional: Check if the user's domain is allowed
    if settings.allowed_domains:
        domain = email.split("@")[-1].lower()
        if domain not in [d.lower() for d in settings.allowed_domains]:
            print(f"Unauthorized domain: {domain}") # Add logging
            return PlainTextResponse(f"Unauthorized domain: {domain}", status_code=403)

    # 5. Store user information in the session cookie
    session_data = {"email": email, "name": name}
    request.session["user"] = session_data
    print(f"Data saved to session: {session_data}") # Keep logging

    # 6. Upsert (update or insert) the employee record in our database
    try:
        emp = db.query(Employee).filter(Employee.email == email).first()
        if not emp:
            print(f"Creating new Employee record for: {email}") # Add logging
            emp = Employee(email=email, display_name=name)
            db.add(emp)
        else:
            if emp.display_name != name: # Only update if name changed
                 print(f"Updating display name for: {email}") # Add logging
                 emp.display_name = name
            else:
                 print(f"Found existing Employee record for: {email}") # Add logging

        db.commit() # Commit employee changes
    except Exception as e:
        db.rollback()
        print(f"ERROR during Employee upsert: {e}") # Add logging
        # Decide how to handle - maybe still redirect? Or show error?
        # For now, let's still try to redirect, but log the error.

    # 7. Redirect back to the originally intended /scan page
    # Retrieve the site stored before the login redirect
    intended_site = request.session.pop("intended_site", settings.default_site)
    redirect_url = f"/scan?site={intended_site}"
    print(f"Login successful, redirecting back to: {redirect_url}") # Keep logging
    return RedirectResponse(url=redirect_url)

@app.get("/logout")
def logout(request: Request):
    """Clears the user's session cookie."""
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)

# ------------------------

#@app.get("/checkin-success", response_class=HTMLResponse)
#def checkin_success(request: Request):
#    """Displays a simple success message after check-in."""
#    return templates.TemplateResponse("checkin_success.html", {"request": request})

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
    """Shows the main admin dashboard with attendance records grouped by month and reason."""
    
    if request.cookies.get("admin_auth") != "super_secret_token":
        return RedirectResponse(url="/admin/login")
    
    # Fetch all valid check-in records, most recent first
    all_records_raw = db.query(Attendance)\
                        .filter(Attendance.event_type == "check_in", Attendance.is_valid == True)\
                        .order_by(Attendance.timestamp_utc.desc())\
                        .all()
    
    # --- Format Timestamps and Prepare Data ---
    try:
        est_zone = ZoneInfo("America/New_York")
    except Exception:
        est_zone = timezone.utc 
        print("WARNING: Could not load America/New_York timezone. Falling back to UTC.")

    formatted_records = []
    records_by_month = defaultdict(list)
    records_by_reason = defaultdict(list)
    
    for rec in all_records_raw:
        # Format timestamp
        if rec.timestamp_utc:
            timestamp_est = rec.timestamp_utc.astimezone(est_zone)
            est_str = timestamp_est.strftime('%Y-%m-%d %H:%M:%S %Z') 
            month_key = timestamp_est.strftime('%Y-%m') # Key for month grouping (e.g., "2025-10")
            record_date = timestamp_est.date() # Get date object for sorting later if needed
        else:
            est_str = 'N/A'
            month_key = "Unknown Month"
            record_date = None # Cannot determine date

        # Create dictionary for easier template access
        formatted_rec = {
            "id": rec.id,
            "timestamp_utc": rec.timestamp_utc, 
            "timestamp_display": est_str,      
            "site": rec.site,
            "event_type": rec.event_type,
            "user_name": rec.user_name,
            "visit_reason": rec.visit_reason, 
            "device_local_id": rec.device_local_id,
            "geo_lat": rec.geo_lat,
            "geo_lon": rec.geo_lon,
            "date_obj": record_date # Store date object if needed
        }
        formatted_records.append(formatted_rec)
        
        # --- Group by Month ---
        records_by_month[month_key].append(formatted_rec)
        
        # --- Group by Reason ---
        reason_key = rec.visit_reason if rec.visit_reason else "N/A" # Group None/empty as "N/A"
        records_by_reason[reason_key].append(formatted_rec)
        
    # Sort month keys (most recent first)
    sorted_months = sorted([m for m in records_by_month.keys() if m != "Unknown Month"], reverse=True)
    if "Unknown Month" in records_by_month:
        sorted_months.append("Unknown Month")
        
    # Sort reason keys (alphabetical, N/A last?)
    sorted_reasons = sorted([r for r in records_by_reason.keys() if r != "N/A"])
    if "N/A" in records_by_reason:
        sorted_reasons.append("N/A")
    # ------------------------------------

    return templates.TemplateResponse(
        "admin.html", 
        {
            "request": request, 
            "records_by_month": records_by_month, 
            "sorted_months": sorted_months,     
            "records_by_reason": records_by_reason, 
            "sorted_reasons": sorted_reasons,     
            "all_records": formatted_records,
            "datetime": datetime # <-- ADD THIS TO PASS DATETIME OBJECT
        }
    )
# -------------------------------------------------------------