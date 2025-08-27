from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional
from enum import Enum

Base = declarative_base()

class CustomerStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING_DELETION = "pending_deletion"
    DELETED = "deleted"

class Customer(Base):
    __tablename__ = "customers"
    
    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=True)
    address = Column(Text, nullable=True)
    city = Column(String(100), nullable=True)
    country = Column(String(100), nullable=True)
    status = Column(String(20), default=CustomerStatus.ACTIVE)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    deletion_requested_at = Column(DateTime(timezone=True), nullable=True)
    deletion_blocked_by = Column(Text, nullable=True)  # JSON de servicios que bloquean

    deletion_timeout_at = Column(DateTime(timezone=True), nullable=True)  # ← NUEVO
    deletion_responses = Column(Text, nullable=True)  # JSON de respuestas recibidas
    deletion_completed = Column(Boolean, default=False)  # ← NUEVO

# Pydantic Models
class CustomerBase(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None

class CustomerCreate(CustomerBase):
    pass

class CustomerUpdate(BaseModel):
    email: Optional[EmailStr] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None

class CustomerResponse(CustomerBase):
    id: int
    customer_id: str
    status: CustomerStatus
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class DeletionValidationResponse(BaseModel):
    service: str
    customer_id: str
    can_delete: bool
    blocking_reason: Optional[str] = None
    blocking_details: Optional[dict] = None
    checked_at: datetime