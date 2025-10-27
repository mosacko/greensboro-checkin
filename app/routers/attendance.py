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
    user_email = None

    if settings.sso_required:
        user_session_data = request.session.get("user")
        if not user_session_data:
            # Store intended site before redirecting to login
            request.session["intended_site"] = site or settings.default_site
            return RedirectResponse(url="/login")

        user_name = user_session_data.get("name")
        user_email = user_session_data.get("email")

    site_code = site or settings.default_site
    if site_code not in settings.sites:
        site_code = settings.default_site

    # --- RESTORE: Create a provisional record ---
    now_utc = datetime.now(timezone.utc)
    try:
        est_zone = ZoneInfo("America/New_York")
        now_est = now_utc.astimezone(est_zone)
        local_date_str = now_est.strftime("%Y-%m-%d")
    except Exception:
        local_date_str = now_utc.strftime("%Y-%m-%d")

    # Remove previous check for existing checkin here, it should happen in /finalize if needed

    rec = Attendance(
        site=site_code,
        event_type="check_in",
        is_valid=True, # Mark as provisional? Could add a status field later.
        source="qr_scan_provisional",
        timestamp_utc=now_utc,
        local_date=local_date_str,
        user_name=user_name,
        user_email=user_email
    )
    db.add(rec)
    db.commit()
    db.refresh(rec) # Get the generated ID
    # --- END RESTORE ---

    token = str(rec.id) # Use the DB ID as the token

    # Render the scan page for the user to submit
    return templates.TemplateResponse(
        "scan.html",
        {"request": request, "token": token, "site": site_code}
    )

@router.post("/finalize")
async def finalize(payload: FinalizePayload, request: Request, db: Session = Depends(get_db)): # Add request parameter
    try:
        pk = int(payload.token)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid token")

    rec = db.get(Attendance, pk)
    if not rec:
        raise HTTPException(status_code=404, detail="Token not found")

    # --- ADD DUPLICATE CHECK HERE ---
    user_email = request.session.get("user", {}).get("email") # Get email from session

    if user_email and rec.event_type == "check_in": # Only check for check-ins if we have email
        try:
            est_zone = ZoneInfo("America/New_York")
            today_est_str = datetime.now(est_zone).strftime("%Y-%m-%d")

            # Check for OTHER finalized check-ins today by this user
            existing_finalized_checkin = db.query(Attendance).filter(
                Attendance.id != pk, # Exclude the current provisional record
                Attendance.local_date == today_est_str,
                Attendance.user_email == user_email,
                Attendance.event_type == "check_in",
                Attendance.is_valid == True,
                # Check if the source indicates it was finalized
                Attendance.source == "qr_scan_finalized" 
            ).first()

            if existing_finalized_checkin:
                print(f"User {user_email} trying to finalize, but already checked in today ({today_est_str}). Invalidating provisional record.")
                # Optionally invalidate the provisional record instead of finalizing
                rec.is_valid = False 
                rec.notes = "Attempted duplicate check-in."
                rec.source = "qr_scan_duplicate"
                db.add(rec)
                db.commit()
                # Redirect to already checked in page
                # You'll need RedirectResponse imported: from fastapi.responses import RedirectResponse
                # return RedirectResponse(url="/already-checked-in", status_code=303) 
                # OR return an error/message
                return {"ok": False, "message": "Already checked in today."}

        except Exception as e:
            print(f"Error checking for existing finalized check-in: {e}")
            # Decide how to handle - maybe allow finalize anyway? For now, proceed.
    # --------------------------------

    # --- Finalize the record ---
    print(f"Finalizing check-in for {rec.user_email or rec.user_name}, ID: {pk}")
    rec.device_local_id = payload.deviceId or rec.device_local_id
    rec.user_agent = payload.userAgent
    rec.source = "qr_scan_finalized" 

    # --- ADD THIS LINE ---
    rec.visit_reason = payload.visitReason # Assign the reason from the payload
    # ---------------------

    if payload.geo:
        rec.geo_lat = payload.geo.lat
        rec.geo_lon = payload.geo.lon
    
    if rec.is_valid is None:
         rec.is_valid = True

    db.add(rec)
    db.commit()

    return {"ok": True, "token": payload.token}