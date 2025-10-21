from fastapi.templating import Jinja2Templates
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse # Make sure RedirectResponse is imported
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, Dict
from datetime import datetime, timezone

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
    
    user_name = None # Default name to None

    # --- ADD SSO CHECK ---
    if settings.sso_required:
        user_session_data = request.session.get("user") # Read session data
        if not user_session_data:
            return RedirectResponse(url="/login") 
        
        # Get user name from session
        user_name = user_session_data.get("name") 
            
    site_code = site or settings.default_site
    if site_code not in settings.sites:
        site_code = settings.default_site

    # Create a provisional record. The database will assign the integer PK.
    rec = Attendance(
        site=site_code,
        event_type="check_in",  # Using the new string value
        is_valid=True,
        source="qr",
        timestamp_utc=datetime.now(timezone.utc),
        local_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        user_name=user_name
    )
    db.add(rec)

    # --- ADD LOGGING RIGHT BEFORE COMMIT ---
    print(f"--- Just before commit in /scan ---")
    print(f"Object to be saved: ID={rec.id}, Site={rec.site}, Name={rec.user_name}")
    # ----------------------------------------

    db.commit()
    db.refresh(rec)

    # Use the new integer ID as the token
    token = str(rec.id) 

    return templates.TemplateResponse(
        "scan.html",
        {"request": request, "token": token, "site": site_code}
    )

@router.post("/finalize")
async def finalize(payload: FinalizePayload, db: Session = Depends(get_db)):
    try:
        pk = int(payload.token)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid token")

    rec = db.get(Attendance, pk)
    if not rec:
        raise HTTPException(status_code=404, detail="Token not found")

    # Update the record with data from the form
    rec.device_local_id = payload.deviceId or rec.device_local_id
    rec.user_agent = payload.userAgent or rec.user_agent

    if payload.geo:
        rec.geo_lat = payload.geo.lat
        rec.geo_lon = payload.geo.lon
    
    db.add(rec)
    db.commit()
    
    return {"ok": True, "token": payload.token}