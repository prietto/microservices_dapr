from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db import get_db
from app.services.invoice_service import InvoiceService
from app.schemas.invoice import InvoiceCreate, InvoiceResponse
from app.models.invoice import InvoiceStatus, Invoice
import httpx

router = APIRouter()

@router.get("/test")
def test():
    return {"message": "Billing API working!"}

@router.post("/create-invoice", response_model=InvoiceResponse)
async def create_invoice(invoice_data: InvoiceCreate, db: Session = Depends(get_db)):
    """Crear nueva factura y solicitar verificación de inventario"""
    
    try:
        # 1. Crear factura en estado pendiente
        invoice_service = InvoiceService(db)
        invoice = invoice_service.create_invoice(invoice_data)
        
        print(f"[BILLING] Created invoice {invoice.invoice_number} in PENDING state")
        
        # 2. Marcar como processing
        invoice_service.update_invoice_status(
            invoice.id, 
            InvoiceStatus.PROCESSING,
            notes="Requesting inventory verification"
        )
        
        # 3. Solicitar verificación de inventario
        dapr_url = f"http://localhost:{settings.dapr_http_port}"
        pubsub_url = f"{dapr_url}/v1.0/publish/rabbitmq-pubsub/inventory-check"
        
        event_data = {
            "invoice_id": invoice.id,
            "product_id": invoice.product_id,
            "quantity": invoice.quantity,
            "action": "check_for_billing"
        }
        
        print(f"[BILLING] Sending inventory check for invoice {invoice.invoice_number}")
        headers = {
            "Content-Type": "application/json",
            "dapr-api-token": settings.dapr_api_token
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(pubsub_url, json=event_data, headers=headers)

        if response.status_code == 204:
            print(f"[BILLING] Inventory check requested for invoice {invoice.invoice_number}")
            # Refrescar invoice para obtener el estado actualizado
            invoice = invoice_service.get_invoice_by_id(invoice.id)
            return invoice
        else:
            # Si falla el evento, marcar factura como fallida
            invoice_service.update_invoice_status(
                invoice.id,
                InvoiceStatus.FAILED,
                notes="Failed to request inventory verification"
            )
            raise HTTPException(status_code=500, detail="Failed to request inventory verification")
            
    except Exception as e:
        print(f"[BILLING] Error creating invoice: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/invoices/{invoice_id}", response_model=InvoiceResponse)
def get_invoice(invoice_id: int, db: Session = Depends(get_db)):
    """Obtener factura por ID"""
    invoice_service = InvoiceService(db)
    invoice = invoice_service.get_invoice_by_id(invoice_id)
    
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    return invoice

@router.get("/invoices")
def list_invoices(status: str = None, db: Session = Depends(get_db)):
    """Listar facturas, opcionalmente filtradas por estado"""
    invoice_service = InvoiceService(db)
    
    if status:
        try:
            status_enum = InvoiceStatus(status)
            invoices = invoice_service.get_invoices_by_status(status_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid status")
    else:
        invoices = invoice_service.get_all_invoices()
    
    return {"invoices": invoices}

@router.get("/queue-status")
async def check_queue_status():
    """Verificar el estado de las colas de RabbitMQ desde billing service"""
    try:
        rabbitmq_api = "http://localhost:15672/api"
        
        async with httpx.AsyncClient(
            auth=("guest", "guest"),
            timeout=5.0
        ) as client:
            response = await client.get(f"{rabbitmq_api}/queues")
            
            if response.status_code == 200:
                queues = response.json()
                
                dapr_queues = []
                pending_messages = 0
                
                for queue in queues:
                    queue_name = queue.get("name", "")
                    messages = queue.get("messages", 0)
                    
                    # Buscar colas que sigan el patrón de Dapr: {app-id}-{topic}
                    if any(pattern in queue_name for pattern in [
                        "billing-service-", 
                        "inventory-service-",
                        "inventory-check",
                        "inventory-response"
                    ]):
                        queue_info = {
                            "name": queue_name,
                            "messages": messages,
                            "messages_ready": queue.get("messages_ready", 0),
                            "consumers": queue.get("consumers", 0),
                            "state": queue.get("state", "unknown")
                        }
                        dapr_queues.append(queue_info)
                        pending_messages += messages
                
                return {
                    "status": "success",
                    "service": "billing-service",
                    "dapr_queues": dapr_queues,
                    "total_pending_messages": pending_messages,
                    "queue_pattern": "Dapr uses pattern: {app-id}-{topic-name}"
                }
            else:
                return {"status": "error", "message": f"RabbitMQ API returned {response.status_code}"}
                
    except Exception as e:
        return {"status": "error", "message": f"Error: {str(e)}"}

@router.get("/rabbitmq-debug")
async def rabbitmq_debug():
    """Debug completo de RabbitMQ"""
    try:
        rabbitmq_api = "http://localhost:15672/api"
        
        async with httpx.AsyncClient(
            auth=("guest", "guest"),
            timeout=10.0
        ) as client:
            
            # Obtener información completa
            queues_response = await client.get(f"{rabbitmq_api}/queues")
            exchanges_response = await client.get(f"{rabbitmq_api}/exchanges")
            
            result = {
                "status": "success",
                "timestamp": "now",
                "queues": [],
                "exchanges": [],
                "totals": {
                    "queues": 0,
                    "exchanges": 0,
                    "total_messages": 0
                }
            }
            
            if queues_response.status_code == 200:
                queues = queues_response.json()
                result["totals"]["queues"] = len(queues)
                
                for queue in queues:
                    messages = queue.get("messages", 0)
                    result["totals"]["total_messages"] += messages
                    
                    result["queues"].append({
                        "name": queue.get("name", ""),
                        "messages": messages,
                        "consumers": queue.get("consumers", 0),
                        "state": queue.get("state", ""),
                        "durable": queue.get("durable", False),
                        "auto_delete": queue.get("auto_delete", False)
                    })
            
            if exchanges_response.status_code == 200:
                exchanges = exchanges_response.json()
                result["totals"]["exchanges"] = len(exchanges)
                
                for exchange in exchanges:
                    result["exchanges"].append({
                        "name": exchange.get("name", ""),
                        "type": exchange.get("type", ""),
                        "durable": exchange.get("durable", False)
                    })
            
            return result
                
    except Exception as e:
        return {"status": "error", "message": f"Error: {str(e)}"}