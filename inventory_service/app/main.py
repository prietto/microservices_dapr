from wsgiref import headers
from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models import Base
from app.db import engine, get_db
from app.api.v1.api import api_router
from app.services.inventory_service import InventoryService
import httpx
import asyncio
from datetime import datetime

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
        },

        {
            "pubsubname": "rabbitmq-pubsub",
            "topic": "customer.deletion.request",
            "route": "/customer-deletion-request"
        }
    ]




@app.post("/customer-deletion-request")
async def handle_customer_deletion_request(event_data: dict, db: Session = Depends(get_db)):
    """Validar si se puede eliminar cliente desde perspectiva de inventario"""
    try:
        print(f"[INVENTORY] Received customer deletion request: {event_data}")
        
        data = event_data.get("data", event_data)
        customer_id = data.get("customer_id")
        
        if not customer_id:
            print(f"[INVENTORY] No customer_id in deletion request")
            return {"success": False, "error": "No customer_id"}
        
        print(f"[INVENTORY] Validating customer deletion for {customer_id}")
        
        # En inventory service, normalmente se puede eliminar cliente
        # a menos que tenga items reservados o personalizados
        can_delete = True
        blocking_reason = None
        
        # Ejemplo de validación (personalizar según tu lógica):
        # item_service = ItemService(db)
        # reserved_items = item_service.get_reserved_items_by_customer(customer_id)
        # if reserved_items:
        #     can_delete = False
        #     blocking_reason = f"Customer has {len(reserved_items)} reserved items"
        
        if can_delete:
            print(f"[INVENTORY] Customer deletion APPROVED: No inventory restrictions")
        else:
            print(f"[INVENTORY] Customer deletion BLOCKED: {blocking_reason}")
        
        # Responder al Account Service
        response_data = {
            "customer_id": customer_id,
            "service_name": "inventory-service",
            "can_delete": can_delete,
            "blocking_reason": blocking_reason,
            "validated_at": datetime.utcnow().isoformat()
        }
        
        # Enviar respuesta via Dapr PubSub
        await send_deletion_response(response_data)
        
        return {"success": True}
        
    except Exception as e:
        print(f"[INVENTORY] Error validating customer deletion: {e}")
        import traceback
        print(f"[INVENTORY] Full traceback: {traceback.format_exc()}")
        return {"success": False, "error": str(e)}




async def send_deletion_response(response_data: dict):
    """Enviar respuesta de validación de eliminación al Account Service"""
    try:
        dapr_url = f"http://localhost:{settings.dapr_http_port}"
        pubsub_url = f"{dapr_url}/v1.0/publish/rabbitmq-pubsub/customer.deletion.response"
        
        headers = {
            "Content-Type": "application/json",
            "dapr-api-token": settings.dapr_api_token
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(pubsub_url, json=response_data, headers=headers)
            
        if response.status_code == 204:
            print(f"[INVENTORY] Deletion validation response sent successfully")
        else:
            print(f"[INVENTORY] Failed to send deletion response: {response.status_code}")
            
    except Exception as e:
        print(f"[INVENTORY] Error sending deletion response: {e}")


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

        headers = {
            "Content-Type": "application/json",
            "dapr-api-token": settings.dapr_api_token
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(pubsub_url, json=compensation_response, headers=headers)

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

            headers = {
                "Content-Type": "application/json",
                "dapr-api-token": settings.dapr_api_token
            }

            async with httpx.AsyncClient() as client:
                await client.post(pubsub_url, json=compensation_response, headers=headers)
        except:
            pass
            
        return {"success": False, "error": str(e)}


@app.post("/inventory-check")
async def handle_inventory_check(event_data: dict, db: Session = Depends(get_db)):
    
    print(f"[INVENTORY] Received check request: {event_data}")
    
    try:
        # ARREGLO MEJORADO: Extraer los datos correctamente del Cloud Event
        data = {}
        
        # Caso 1: Event data tiene campo 'data'
        if isinstance(event_data, dict) and 'data' in event_data:
            if isinstance(event_data['data'], str):
                try:
                    import json
                    data = json.loads(event_data['data']) if event_data['data'].strip() else {}
                except json.JSONDecodeError:
                    print(f"[INVENTORY] Warning: Could not parse JSON from data: {event_data['data']}")
                    data = {}
            elif isinstance(event_data['data'], dict):
                data = event_data['data']
            else:
                print(f"[INVENTORY] Warning: Unexpected data type: {type(event_data['data'])}")
                data = {}
        
        # Caso 2: Event data es directamente los datos
        elif isinstance(event_data, dict):
            # Verificar si tiene campos que esperamos
            if any(key in event_data for key in ['invoice_id', 'product_id', 'quantity']):
                data = event_data
            else:
                print(f"[INVENTORY] Warning: No expected fields found in event_data")
                data = {}
        
        print(f"[INVENTORY] Parsed data: {data}")
        
        # Validar que tenemos datos mínimos
        if not data or not data.get("product_id"):
            print(f"[INVENTORY] ERROR: No valid data found in event")
            # IMPORTANTE: Devolver HTTP 200 para que Dapr no reintente
            return {"success": False, "error": "No valid data found"}
        
        # Extraer campos
        invoice_id = data.get("invoice_id", "unknown")
        product_id = data.get("product_id", "")
        quantity = data.get("quantity", 0)
        
        print(f"[INVENTORY] Processing: invoice_id={invoice_id}, product_id={product_id}, quantity={quantity}")
        
        # Simular procesamiento
        print("[INVENTORY] Processing... (simulating slow operation)")
        await asyncio.sleep(2)
        
        # Verificar inventario
        inventory_service = InventoryService(db)
        item = inventory_service.get_item_by_product_id(product_id)
        
        # Procesar inventario
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
        
        # Preparar respuesta
        response_data = {
            'invoice_id': invoice_id,
            'product_id': product_id,
            'quantity_requested': quantity,
            'available': available,
            'remaining_stock': remaining,
            'unit_price': unit_price,
            'message': message
        }
        
        print(f"[INVENTORY] Response for invoice {invoice_id}: {response_data}")
        
        # Publicar evento de respuesta (opcional)
        try:
            dapr_url = f"http://localhost:{settings.dapr_http_port}"
            pubsub_url = f"{dapr_url}/v1.0/publish/rabbitmq-pubsub/inventory-response"

            headers = {
                "Content-Type": "application/json",
                "dapr-api-token": settings.dapr_api_token
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(pubsub_url, json=response_data, headers=headers)
                if response.status_code == 204:
                    print(f"[INVENTORY] Published inventory-response event")
        except Exception as pub_error:
            print(f"[INVENTORY] Warning: Could not publish response event: {pub_error}")
        
        # IMPORTANTE: Devolver solo éxito para que Dapr no reintente
        return {"success": True}
        
    except Exception as e:
        print(f"[INVENTORY] Error processing inventory check: {str(e)}")
        import traceback
        traceback.print_exc()
        
        # IMPORTANTE: Devolver HTTP 200 con error para que Dapr no reintente
        return {"success": False, "error": str(e)}
    

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.app_port)