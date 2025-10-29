# seed_db.py
import os
import random
from datetime import datetime, timedelta, timezone, date
from zoneinfo import ZoneInfo
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from faker import Faker # We'll need to install this library

# Import your models and database setup
# Adjust path if your structure is different
from app.database import Base, engine 
from app.models import Attendance, Employee 

# --- Configuration ---
NUM_EMPLOYEES = 20
NUM_DAYS = 90
CHECK_IN_RATE = 0.75 # 75%
SITE_CODE = "greenville" 
# --- ADD VISIT REASONS ---
VISIT_REASONS = ["Work", "Visit", "Client Meeting", "Internal Meeting", "Other"]
# ---------------------

# Setup database connection
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
db = SessionLocal()

# Faker for random names/emails
fake = Faker()

# Timezone for date calculation
try:
    est_zone = ZoneInfo("America/New_York")
except Exception:
    print("Warning: Could not load EST timezone, using UTC for date generation.")
    est_zone = timezone.utc

print(f"Generating dummy data for {NUM_EMPLOYEES} employees over {NUM_DAYS} days...")

try:
    # Generate Employees (optional, if you also cleared employees table)
    employees_to_create = []
    employee_emails = set() # Ensure unique emails
    print("Generating employee data...")
    while len(employees_to_create) < NUM_EMPLOYEES:
         email = fake.unique.email()
         if email not in employee_emails:
              employees_to_create.append(Employee(email=email, display_name=fake.name()))
              employee_emails.add(email)

    # Fetch existing emails to avoid duplicates if employees table wasn't cleared
    existing_emails = {emp.email for emp in db.query(Employee.email).all()}
    new_employees = [emp for emp in employees_to_create if emp.email not in existing_emails]

    if new_employees:
         print(f"Adding {len(new_employees)} new employees to the database...")
         db.add_all(new_employees)
         db.commit()
    else:
         print("Using existing employees.")

    # Get all employees (new and existing) for attendance records
    all_employees = db.query(Employee).all()
    if len(all_employees) < NUM_EMPLOYEES:
         print(f"Warning: Only found {len(all_employees)} employees in DB.")

    # Generate Attendance Data
    attendance_records = []
    today = datetime.now(est_zone).date()

    print("Generating attendance data...")
    for i in range(NUM_DAYS):
        current_date = today - timedelta(days=i)
        # ... (Skip weekends if uncommented) ...
        current_date_str = current_date.strftime("%Y-%m-%d")

        for employee in all_employees:
            if random.random() < CHECK_IN_RATE:
                # ... (Generate random check-in time and timestamp_utc) ...
                checkin_hour = random.randint(8, 9)
                checkin_minute = random.randint(0, 59)
                checkin_second = random.randint(0, 59)
                timestamp_est = datetime(
                    current_date.year, current_date.month, current_date.day,
                    checkin_hour, checkin_minute, checkin_second,
                    tzinfo=est_zone
                )
                timestamp_utc = timestamp_est.astimezone(timezone.utc)

                # --- CHOOSE A RANDOM REASON ---
                chosen_reason = random.choice(VISIT_REASONS)
                # -----------------------------

                attendance_records.append(Attendance(
                    timestamp_utc=timestamp_utc,
                    local_date=current_date_str,
                    site=SITE_CODE,
                    event_type="check_in",
                    user_name=employee.display_name,
                    user_email=employee.email,
                    visit_reason=chosen_reason, # <-- ADD THE REASON HERE
                    source="dummy_data",
                    is_valid=True
                ))

    print(f"Adding {len(attendance_records)} attendance records to the database...")
    db.add_all(attendance_records)
    db.commit()
    print("Dummy data generation complete!")

except Exception as e:
    db.rollback()
    print(f"An error occurred: {e}")
finally:
    db.close()