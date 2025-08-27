from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from enum import Enum

class InvoiceStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class InvoiceCreate(BaseModel):
    product_id: str
    quantity: int
    customer_email: Optional[str] = None

class InvoiceResponse(BaseModel):
    id: int
    invoice_number: str
    product_id: str
    quantity: int
    unit_price: Optional[float]
    total_amount: Optional[float]
    status: str
    customer_email: Optional[str]
    created_at: datetime
    updated_at: datetime
    notes: Optional[str]

    class Config:
        from_attributes = True