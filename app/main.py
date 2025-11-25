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
#from authlib.integrations.starlette_client import OAuth
#from authlib.integrations.base_client.errors import OAuthError
#from .models import Employee # Import Employee model
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
#oauth = OAuth()
#oauth.register(
#    name="azure",
#    server_metadata_url=f"https://login.microsoftonline.com/{settings.oidc_tenant}/v2.0/.well-known/openid-configuration",
#    client_id=settings.oidc_client_id,
#    client_secret=settings.oidc_client_secret,
#    client_kwargs={"scope": "openid profile email offline_access"},
#)
# ------------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    user = request.session.get("user") # Pass user info to template
    return templates.TemplateResponse("home.html", {"request": request, "sites": settings.sites, "user": user})

app.include_router(attendance_router.router, prefix="", tags=["attendance"])
app.include_router(metrics_router.router, prefix="", tags=["metrics"]) # ADD THIS LINE

@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.post("/register")
def register_user(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    # 1. Check if user exists
    existing_user = db.query(Employee).filter(Employee.email == email).first()
    if existing_user:
        return templates.TemplateResponse("register.html", {
            "request": request, 
            "error": "Email already registered. Please login."
        })

    # 2. Create new user
    full_name = f"{first_name} {last_name}"
    hashed_pwd = get_password_hash(password)
    
    new_employee = Employee(
        email=email,
        display_name=full_name,
        password_hash=hashed_pwd,
        status="active"
    )
    db.add(new_employee)
    db.commit()

    # 3. Auto-login (set session)
    request.session["user"] = {"email": email, "name": full_name}
    
    # 4. Redirect to Scan
    return RedirectResponse(url="/scan", status_code=303)

# --- NEW LOGIN ROUTES ---

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    # 1. Find user
    user = db.query(Employee).filter(Employee.email == email).first()
    
    # 2. Verify password
    if not user or not user.password_hash or not verify_password(password, user.password_hash):
        return templates.TemplateResponse("login.html", {
            "request": request, 
            "error": "Invalid email or password"
        })

    # 3. Set Session
    request.session["user"] = {"email": user.email, "name": user.display_name}

    # 4. Redirect
    # If we stored an intended site in the session (from /scan redirection), use it
    intended_site = request.session.pop("intended_site", settings.default_site)
    return RedirectResponse(url=f"/scan?site={intended_site}", status_code=303)

@app.get("/checkin-success", response_class=HTMLResponse)
def checkin_success(request: Request):
    return templates.TemplateResponse("checkin_success.html", {"request": request})

@app.get("/logout")
@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)

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
    records_by_business_line = defaultdict(list)
    
    for rec in all_records_raw:
        # Format timestamp
        if rec.timestamp_utc:
            timestamp_est = rec.timestamp_utc.astimezone(est_zone)
            est_str = timestamp_est.strftime('%Y-%m-%d %H:%M:%S %Z') 
            # Format specifically for HTML datetime-local input (YYYY-MM-DDTHH:MM)
            iso_local_str = timestamp_est.strftime('%Y-%m-%dT%H:%M')
            month_key = timestamp_est.strftime('%Y-%m') # Key for month grouping (e.g., "2025-10")
            record_date = timestamp_est.date() # Get date object for sorting later if needed
        else:
            est_str = 'N/A'
            iso_local_str = '' # Empty string for input if None
            month_key = "Unknown Month"
            record_date = None # Cannot determine date

        # Create dictionary for easier template access
        formatted_rec = {
            "id": rec.id,
            "timestamp_utc": rec.timestamp_utc, 
            "timestamp_display": est_str,     
            "timestamp_iso_local": iso_local_str, 
            "site": rec.site,
            "event_type": rec.event_type,
            "user_name": rec.user_name,
            "visit_reason": rec.visit_reason, 
            "business_line": rec.business_line,
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

        # --- Group by Business Line ---
        business_line_key = rec.business_line if rec.business_line else "N/A"
        records_by_business_line[business_line_key].append(formatted_rec)
        # ----------------------------
        
    # Sort month keys (most recent first)
    sorted_months = sorted([m for m in records_by_month.keys() if m != "Unknown Month"], reverse=True)
    if "Unknown Month" in records_by_month:
        sorted_months.append("Unknown Month")
        
    # Sort reason keys (alphabetical, N/A last?)
    sorted_reasons = sorted([r for r in records_by_reason.keys() if r != "N/A"])
    if "N/A" in records_by_reason:
        sorted_reasons.append("N/A")
    # ------------------------------------

    # --- Sort Business Lines ---
    sorted_business_lines = sorted([bl for bl in records_by_business_line.keys() if bl != "N/A"])
    if "N/A" in records_by_business_line:
        sorted_business_lines.append("N/A")
    # ---------------------------

    return templates.TemplateResponse(
        "admin.html", 
        {
            "request": request, 
            "records_by_month": records_by_month, 
            "sorted_months": sorted_months,     
            "records_by_reason": records_by_reason, 
            "sorted_reasons": sorted_reasons,
            "records_by_business_line": records_by_business_line, # <-- PASS NEW DATA
            "sorted_business_lines": sorted_business_lines,      # <-- PASS NEW DATA     
            "all_records": formatted_records,
            "datetime": datetime # <-- ADD THIS TO PASS DATETIME OBJECT
        }
    )
# -------------------------------------------------------------

# --- Admin Actions (Add, Edit, Delete) ---

@app.post("/admin/add")
def admin_add_record(
    request: Request,
    user_name: str = Form(...),
    visit_reason: str = Form(...),
    business_line: str = Form(None),
    site: str = Form(...),
    custom_date: str = Form(...), # Expecting YYYY-MM-DDTHH:MM
    db: Session = Depends(get_db)
):
    if request.cookies.get("admin_auth") != "super_secret_token":
        return RedirectResponse(url="/admin/login", status_code=303)

    try:
        # Parse the datetime-local input
        dt_obj = datetime.strptime(custom_date, "%Y-%m-%dT%H:%M")
        # Convert local time input to UTC for storage
        # Assuming admin is entering EST time, we convert to UTC
        est_zone = ZoneInfo("America/New_York")
        dt_est = dt_obj.replace(tzinfo=est_zone)
        dt_utc = dt_est.astimezone(timezone.utc)
        
        new_rec = Attendance(
            user_name=user_name,
            visit_reason=visit_reason,
            business_line=business_line,
            site=site,
            timestamp_utc=dt_utc,
            local_date=dt_est.strftime("%Y-%m-%d"),
            event_type="check_in",
            source="admin_manual",
            is_valid=True
        )
        db.add(new_rec)
        db.commit()
    except Exception as e:
        print(f"Error adding record: {e}")
    
    return RedirectResponse(url="/admin", status_code=303)

@app.post("/admin/edit")
def admin_edit_record(
    request: Request,
    record_id: int = Form(...),
    user_name: str = Form(...),
    visit_reason: str = Form(...),
    business_line: str = Form(None),
    site: str = Form(...),
    custom_date: str = Form(...),
    db: Session = Depends(get_db)
):
    if request.cookies.get("admin_auth") != "super_secret_token":
        return RedirectResponse(url="/admin/login", status_code=303)

    rec = db.get(Attendance, record_id)
    if rec:
        rec.user_name = user_name
        rec.visit_reason = visit_reason
        rec.business_line = business_line
        rec.site = site

        # --- UPDATE TIMESTAMP ---
        try:
            # Parse the datetime-local input (YYYY-MM-DDTHH:MM)
            dt_obj = datetime.strptime(custom_date, "%Y-%m-%dT%H:%M")
            
            # Assume Admin is entering EST time, convert to UTC for storage
            try:
                est_zone = ZoneInfo("America/New_York")
            except:
                est_zone = timezone.utc
            
            dt_est = dt_obj.replace(tzinfo=est_zone)
            dt_utc = dt_est.astimezone(timezone.utc)
            
            rec.timestamp_utc = dt_utc
            rec.local_date = dt_est.strftime("%Y-%m-%d") # Update local_date too for grouping
        except ValueError:
            pass # Keep old date if format is wrong
        # ------------------------

        db.commit()
    
    return RedirectResponse(url="/admin", status_code=303)

@app.post("/admin/delete")
def admin_delete_record(
    request: Request,
    record_id: int = Form(...),
    db: Session = Depends(get_db)
):
    if request.cookies.get("admin_auth") != "super_secret_token":
        return RedirectResponse(url="/admin/login", status_code=303)

    rec = db.get(Attendance, record_id)
    if rec:
        db.delete(rec)
        db.commit()
    
    return RedirectResponse(url="/admin", status_code=303)
