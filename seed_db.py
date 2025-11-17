import os
import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from faker import Faker 

from app.database import Base, engine 
from app.models import Attendance, Employee 

# --- Configuration ---
NUM_EMPLOYEES = 10       # 25 unique people
NUM_DAYS = 30            # Last 3 months
CHECK_IN_RATE = 0.5    # 65% chance they come in on a given day
SITE_CODE = "greenville" 

VISIT_REASONS = ["Work", "Visit", "Client Meeting", "Internal Meeting", "Other"]
BUSINESS_LINES = ["Transportation", "Buildings", "Environment", "Water", "Advisory", "Corporate/Admin"]
# ---------------------

# Setup database connection
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
db = SessionLocal()
fake = Faker()

try:
    est_zone = ZoneInfo("America/New_York")
except Exception:
    print("Warning: Could not load EST timezone, using UTC.")
    est_zone = timezone.utc

print(f"Generating data for {NUM_EMPLOYEES} employees over {NUM_DAYS} days...")

try:
    # 1. Generate Employees
    employees_to_create = []
    employee_emails = set()
    
    # Fetch existing emails to avoid duplicates
    existing_emails = {emp.email for emp in db.query(Employee.email).all()}
    
    while len(employees_to_create) + len(existing_emails) < NUM_EMPLOYEES:
         email = fake.unique.email()
         if email not in existing_emails and email not in employee_emails:
              employees_to_create.append(Employee(email=email, display_name=fake.name()))
              employee_emails.add(email)
    
    if employees_to_create:
         print(f"Adding {len(employees_to_create)} new employees...")
         db.add_all(employees_to_create)
         db.commit()
    
    all_employees = db.query(Employee).all()

    # 2. Generate Attendance
    attendance_records = []
    today = datetime.now(est_zone).date()
    
    print("Generating attendance records...")
    for i in range(NUM_DAYS):
        current_date = today - timedelta(days=i)
        
        # Skip weekends (Saturday=5, Sunday=6)
        if current_date.weekday() >= 5: 
            continue 

        current_date_str = current_date.strftime("%Y-%m-%d")

        for employee in all_employees:
            # Random chance to check in
            if random.random() < CHECK_IN_RATE:
                # Random time between 7:30 AM and 10:30 AM
                checkin_hour = random.randint(7, 10)
                checkin_minute = random.randint(0, 59)
                
                timestamp_est = datetime(
                    current_date.year, current_date.month, current_date.day,
                    checkin_hour, checkin_minute, 0,
                    tzinfo=est_zone
                )
                timestamp_utc = timestamp_est.astimezone(timezone.utc)

                attendance_records.append(Attendance(
                    timestamp_utc=timestamp_utc,
                    local_date=current_date_str,
                    site=SITE_CODE,
                    event_type="check_in",
                    user_name=employee.display_name,
                    user_email=employee.email,
                    visit_reason=random.choice(VISIT_REASONS),     # Random Reason
                    business_line=random.choice(BUSINESS_LINES),   # Random Business Line
                    device_local_id=fake.uuid4(),                  # Fake Device ID
                    source="dummy_data",
                    is_valid=True
                ))

    print(f"Adding {len(attendance_records)} attendance records...")
    
    # Add in chunks to avoid massive transactions
    chunk_size = 500
    for i in range(0, len(attendance_records), chunk_size):
        db.add_all(attendance_records[i:i + chunk_size])
        db.commit()
        print(f"Committed chunk {i//chunk_size + 1}...")

    print("Dummy data generation complete!")

except Exception as e:
    db.rollback()
    print(f"An error occurred: {e}")
finally:
    db.close()