from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models import Base
from app.db import engine, get_db
from app.api.v1.api import api_router
from app.services.inventory_service import InventoryService
import httpx
import asyncio

Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.project_name)
app.include_router(api_router, prefix=settings.api_v1_str)

@app.get("/")
def read_root():
    return {"message": "Inventory Service API"}

@app.get("/health")
def health():
    return {"status": "healthy"}

# Suscripciones Dapr
@app.get("/dapr/subscribe")
def subscribe():
    return [
        {
            "pubsubname": "rabbitmq-pubsub",
            "topic": "inventory-check", 
            "route": "/inventory-check"
        },
        {
            "pubsubname": "rabbitmq-pubsub",
            "topic": "compensate-inventory",
            "route": "/compensate-inventory"
        }
    ]

# Manejar solicitudes de compensación
@app.post("/compensate-inventory")
async def handle_compensate_inventory(event_data: dict, db: Session = Depends(get_db)):
    """Manejar eventos de compensación de inventario"""
    print(f"[INVENTORY] COMPENSATION: Received compensation request: {event_data}")
    
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
            print(f"[INVENTORY] ERROR: Product {product_id} not found for compensation")
            return {"success": False, "error": "Product not found"}
        
        # Restaurar stock (agregar de vuelta la cantidad)
        old_quantity = item.quantity
        inventory_service.update_item_quantity(product_id, quantity)  # Suma positiva
        
        # Obtener nueva cantidad después de la actualización
        updated_item = inventory_service.get_item_by_product_id(product_id)
        new_quantity = updated_item.quantity
        
        print(f"[INVENTORY] SUCCESS: Compensated: Restored {quantity} units of {product_id}")
        print(f"[INVENTORY] Stock updated: {old_quantity} -> {new_quantity}")
        
        # Enviar confirmación de compensación
        compensation_response = {
            "invoice_id": invoice_id,
            "product_id": product_id,
            "quantity_restored": quantity,
            "current_stock": new_quantity,
            "compensation_successful": True,
            "reason": reason
        }
        
        # Publicar evento de compensación completada
        dapr_url = f"http://localhost:{settings.dapr_http_port}"
        pubsub_url = f"{dapr_url}/v1.0/publish/rabbitmq-pubsub/inventory-compensated"
        
        async with httpx.AsyncClient() as client:
            response = await client.post(pubsub_url, json=compensation_response)
            
        if response.status_code == 204:
            print(f"[INVENTORY] SUCCESS: Compensation confirmation sent for invoice {invoice_id}")
        else:
            print(f"[INVENTORY] WARNING: Failed to send compensation confirmation: {response.status_code}")
        
        return {
            "success": True, 
            "message": f"Restored {quantity} units of {product_id}",
            "previous_stock": old_quantity,
            "current_stock": new_quantity
        }
        
    except Exception as e:
        print(f"[INVENTORY] ERROR: Compensation failed: {e}")
        
        # Enviar confirmación de fallo
        compensation_response = {
            "invoice_id": invoice_id,
            "product_id": product_id,
            "compensation_successful": False,
            "error": str(e)
        }
        
        try:
            dapr_url = f"http://localhost:{settings.dapr_http_port}"
            pubsub_url = f"{dapr_url}/v1.0/publish/rabbitmq-pubsub/inventory-compensated"
            
            async with httpx.AsyncClient() as client:
                await client.post(pubsub_url, json=compensation_response)
        except:
            pass
            
        return {"success": False, "error": str(e)}

# Manejar solicitudes de verificación de inventario
@app.post("/inventory-check")
async def handle_inventory_check(event_data: dict, db: Session = Depends(get_db)):
    print(f"[INVENTORY] Received check request: {event_data}")
    
    # DELAY PROLONGADO para simular procesamiento lento
    print(f"[INVENTORY] Processing... (simulating slow operation)")
    await asyncio.sleep(10)  # Reducir a 10 segundos para testing más rápido

    # Extraer data del evento (Dapr CloudEvents)
    data = event_data.get("data", event_data)
    invoice_id = data.get("invoice_id")
    product_id = data.get("product_id")
    quantity = data.get("quantity", 1)
    
    try:
        # Verificar inventario
        inventory_service = InventoryService(db)
        item = inventory_service.get_item_by_product_id(product_id)
        
        # Preparar respuesta
        if item and item.quantity >= quantity:
            available = True
            # Reducir inventario si está disponible
            inventory_service.update_item_quantity(product_id, -quantity)
            remaining = item.quantity - quantity
            message = f"Inventory available. Reduced {quantity} units."
            unit_price = item.price
        else:
            available = False
            remaining = item.quantity if item else 0
            message = f"Insufficient inventory. Available: {remaining}, Needed: {quantity}"
            unit_price = item.price if item else 0.0
        
        # Enviar respuesta con información de la factura
        response_data = {
            "invoice_id": invoice_id,
            "product_id": product_id,
            "quantity_requested": quantity,
            "available": available,
            "remaining_stock": remaining,
            "unit_price": unit_price,
            "message": message
        }
        
        dapr_url = f"http://localhost:{settings.dapr_http_port}"
        pubsub_url = f"{dapr_url}/v1.0/publish/rabbitmq-pubsub/inventory-response"
        
        async with httpx.AsyncClient() as client:
            response = await client.post(pubsub_url, json=response_data)
        
        print(f"[INVENTORY] Response sent for invoice {invoice_id}: {response_data}")
        
    except Exception as e:
        print(f"[INVENTORY] Error: {e}")
        
    return {"success": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.app_port)