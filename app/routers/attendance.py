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
def scan(request: Request, site: Optional[str] = None):
    # --- SIMPLIFIED /scan ---
    # It only checks SSO and redirects if needed. 
    # The actual check-in happens in /auth/callback.
    if settings.sso_required:
        user = request.session.get("user")
        if not user:
            # If not logged in, redirect to login (which stores site & goes to Azure)
            # Pass site along in case login needs it directly (though session is preferred)
            return RedirectResponse(url=f"/login?site={site or settings.default_site}") 
    
    # If already logged in, maybe show a message or redirect home?
    # Or redirect straight to success? Let's redirect home for now.
    # Alternatively, you could just show the success page directly if logged in.
    print("User already logged in, redirecting home from /scan")
    return RedirectResponse(url="/") 
    # --- END SIMPLIFIED ---