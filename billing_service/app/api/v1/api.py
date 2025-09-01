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
    """Crear nueva factura y solicitar verificación de inventario y cliente"""
    print('invoice_data=> ', invoice_data)
    try:
        # 1. Crear factura en estado pendiente
        invoice_service = InvoiceService(db)
        invoice = await invoice_service.create_invoice(invoice_data)
        
        print(f"[BILLING] Created invoice {invoice.invoice_number} in PENDING state")
        
        # 2. Marcar como processing
        await invoice_service.update_invoice_status(
            invoice.id, 
            InvoiceStatus.PROCESSING,
            notes="Invoice created - Customer and inventory verification in progress"
        )
        
        dapr_url = f"http://localhost:{settings.dapr_http_port}"
        headers = {
            "Content-Type": "application/json",
            "dapr-api-token": settings.dapr_api_token
        }
        
        # 3. Solicitar verificación de inventario
        inventory_pubsub_url = f"{dapr_url}/v1.0/publish/rabbitmq-pubsub/inventory-check"
        inventory_event_data = {
            "invoice_id": invoice.id,
            "product_id": invoice.product_id,
            "quantity": invoice.quantity,
            "action": "check_for_billing"
        }
        
        print(f"[BILLING] Sending inventory check for invoice {invoice.invoice_number}")

        # 4. Solicitar verificación de cliente
        customer_pubsub_url = f"{dapr_url}/v1.0/publish/rabbitmq-pubsub/customer-check"
        customer_event_data = {
            "invoice_id": invoice.id,
            "customer_id": invoice.customer_id,
            "customer_email": invoice.customer_email,
            "action": "check_for_billing"
        }
        
        print(f"[BILLING] Sending customer check for invoice {invoice.invoice_number}")

        async with httpx.AsyncClient() as client:
            # Enviar solicitud de verificación de inventario
            inventory_response = await client.post(inventory_pubsub_url, json=inventory_event_data, headers=headers)
            
            # Enviar solicitud de verificación de cliente
            customer_response = await client.post(customer_pubsub_url, json=customer_event_data, headers=headers)

        # Verificar si ambas solicitudes fueron exitosas
        if inventory_response.status_code == 204 and customer_response.status_code == 204:
            print(f"[BILLING] Inventory and customer checks requested for invoice {invoice.invoice_number}")
            # Refrescar invoice para obtener el estado actualizado
            invoice = invoice_service.get_invoice_by_id(invoice.id)
            return invoice
        else:
            # Si falla algún evento, marcar factura como fallida
            error_msg = ""
            if inventory_response.status_code != 204:
                error_msg += f"Inventory check failed (status: {inventory_response.status_code}); "
            if customer_response.status_code != 204:
                error_msg += f"Customer check failed (status: {customer_response.status_code}); "
            
            invoice_service.update_invoice_status(
                invoice.id,
                InvoiceStatus.FAILED,
                notes=f"Failed to request verifications: {error_msg}"
            )
            raise HTTPException(status_code=500, detail=f"Failed to request verifications: {error_msg}")
            
    except Exception as e:
        import traceback
        print(traceback.format_exc())
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
                        "account-service-",
                        "inventory-check",
                        "inventory-response",
                        "customer-check",
                        "customer-response"
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