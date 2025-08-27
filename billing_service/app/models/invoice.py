from sqlalchemy import Column, Integer, String, Float, DateTime, Text
from datetime import datetime
import enum
# Importar Base desde db.py
from app.db import Base

class InvoiceStatus(enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    PAYMENT_PROCESSING = "payment_processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class Invoice(Base):
    __tablename__ = "invoices"
    
    id = Column(Integer, primary_key=True, index=True)
    invoice_number = Column(String(50), unique=True, index=True)
    product_id = Column(String(50), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=True)
    total_amount = Column(Float, nullable=True)
    status = Column(String(20), default=InvoiceStatus.PENDING.value)
    customer_email = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    notes = Column(Text, nullable=True)