# app/routers/metrics.py

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, Date # Import necessary SQLAlchemy functions
from datetime import datetime, timedelta, timezone # Import date/time functions

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