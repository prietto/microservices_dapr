from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db import get_db
from app.services.inventory_service import InventoryService
from app.schemas.inventory_item import InventoryItemCreate
from app.models.inventory_item import InventoryItem
import httpx
import asyncio

api_router = APIRouter()

@api_router.get("/test")
def test_endpoint():
    return {"message": "Inventory API working!"}

@api_router.post("/items")
def create_item(item_data: InventoryItemCreate, db: Session = Depends(get_db)):
    """Crear un nuevo item en el inventario"""
    try:
        inventory_service = InventoryService(db)
        
        # Verificar si ya existe
        existing = inventory_service.get_item_by_product_id(item_data.product_id)
        if existing:
            raise HTTPException(status_code=400, detail="Product already exists")
        
        # Crear el item
        item = inventory_service.create_item(item_data)
        
        return {
            "message": "Item created successfully",
            "product_id": item.product_id,
            "name": item.name,
            "quantity": item.quantity,
            "price": item.price
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.put("/items/{product_id}")
def update_item(product_id: str, item_data: InventoryItemCreate, db: Session = Depends(get_db)):
    """Actualizar un item existente"""
    try:
        inventory_service = InventoryService(db)
        
        existing = inventory_service.get_item_by_product_id(product_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Product not found")
        
        # Actualizar los campos
        existing.name = item_data.name
        existing.description = item_data.description
        existing.quantity = item_data.quantity
        existing.price = item_data.price
        
        db.commit()
        db.refresh(existing)
        
        return {
            "message": "Item updated successfully",
            "product_id": existing.product_id,
            "name": existing.name,
            "quantity": existing.quantity,
            "price": existing.price
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/items/{product_id}")
def get_item(product_id: str, db: Session = Depends(get_db)):
    inventory_service = InventoryService(db)
    item = inventory_service.get_item_by_product_id(product_id)
    if item:
        return {
            "product_id": item.product_id,
            "name": item.name,
            "description": item.description,
            "quantity": item.quantity,
            "price": item.price
        }
    return {"error": "Item not found"}

@api_router.get("/items")
def list_items(db: Session = Depends(get_db)):
    """Listar todos los items del inventario"""
    inventory_service = InventoryService(db)
    items = inventory_service.get_all_items()
    return {
        "items": [
            {
                "product_id": item.product_id,
                "name": item.name,
                "description": item.description,
                "quantity": item.quantity,
                "price": item.price
            }
            for item in items
        ]
    }

@api_router.post("/seed")
def create_test_data(db: Session = Depends(get_db)):
    """Crear datos de prueba"""
    inventory_service = InventoryService(db)
    
    test_items = [
        InventoryItemCreate(
            product_id="LAPTOP001",
            name="Laptop Gaming",
            description="High-performance gaming laptop",
            quantity=5,
            price=1299.99
        ),
        InventoryItemCreate(
            product_id="MOUSE001", 
            name="Gaming Mouse",
            description="RGB gaming mouse",
            quantity=2,
            price=79.99
        ),
        InventoryItemCreate(
            product_id="KEYBOARD001",
            name="Mechanical Keyboard",
            description="RGB mechanical keyboard",
            quantity=0,
            price=149.99
        )
    ]
    
    created_items = []
    for item_data in test_items:
        try:
            existing = inventory_service.get_item_by_product_id(item_data.product_id)
            if not existing:
                inventory_service.create_item(item_data)
                created_items.append(item_data.product_id)
        except:
            pass
    
    return {
        "message": "Test data created",
        "created_items": created_items
    }

@api_router.get("/queue-status")
async def check_queue_status():
    """Verificar el estado de las colas de RabbitMQ"""
    try:
        # URL de la API de management de RabbitMQ
        rabbitmq_api = "http://localhost:15672/api"
        
        async with httpx.AsyncClient(
            auth=("guest", "guest"),
            timeout=5.0
        ) as client:
            # Obtener información de todas las colas
            response = await client.get(f"{rabbitmq_api}/queues")
            
            if response.status_code == 200:
                queues = response.json()
                
                # Filtrar colas relacionadas con nuestros topics
                relevant_queues = []
                for queue in queues:
                    queue_name = queue.get("name", "")
                    if any(topic in queue_name for topic in ["inventory-check", "inventory-response"]):
                        relevant_queues.append({
                            "name": queue_name,
                            "messages": queue.get("messages", 0),
                            "messages_ready": queue.get("messages_ready", 0),
                            "messages_unacknowledged": queue.get("messages_unacknowledged", 0),
                            "consumers": queue.get("consumers", 0),
                            "state": queue.get("state", "unknown")
                        })
                
                return {
                    "status": "success",
                    "queues": relevant_queues,
                    "total_pending_messages": sum(q["messages"] for q in relevant_queues)
                }
            else:
                return {
                    "status": "error",
                    "message": f"RabbitMQ API returned {response.status_code}"
                }
                
    except Exception as e:
        return {
            "status": "error",
            "message": f"Could not connect to RabbitMQ Management API: {str(e)}",
            "note": "Make sure RabbitMQ Management plugin is enabled"
        }

@api_router.get("/service-health")
async def service_health():
    """Verificar el estado del servicio y conexiones"""
    return {
        "service": "inventory-service",
        "status": "running",
        "database": "connected",
        "endpoints": {
            "check_queue": "/api/v1/queue-status",
            "items": "/api/v1/items",
            "seed_data": "/api/v1/seed"
        }
    }


@api_router.patch("/items/{product_id}/stock")
def update_stock(product_id: str, quantity: int, db: Session = Depends(get_db)):
    """Actualizar solo la cantidad de stock de un producto"""
    try:
        inventory_service = InventoryService(db)
        
        existing = inventory_service.get_item_by_product_id(product_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Product not found")
        
        # Solo actualizar la cantidad
        existing.quantity = quantity
        db.commit()
        db.refresh(existing)
        
        return {
            "message": "Stock updated successfully",
            "product_id": existing.product_id,
            "name": existing.name,
            "old_quantity": existing.quantity,
            "new_quantity": quantity,
            "price": existing.price
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

@api_router.post("/compensate-inventory")
async def compensate_inventory(event_data: dict, db: Session = Depends(get_db)):
    """Compensar inventario - restaurar stock reducido"""
    print(f"[INVENTORY] 🔄 Compensating inventory: {event_data}")
    
    # Extraer datos del evento
    data = event_data.get("data", event_data)
    product_id = data.get("product_id")
    quantity = data.get("quantity")
    invoice_id = data.get("invoice_id")
    reason = data.get("reason", "Saga compensation")
    
    try:
        inventory_service = InventoryService(db)
        
        # Verificar que el producto existe
        item = inventory_service.get_item_by_product_id(product_id)
        if not item:
            print(f"[INVENTORY] ❌ Product {product_id} not found for compensation")
            return {"success": False, "error": "Product not found"}
        
        # Restaurar stock (agregar de vuelta la cantidad)
        old_quantity = item.quantity
        inventory_service.update_item_quantity(product_id, quantity)  # Suma positiva
        new_quantity = old_quantity + quantity
        
        print(f"[INVENTORY] ✅ Compensated: Restored {quantity} units of {product_id}")
        print(f"[INVENTORY] Stock updated: {old_quantity} → {new_quantity}")
        
        # Opcional: Enviar confirmación de compensación
        compensation_response = {
            "invoice_id": invoice_id,
            "product_id": product_id,
            "quantity_restored": quantity,
            "current_stock": new_quantity,
            "compensation_successful": True,
            "reason": reason
        }
        
        # Publicar evento de compensación completada (opcional)
        dapr_url = "http://localhost:3500"
        pubsub_url = f"{dapr_url}/v1.0/publish/rabbitmq-pubsub/inventory-compensated"
        
        async with httpx.AsyncClient() as client:
            await client.post(pubsub_url, json=compensation_response)
        
        return {
            "success": True, 
            "message": f"Restored {quantity} units of {product_id}",
            "previous_stock": old_quantity,
            "current_stock": new_quantity
        }
        
    except Exception as e:
        print(f"[INVENTORY] ❌ Compensation failed: {e}")
        return {"success": False, "error": str(e)}