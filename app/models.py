from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Float, Boolean, Text, CheckConstraint
from .database import Base

class Employee(Base):
    __tablename__ = "employees"
    id = Column(Integer, primary_key=True)
    email = Column(String(320), unique=True, index=True, nullable=False)
    display_name = Column(String(200), nullable=False)
    status = Column(String(20), default="active", nullable=False)
    department = Column(String(100))
    external_tenant = Column(String(120))
    created_at_utc = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at_utc = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                            onupdate=lambda: datetime.now(timezone.utc), nullable=False)

class Attendance(Base):
    __tablename__ = "attendance"
    
    # Use a SQL string expression for the constraint
    __table_args__ = (
        CheckConstraint("event_type IN ('check_in', 'check_out')", name='chk_event_type'),
    )
    
    id = Column(Integer, primary_key=True)
    # ... (rest of your columns are fine) ...
    event_type = Column(String(20), nullable=False, index=True)
    timestamp_utc = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    local_date = Column(String(10))
    site = Column(String(64), nullable=False)
    
    # This is now a simple String, as you requested
    event_type = Column(String(20), nullable=False, index=True) 

    user_name = Column(String(200), nullable=True) # To store the name from SSO
    user_email = Column(String(320), nullable=True, index=True) # Add email, index for faster lookups
    
    source = Column(String(32), nullable=False, default="qr")
    user_agent = Column(Text)
    device_local_id = Column(String(64))
    geo_lat = Column(Float)
    geo_lon = Column(Float)
    signature_path = Column(String(256))
    is_valid = Column(Boolean, nullable=False, default=True)
    notes = Column(Text)
    updated_at_utc = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                            onupdate=lambda: datetime.now(timezone.utc), nullable=False)