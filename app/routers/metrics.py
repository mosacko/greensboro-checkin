# app/routers/metrics.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, extract # Import necessary SQLAlchemy functions
from datetime import datetime, timedelta, timezone, date # Import date/time functions
import re # Import regular expression module for date validation

from ..database import get_db
from ..models import Attendance

from collections import defaultdict

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
            cast(Attendance.timestamp_utc, date).label("checkin_date"), # Extract date part
            func.count(Attendance.id).label("count")                 # Count records
        )
        .filter(
            cast(Attendance.timestamp_utc, date) >= seven_days_ago, # Filter by date range
            cast(Attendance.timestamp_utc, date) <= today,
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

@router.get("/monthly_summary/{year_month}")
async def get_monthly_summary(year_month: str, db: Session = Depends(get_db)):
    """
    Calculates total check-ins and breakdown by reason for a given month (YYYY-MM).
    """
    # Validate format YYYY-MM
    if not re.match(r"^\d{4}-\d{2}$", year_month):
        raise HTTPException(status_code=400, detail="Invalid month format. Use YYYY-MM.")

    try:
        year, month = map(int, year_month.split('-'))
        # Basic validation for month value
        if not (1 <= month <= 12):
             raise ValueError("Month out of range")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid year or month value.")

    # Query for total count and reason breakdown for the given month
    # We filter using date functions directly in the query
    # Query for records in the given month
    records_in_month = db.query(
            Attendance.visit_reason,
            Attendance.business_line # Also query business_line
        ).filter(
            extract('year', Attendance.timestamp_utc) == year,
            extract('month', Attendance.timestamp_utc) == month,
            Attendance.event_type == "check_in",
            Attendance.is_valid == True
        ).all() 

    total_checkins = len(records_in_month)
    # --- Calculate Breakdowns ---
    reason_counts = defaultdict(int)
    business_line_counts = defaultdict(int)
    
    for record in records_in_month:
        reason_key = record.visit_reason if record.visit_reason else "N/A"
        business_line_key = record.business_line if record.business_line else "N/A"
        reason_counts[reason_key] += 1
        business_line_counts[business_line_key] += 1
    # ---------------------------

    # --- Format Breakdowns with Percentages ---
    def format_breakdown(counts_dict, total):
        formatted = {}
        if total > 0:
            for key, count in counts_dict.items():
                percent = round((count / total) * 100, 1)
                formatted[key] = f"{count} ({percent}%)"
        else:
            for key, count in counts_dict.items():
                 formatted[key] = f"{count} (0.0%)"
        return formatted

    reason_breakdown_percent = format_breakdown(reason_counts, total_checkins)
    business_line_breakdown_percent = format_breakdown(business_line_counts, total_checkins) # Format business line
    # ----------------------------------------

    return {
        "month": year_month,
        "total_checkins": total_checkins,
        "reason_breakdown": reason_breakdown_percent,
        "business_line_breakdown": business_line_breakdown_percent # <-- RETURN NEW DATA
    }