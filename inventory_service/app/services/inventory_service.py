from sqlalchemy.orm import Session
from app.models.inventory_item import InventoryItem
from app.schemas.inventory_item import (
    InventoryItemCreate,
    InventoryItemUpdate
)
# Comentar o eliminar esta línea problemática:
# from .dapr_service import DaprService

class InventoryService:
    def __init__(self, db: Session):
        self.db = db

    def get_all_items(self):
        """Obtener todos los items del inventario"""
        return self.db.query(InventoryItem).all()

    def get_item_by_product_id(self, product_id: str):
        """Obtener un item por su product_id"""
        return self.db.query(InventoryItem).filter(
            InventoryItem.product_id == product_id
        ).first()

    def create_item(self, item_data: InventoryItemCreate):
        """Crear un nuevo item en el inventario"""
        db_item = InventoryItem(**item_data.dict())
        self.db.add(db_item)
        self.db.commit()
        self.db.refresh(db_item)
        return db_item

    def update_item_quantity(self, product_id: str, quantity_change: int):
        """Actualizar la cantidad de un item (puede ser positivo o negativo)"""
        item = self.get_item_by_product_id(product_id)
        if not item:
            raise ValueError(f"Product {product_id} not found")
        
        new_quantity = item.quantity + quantity_change
        if new_quantity < 0:
            raise ValueError(f"Insufficient inventory. Available: {item.quantity}, Requested change: {quantity_change}")
        
        item.quantity = new_quantity
        self.db.commit()
        self.db.refresh(item)
        return item

    def update_item(self, product_id: str, item_data: InventoryItemUpdate):
        """Actualizar un item del inventario"""
        item = self.get_item_by_product_id(product_id)
        if not item:
            raise ValueError(f"Product {product_id} not found")
        
        update_data = item_data.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(item, field, value)
        
        self.db.commit()
        self.db.refresh(item)
        return item

    def delete_item(self, product_id: str):
        """Eliminar un item del inventario"""
        item = self.get_item_by_product_id(product_id)
        if not item:
            raise ValueError(f"Product {product_id} not found")
        
        self.db.delete(item)
        self.db.commit()
        return True