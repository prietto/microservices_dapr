from fastapi import FastAPI
from app.core.config import settings
from app.models import Base
from app.db import engine
from app.api.v1.api import api_router

# Crear las tablas
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.project_name,
    description="Microservicio para gestión de inventario con Dapr",
    version="1.0.0",
    openapi_url=f"{settings.api_v1_str}/openapi.json"
)

# Incluir routers
app.include_router(api_router, prefix=settings.api_v1_str)

@app.get("/")
def read_root():
    return {
        "message": "Inventory Service API", 
        "version": "1.0.0",
        "docs": f"{settings.api_v1_str}/docs"
    }

# Endpoint para suscripciones Dapr
@app.get("/dapr/subscribe")
def subscribe():
    return [{
        "pubsubname": "rabbitmq-pubsub",
        "topic": "invoice-events", 
        "route": "/dapr/invoice-events"
    }]

# NUEVO: Endpoint para recibir eventos de facturación
@app.post("/dapr/invoice-events")
async def handle_invoice_event(event_data: dict):
    """Manejar eventos del servicio de facturación"""
    print(f"[INVENTORY] Received invoice event: {event_data}")
    
    # Dapr envuelve el mensaje en CloudEvents - extraer la data real
    actual_data = event_data.get("data", {})
    event_type = actual_data.get("event_type")
    
    if event_type == "invoice_created":
        product_id = actual_data.get("product_id")
        quantity = actual_data.get("quantity", 1)
        invoice_id = actual_data.get("invoice_id")
        customer_name = actual_data.get("customer_name")
        
        print(f"[INVENTORY] Processing: Reduce {quantity} units of {product_id} for invoice {invoice_id}")
        
        # Aquí podrías reducir el inventario real
        # Por ahora solo simulamos
        
        # Respuesta que Dapr entiende correctamente
        return {"success": True}
    
    elif event_type == "invoice_cancelled":
        product_id = actual_data.get("product_id")
        quantity = actual_data.get("quantity", 1)
        invoice_id = actual_data.get("invoice_id")
        
        print(f"[INVENTORY] Processing: Restore {quantity} units of {product_id} for cancelled invoice {invoice_id}")
        
        return {"success": True}
    
    else:
        print(f"[INVENTORY] Unknown event type: {event_type}")
        print(f"[INVENTORY] Available data: {actual_data}")
        
        return {"success": True}  # Incluso eventos desconocidos los marcamos como exitosos

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.app_port)