# app/routers/metrics.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, Date # Import necessary SQLAlchemy functions
from datetime import datetime, timedelta, timezone # Import date/time functions
import re # Import regular expression module for date validation

from ..database import get_db
from ..models import Attendance

router = APIRouter(
    prefix="/api/metrics", # Add a prefix for all routes in this file
    tags=["metrics"]        # Tag for API documentation
)

@router.get("/daily_checkins_last_week")
def get_daily_checkins_last_week(db: Session = Depends(get_db)):
    """
    Counts the number of valid check-ins per day for the past 7 days (including today).
    Returns data formatted for Chart.js.
    """
    today = datetime.now(timezone.utc).date()
    seven_days_ago = today - timedelta(days=6) # Calculate start date

    # Query the database: Count Attendance records, group by date
    results = (
        db.query(
            cast(Attendance.timestamp_utc, Date).label("checkin_date"), # Extract date part
            func.count(Attendance.id).label("count")                 # Count records
        )
        .filter(
            cast(Attendance.timestamp_utc, Date) >= seven_days_ago, # Filter by date range
            cast(Attendance.timestamp_utc, Date) <= today,
            Attendance.event_type == "check_in",                    # Only count check-ins
            Attendance.is_valid == True                             # Only count valid entries
        )
        .group_by("checkin_date")                                  # Group results by date
        .order_by("checkin_date")                                  # Order by date
        .all()
    )

    # Format data for Chart.js (labels = dates, data = counts)
    # Ensure all days in the range are present, even if count is 0
    date_map = {r.checkin_date: r.count for r in results}
    labels = [(seven_days_ago + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    data = [date_map.get(datetime.strptime(label, "%Y-%m-%d").date(), 0) for label in labels]
    
    return {"labels": labels, "data": data}

# --- ADD NEW ENDPOINT ---
@router.get("/attendance/{date_str}") 
async def get_attendance_for_date(date_str: str, db: Session = Depends(get_db)):
    """
    Fetches all valid check-in records for a specific date (YYYY-MM-DD).
    """
    # Basic validation for the date string format
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    try:
        # Attempt to parse the date to ensure it's valid, though we query by string
        requested_date = date.fromisoformat(date_str) 
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date value.")

    # Query the database for records matching the local_date string
    records = db.query(Attendance).filter(
        Attendance.local_date == date_str,
        Attendance.event_type == "check_in",
        Attendance.is_valid == True
    ).order_by(Attendance.timestamp_utc.asc()).all() # Order by time ascending for the panel display

    # (Optional) Convert SQLAlchemy objects to dictionaries for JSON response
    # This avoids potential issues with lazy loading or complex objects
    results = [
        {
            "id": rec.id,
            "timestamp_utc": rec.timestamp_utc,
            "local_date": rec.local_date,
            "site": rec.site,
            "event_type": rec.event_type,
            "user_name": rec.user_name,
            "user_email": rec.user_email,
            "visit_reason": rec.visit_reason,
            "device_local_id": rec.device_local_id,
            "geo_lat": rec.geo_lat,
            "geo_lon": rec.geo_lon
        } 
        for rec in records
    ]

    return results