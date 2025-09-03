import asyncio
import httpx
from datetime import datetime
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

# Usar importaciones relativas siguiendo convenciones del proyecto
from app.api.v1.api import router as customers_router
from app.db.database import create_tables, get_db
from app.core.config import settings
from app.services.customer_service import CustomerService
from app.services.deletion_service import CustomerDeletionService
import time
import random


# Crear tablas siguiendo convenciones del proyecto
create_tables()

app = FastAPI(
    title="Accounts Service (Customers)",
    description="Servicio de gestión de clientes con validación distribuida de eliminación",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers con versionado API estándar
app.include_router(customers_router, prefix="/api/v1", tags=["customers"])

# Suscripciones Dapr siguiendo convenciones del proyecto
@app.get("/dapr/subscribe")
def subscribe():
    subscriptions = [
        {
            "pubsubname": "rabbitmq-pubsub",
            "topic": "customer-check",
            "route": "/customer-check"
        },
        {
            "pubsubname": "rabbitmq-pubsub",
            "topic": "customer.deletion.response",
            "route": "/customer-deletion-response"
        }
    ]
    return subscriptions



def simulate_processing_time(min_delay: float = 0.1, max_delay: float = 0.5):
    """Decorator para simular tiempo de procesamiento"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Simular tiempo de procesamiento
            delay = random.uniform(min_delay, max_delay)
            print(f"[{func.__name__}] Simulating processing time: {delay:.3f}s")
            await asyncio.sleep(delay)
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator

@app.post("/customer-deletion-response")
async def handle_deletion_response(event_data: dict, db: Session = Depends(get_db)):
    """Manejar respuestas de validación de eliminación"""
    try:
        print(f"[ACCOUNT] Received deletion response: {event_data}")
        
        data = event_data.get("data", event_data)
        customer_id = data.get("customer_id")
        service_name = data.get("service_name")
        can_delete = data.get("can_delete", False)
        blocking_reason = data.get("blocking_reason")
        
        deletion_service = CustomerDeletionService(db)
        result = deletion_service.process_deletion_response(
            customer_id=customer_id,
            service_name=service_name,
            can_delete=can_delete,
            blocking_reason=blocking_reason
        )
        
        return {"success": True, "result": result}
        
    except Exception as e:
        print(f"[ACCOUNT] Error handling deletion response: {e}")
        return {"success": False, "error": str(e)}



@app.post("/customer-check")
async def handle_customer_check(event_data: dict, db: Session = Depends(get_db)):
    """Verificar si un cliente existe, crear si no existe"""
    try:
        

        print(f"[ACCOUNT] Received customer check request: {event_data}")
        
        # Simular delay con contador visible
        for i in range(15, 0, -1):
            print(f"[ACCOUNT] Customer verification starting in {i} seconds...")
            await asyncio.sleep(1)
        
        print(f"[ACCOUNT] Processing customer verification now...")
        
        
        data = event_data.get("data", event_data)
        invoice_id = data.get("invoice_id")
        customer_id = data.get("customer_id")
        customer_email = data.get("customer_email")
        
        if not invoice_id or not customer_id:
            error_msg = "Missing invoice_id or customer_id in request"
            print(f"[ACCOUNT] {error_msg}")
            await send_customer_response(invoice_id, False, False, error_msg)
            return {"success": False, "error": error_msg}
        
        customer_service = CustomerService(db)
        
        # Verificar si el cliente existe
        existing_customer = customer_service.get_customer_by_id(customer_id)
        
        if existing_customer:
            print(f"[ACCOUNT] Customer {customer_id} exists")
            await send_customer_response(invoice_id, True, False, None)
            return {"success": True, "customer_exists": True}
        
        # Cliente no existe, intentar crear
        print(f"[ACCOUNT] Customer {customer_id} doesn't exist, attempting to create...")
        
        # Datos para crear cliente usando el customer_id del billing
        customer_data = {
            "customer_id": customer_id,
            "email": customer_email or f"{customer_id}@generated.com",
            "name": f"Generated Customer {customer_id}",
            "phone": "000-000-0000",
            "address": "",
            "city": "",
            "country": ""
        }
        
        try:
            new_customer = customer_service.create_customer(customer_data)
            print(f"[ACCOUNT] Created new customer: {new_customer.customer_id}")
            await send_customer_response(invoice_id, False, True, None)
            return {"success": True, "customer_created": True}
            
        except Exception as create_error:
            error_msg = f"Failed to create customer: {str(create_error)}"
            print(f"[ACCOUNT] {error_msg}")
            await send_customer_response(invoice_id, False, False, error_msg)
            return {"success": False, "error": error_msg}
            
    except Exception as e:
        import traceback
        print(f"[ACCOUNT] Error in customer check: {e}")
        print(traceback.format_exc())
        await send_customer_response(invoice_id, False, False, str(e))
        return {"success": False, "error": str(e)}

async def send_customer_response(invoice_id: int, customer_exists: bool, customer_created: bool, error: str = None):
    """Enviar respuesta de verificación de cliente via Dapr pub/sub usando httpx"""
    try:
        response_data = {
            "invoice_id": invoice_id,
            "customer_exists": customer_exists,
            "customer_created": customer_created,
            "error": error,
            "timestamp": datetime.utcnow().isoformat(),
            "service": "account-service"
        }
        
        print(f"[ACCOUNT] Sending customer response: {response_data}")
        
        # Usar httpx siguiendo las convenciones del proyecto (como en inventory_service)
        dapr_url = f"http://localhost:{settings.dapr_http_port}"
        pubsub_url = f"{dapr_url}/v1.0/publish/rabbitmq-pubsub/customer-response"
        
        headers = {
            "Content-Type": "application/json",
            "dapr-api-token": settings.dapr_api_token
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(pubsub_url, json=response_data, headers=headers)
            
        if response.status_code == 204:
            print(f"[ACCOUNT] Customer response sent successfully")
        else:
            print(f"[ACCOUNT] Warning: Failed to send customer response: {response.status_code}")
            
    except Exception as e:
        print(f"[ACCOUNT] Error sending customer response: {e}")
        import traceback
        print(traceback.format_exc())

@app.post("/customer-deletion-request")
async def handle_customer_deletion_request(event_data: dict, db: Session = Depends(get_db)):
    """Manejar solicitudes de eliminación de cliente (funcionalidad existente)"""
    print(f"[ACCOUNT] Received customer deletion request: {event_data}")
    return {"success": True}

@app.get("/health")
def health():
    """Health check endpoint para Dapr"""
    return {"status": "healthy", "service": "accounts-service"}

@app.get("/")
def root():
    """Root endpoint"""
    return {
        "message": "Accounts Service - Customer Management", 
        "version": "1.0.0",
        "docs": "/docs"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.app_port)