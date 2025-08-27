from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .base import Base

class Category(Base):
    __tablename__ = "categories"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(String(300))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relación con InventoryItem
    items = relationship("InventoryItem", back_populates="category")
    
    def __repr__(self):
        return f"<Category(name='{self.name}')>"