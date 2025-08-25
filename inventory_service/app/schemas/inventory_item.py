from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class InventoryItemBase(BaseModel):
    product_id: str = Field(..., description="ID único del producto")
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=500)
    quantity: int = Field(..., ge=0)
    price: float = Field(..., gt=0)
    available: bool = True
    category_id: Optional[int] = None

class InventoryItemCreate(InventoryItemBase):
    pass

class InventoryItemUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=500)
    quantity: Optional[int] = Field(None, ge=0)
    price: Optional[float] = Field(None, gt=0)
    available: Optional[bool] = None
    category_id: Optional[int] = None

class InventoryItemResponse(InventoryItemBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class InventoryStatusResponse(BaseModel):
    product_id: str
    available: bool
    quantity: int
    status: str  # "available", "low_stock", "out_of_stock"
    last_updated: datetime