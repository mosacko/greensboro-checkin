from fastapi.templating import Jinja2Templates
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse # Make sure RedirectResponse is imported
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, Dict
from datetime import datetime, timezone, date # Add date
from zoneinfo import ZoneInfo # Add ZoneInfo

from ..database import get_db
from ..models import Attendance
from ..settings import settings

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# --- Pydantic Schemas for the /finalize endpoint ---

class GeoPayload(BaseModel):
    lat: Optional[float] = None
    lon: Optional[float] = None

class FinalizePayload(BaseModel):
    token: str
    site: str
    deviceId: Optional[str] = None
    userAgent: Optional[str] = None
    geo: Optional[GeoPayload] = None
    nameText: Optional[str] = None
    signatureDataUrl: Optional[str] = None

# --- Routes ---

@router.get("/scan", response_class=HTMLResponse)
def scan(request: Request, db: Session = Depends(get_db), site: Optional[str] = None):
    
    user_name = None
    user_email = None # Need email for querying
    
    if settings.sso_required:
        user_session_data = request.session.get("user")
        if not user_session_data:
            # Not logged in, redirect to login (which stores intended site)
            return RedirectResponse(url=f"/login?site={site or settings.default_site}") 
        
        user_name = user_session_data.get("name") 
        user_email = user_session_data.get("email") # Get email too

        # --- CHECK IF ALREADY CHECKED IN TODAY (EST) ---
        if user_email: # Only check if we have an email
            try:
                est_zone = ZoneInfo("America/New_York")
                today_est_str = datetime.now(est_zone).strftime("%Y-%m-%d")
                
                existing_checkin = db.query(Attendance).filter(
                    Attendance.local_date == today_est_str,
                    Attendance.user_email == user_email, # <-- Check by email
                    Attendance.event_type == "check_in",
                    Attendance.is_valid == True
                ).first()

                if existing_checkin:
                    print(f"User {user_email} already checked in today ({today_est_str}).")
                    return RedirectResponse(url="/already-checked-in") 
                    
            except Exception as e:
                print(f"Error checking for existing check-in: {e}")
                # Proceed with check-in if error occurs during check
        else:
             print("WARNING: No user email found in session to check for duplicates.")
        # ----------------------------------------------------
    else: # If SSO is not required (MVP mode)
       # Handle non-SSO check-in if needed, or remove this logic
       pass # Currently does nothing if SSO disabled

    # --- PROCEED WITH CHECK-IN (IF NOT ALREADY CHECKED IN) ---
    site_code = site or settings.default_site
    if site_code not in settings.sites:
        site_code = settings.default_site

    now_utc = datetime.now(timezone.utc)
    try:
        est_zone = ZoneInfo("America/New_York")
        now_est = now_utc.astimezone(est_zone)
        local_date_str = now_est.strftime("%Y-%m-%d")
    except Exception:
        local_date_str = now_utc.strftime("%Y-%m-%d")

    print(f"Creating NEW Attendance record for {user_email or user_name} on {local_date_str} (EST)")
    rec = Attendance(
        site=site_code,
        event_type="check_in", 
        is_valid=True,
        source="qr_scan_loggedin", 
        timestamp_utc=now_utc,
        local_date=local_date_str,
        user_name=user_name,
        user_email=user_email # <-- Save the email
    )
    db.add(rec)
    try:
        db.commit()
        return RedirectResponse(url="/checkin-success")
    except Exception as e:
        db.rollback()
        print(f"Error committing new check-in via /scan: {e}")
        return PlainTextResponse("Check-in failed.", status_code=500)