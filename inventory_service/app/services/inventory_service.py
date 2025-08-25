from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from app.models.inventory_item import InventoryItem
from app.schemas.inventory_item import (
    InventoryItemCreate, 
    InventoryItemUpdate, 
    InventoryStatusResponse
)
from app.core.config import settings
from .dapr_service import DaprService

class InventoryService:
    def __init__(self, db: Session):
        self.db = db
        self.dapr_service = DaprService()
    
    def create_item(self, item_data: InventoryItemCreate) -> InventoryItem:
        """Crear un nuevo item en el inventario"""
        db_item = InventoryItem(**item_data.dict())
        self.db.add(db_item)
        self.db.commit()
        self.db.refresh(db_item)
        return db_item
    
    def get_item_by_product_id(self, product_id: str) -> Optional[InventoryItem]:
        """Obtener item por product_id"""
        return self.db.query(InventoryItem).filter(
            InventoryItem.product_id == product_id
        ).first()
    
    def get_all_items(self, skip: int = 0, limit: int = 100) -> List[InventoryItem]:
        """Obtener todos los items con paginación"""
        return self.db.query(InventoryItem).offset(skip).limit(limit).all()
    
    def update_item_quantity(self, product_id: str, quantity_change: int) -> InventoryItem:
        """Actualizar cantidad de un item y notificar cambios"""
        db_item = self.get_item_by_product_id(product_id)
        if not db_item:
            raise ValueError(f"Producto {product_id} no encontrado")
        
        old_quantity = db_item.quantity
        new_quantity = old_quantity + quantity_change
        
        if new_quantity < 0:
            raise ValueError("Cantidad insuficiente en inventario")
        
        db_item.quantity = new_quantity
        db_item.available = new_quantity > 0
        db_item.updated_at = datetime.utcnow()
        
        self.db.commit()
        self.db.refresh(db_item)
        
        # Notificar cambio vía Dapr
        self.dapr_service.publish_inventory_change(
            product_id=product_id,
            old_quantity=old_quantity,
            new_quantity=new_quantity,
            available=db_item.available
        )
        
        return db_item
    
    def get_inventory_status(self, product_id: str) -> InventoryStatusResponse:
        """Obtener estado del inventario para un producto"""
        item = self.get_item_by_product_id(product_id)
        if not item:
            raise ValueError(f"Producto {product_id} no encontrado")
        
        if item.quantity == 0:
            status = "out_of_stock"
        elif item.quantity <= settings.low_stock_threshold:
            status = "low_stock"
        else:
            status = "available"
        
        return InventoryStatusResponse(
            product_id=item.product_id,
            available=item.available,
            quantity=item.quantity,
            status=status,
            last_updated=item.updated_at or item.created_at
        )