from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from app.core.config import settings
from app.api.v1.api import router
from app.db import get_db, create_tables
from app.services.invoice_service import InvoiceService
from app.models.invoice import InvoiceStatus
import httpx
import asyncio

app = FastAPI(title=settings.project_name)

# Crear las tablas al iniciar la aplicación
@app.on_event("startup")
async def startup_event():
    create_tables()

app.include_router(router, prefix=settings.api_v1_str)

@app.get("/")
def read_root():
    return {"message": "Billing Service API"}

@app.get("/health")
def health():
    return {"status": "healthy"}

# Suscripciones Dapr
@app.get("/dapr/subscribe")
def subscribe():
    return [
        {
            "pubsubname": "rabbitmq-pubsub",
            "topic": "inventory-response",
            "route": "/inventory-response"
        },
        {
            "pubsubname": "rabbitmq-pubsub", 
            "topic": "inventory-compensated",
            "route": "/inventory-compensated"
        },
        {
            "pubsubname": "rabbitmq-pubsub",
            "topic": "billing-compensate",
            "route": "/billing-compensate"
        },
         {
            "pubsubname": "rabbitmq-pubsub",
            "topic": "payment-completed",
            "route": "/payment-completed"
        },
        {
            "pubsubname": "rabbitmq-pubsub",
            "topic": "payment-failed",
            "route": "/payment-failed"
        }
    ]


# EL SERVICIO DE INVENTARIO RESPONDIO Y SE EJECUTA EL SIGUIENTE METODO
@app.post("/inventory-response")
async def handle_inventory_response(event_data: dict, db: Session = Depends(get_db)):
    print(f"[BILLING] Received inventory response: {event_data}")
    
    data = event_data.get("data", event_data)
    invoice_id = data.get("invoice_id")
    product_id = data.get("product_id")
    available = data.get("available")
    unit_price = data.get("unit_price", 0.0)
    quantity_requested = data.get("quantity_requested", 1)
    message = data.get("message", "")

    if not invoice_id:
        print(f"[BILLING] ERROR: No invoice_id in inventory response")
        return {"success": False, "error": "No invoice_id"}
    
    invoice_service = InvoiceService(db)
    
    try:
        if available:
            # Inventario disponible - cambiar estado y enviar evento de pago
            invoice = invoice_service.update_invoice_status(
                invoice_id=invoice_id,
                status=InvoiceStatus.PAYMENT_PROCESSING,  # ← NUEVO ESTADO
                unit_price=unit_price,
                notes=f"Inventory confirmed: {message}. Requesting payment..."
            )
            
            # ENVIAR EVENTO ASÍNCRONO AL PAYMENT SERVICE
            await request_payment_processing(
                invoice_id=invoice_id,
                amount=unit_price * quantity_requested,
                customer_id=getattr(invoice, 'customer_id', invoice.customer_email),
                product_id=product_id
            )
            
            print(f"[BILLING] Payment request sent for invoice {invoice.invoice_number}")
            
        else:
            # No hay inventario, marcar como fallida
            invoice = invoice_service.update_invoice_status(
                invoice_id=invoice_id,
                status=InvoiceStatus.FAILED,
                notes=f"Insufficient inventory: {message}"
            )
            print(f"[BILLING] Invoice {invoice.invoice_number} failed: no inventory")
            
    except Exception as e:
        print(f"[BILLING] Error processing inventory response: {e}")
    
    return {"success": True}


# FUNCION PARA ENVIAR EVENTO DE PROCESAMIENTO DE PAGO
async def request_payment_processing(invoice_id: int, amount: float, customer_id: str, product_id: str):
    """Enviar evento para solicitar procesamiento de pago"""
    print(f"[BILLING] Requesting payment for invoice {invoice_id}, amount: ${amount}")
    
    payment_request_data = {
        "invoiceId": str(invoice_id),
        "orderId": str(invoice_id),
        "amount": amount,
        "customerId": customer_id,
        "productId": product_id,
        "currency": "USD",
        "description": f"Payment for invoice {invoice_id}",
        "requestedBy": "billing-service"
    }
    
    try:
        # Enviar evento de solicitud de pago con timeout
        dapr_url = f"http://localhost:3501"
        pubsub_url = f"{dapr_url}/v1.0/publish/rabbitmq-pubsub/payment-request"

        headers = {
            "Content-Type": "application/json",
            "dapr-api-token": settings.dapr_api_token
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(pubsub_url, json=payment_request_data, headers=headers)

        if response.status_code == 204:
            print(f"[BILLING] Payment request event sent for invoice {invoice_id}")
        else:
            print(f"[BILLING] Failed to send payment request: {response.status_code}")
            # Si falla el envío, activar compensación
            await handle_payment_request_failure(invoice_id, product_id, "Failed to send payment request")
            
    except Exception as e:
        print(f"[BILLING] Error sending payment request: {e}")
        # Error en el envío, activar compensación
        await handle_payment_request_failure(invoice_id, product_id, f"Payment request error: {str(e)}")



async def handle_payment_request_failure(invoice_id: int, product_id: str, reason: str):
    """Manejar falla en la solicitud de pago - activar compensación"""
    print(f"[BILLING] 🔄 Payment request failed for invoice {invoice_id}: {reason}")
    
    try:
        # Activar compensación de inventario
        await trigger_inventory_compensation(
            invoice_id=invoice_id,
            product_id=product_id,
            quantity=1,  # Asumiendo cantidad 1, podrías obtenerla de la invoice
            reason=f"Payment request failed: {reason}"
        )
        
        # Actualizar estado de la factura
        db = next(get_db())  # Obtener sesión de DB
        invoice_service = InvoiceService(db)
        
        invoice = invoice_service.update_invoice_status(
            invoice_id=invoice_id,
            status=InvoiceStatus.CANCELLED,
            notes=f"Payment request failed: {reason}. Inventory compensation triggered."
        )
        
        print(f"[BILLING] Invoice {invoice.invoice_number} cancelled due to payment failure")
        
    except Exception as e:
        print(f"[BILLING] Error handling payment request failure: {e}")


# NUEVOS ENDPOINTS para recibir respuestas de payment
@app.post("/payment-completed")
async def handle_payment_completed(event_data: dict, db: Session = Depends(get_db)):
    """Manejar pago completado exitosamente"""
    print(f"[BILLING] Payment completed: {event_data}")
    
    data = event_data.get("data", event_data)
    invoice_id = data.get("invoice_id") or data.get("order_id")
    transaction_id = data.get("transaction_id")
    amount = data.get("amount")
    
    try:
        invoice_service = InvoiceService(db)
        
        # Actualizar factura como completada
        invoice = invoice_service.update_invoice_status(
            invoice_id=invoice_id,
            status=InvoiceStatus.COMPLETED,
            notes=f"Payment completed successfully. Transaction ID: {transaction_id}, Amount: ${amount}"
        )
        
        await send_invoice_notification(invoice, "completed")
        print(f"[BILLING] Invoice {invoice.invoice_number} completed successfully")
        
    except Exception as e:
        print(f"[BILLING] Error handling payment completion: {e}")
    
    return {"success": True}



@app.post("/payment-failed")
async def handle_payment_failed(event_data: dict, db: Session = Depends(get_db)):
    """Manejar pago fallido - activar compensación"""
    print(f"[BILLING] Payment failed: {event_data}")
    
    data = event_data.get("data", event_data)
    invoice_id = data.get("invoice_id") or data.get("order_id")
    reason = data.get("reason", "Payment processing failed")
    error_details = data.get("error_details", "")
    
    try:
        invoice_service = InvoiceService(db)
        invoice = invoice_service.get_invoice_by_id(invoice_id)
        
        if invoice:
            # COMPENSACIÓN: Restaurar inventario
            await trigger_inventory_compensation(
                invoice_id=invoice_id,
                product_id=invoice.product_id,
                quantity=invoice.quantity,
                reason=f"Payment failed: {reason}"
            )
            
            # Marcar factura como fallida
            invoice_service.update_invoice_status(
                invoice_id=invoice_id,
                status=InvoiceStatus.FAILED,
                notes=f"Payment failed: {reason}. Details: {error_details}. Inventory compensated."
            )
            
            await send_invoice_notification(invoice, "failed")
            print(f"[BILLING] Invoice {invoice.invoice_number} failed, inventory compensated")
        
    except Exception as e:
        print(f"[BILLING] Error handling payment failure: {e}")
    
    return {"success": True}



# Nueva función para disparar compensación
async def trigger_inventory_compensation(invoice_id: int, product_id: str, quantity: int, reason: str):
    """Disparar compensación de inventario"""
    print(f"[BILLING]  Triggering inventory compensation for invoice {invoice_id}")
    
    compensation_data = {
        "invoice_id": invoice_id,
        "product_id": product_id,
        "quantity": quantity,  # Cantidad a restaurar
        "reason": reason,
        "compensation_type": "restore_inventory",
        "triggered_by": "billing-service"
    }
    
    try:
        dapr_url = f"http://localhost:3500"
        pubsub_url = f"{dapr_url}/v1.0/publish/rabbitmq-pubsub/compensate-inventory"

        headers = {
            "Content-Type": "application/json",
            "dapr-api-token": settings.dapr_api_token
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(pubsub_url, json=compensation_data, headers=headers)

        if response.status_code == 204:
            print(f"[BILLING] Compensation request sent for invoice {invoice_id}")
        else:
            print(f"[BILLING] Failed to send compensation request: {response.status_code}")
            
    except Exception as e:
        print(f"[BILLING] Error sending compensation: {e}")

# Manejar confirmación de compensación
@app.post("/inventory-compensated")
async def handle_inventory_compensated(event_data: dict, db: Session = Depends(get_db)):
    """Manejar confirmación de compensación de inventario"""
    print(f"[BILLING] Received inventory compensation confirmation: {event_data}")
    
    data = event_data.get("data", event_data)
    invoice_id = data.get("invoice_id")
    compensation_successful = data.get("compensation_successful", False)
    quantity_restored = data.get("quantity_restored", 0)
    
    invoice_service = InvoiceService(db)
    
    try:
        if compensation_successful:
            # Actualizar notas de la factura con información de compensación
            invoice = invoice_service.get_invoice_by_id(invoice_id)
            if invoice:
                current_notes = invoice.notes or ""
                compensation_note = f"\n[COMPENSATED] Restored {quantity_restored} units to inventory"
                
                invoice_service.update_invoice_status(
                    invoice_id=invoice_id,
                    status=InvoiceStatus.CANCELLED,  # Estado final después de compensación
                    notes=current_notes + compensation_note
                )
                
                # Enviar notificación de cancelación
                await send_invoice_notification(invoice, "cancelled")
                print(f"[BILLING] Invoice {invoice.invoice_number} compensated and cancelled")
        else:
            print(f"[BILLING] Inventory compensation failed for invoice {invoice_id}")
            
    except Exception as e:
        print(f"[BILLING] Error handling compensation confirmation: {e}")
    
    return {"success": True}

# Endpoint para compensar billing (si otro servicio lo necesita)
@app.post("/billing-compensate")
async def handle_billing_compensate(event_data: dict, db: Session = Depends(get_db)):
    """Manejar compensación de billing desde otros servicios"""
    print(f"[BILLING] 🔄 Compensating billing: {event_data}")
    
    data = event_data.get("data", event_data)
    invoice_id = data.get("invoice_id")
    reason = data.get("reason", "External service compensation")
    
    try:
        invoice_service = InvoiceService(db)
        
        # Marcar factura como cancelada/compensada
        invoice = invoice_service.update_invoice_status(
            invoice_id=invoice_id,
            status=InvoiceStatus.CANCELLED,
            notes=f"Compensated by external service: {reason}"
        )
        
        # Enviar notificación de cancelación
        await send_invoice_notification(invoice, "cancelled")
        
        print(f"[BILLING] Compensated: Invoice {invoice.invoice_number} cancelled")
        
        return {"success": True}
        
    except Exception as e:
        print(f"[BILLING] Billing compensation failed: {e}")
        return {"success": False, "error": str(e)}
    


async def send_invoice_notification(invoice, status: str):
    """Enviar notificación por email (simulado)"""
    try:
        # Simular envío de email
        await asyncio.sleep(1)  # Simular latencia de email service
        
        email_data = {
            "to": invoice.customer_email or "customer@example.com",
            "subject": f"Invoice {invoice.invoice_number} - {status.title()}",
            "body": f"""
            Dear Customer,
            
            Your invoice {invoice.invoice_number} is now {status}.
            
            Product: {invoice.product_id}
            Quantity: {invoice.quantity}
            Total Amount: ${invoice.total_amount or 0.0:.2f}
            Status: {status.title()}
            
            Thank you for your business!
            """,
            "invoice_id": invoice.id
        }
        
        print(f"[BILLING] Email sent to {email_data['to']}: {email_data['subject']}")
        
    except Exception as e:
        print(f"[BILLING] Error sending email notification: {e}")




async def process_payment_with_csharp_service(invoice_id: int, amount: float, customer_id: str, product_id: str):
    """Procesar pago usando el Payment Service en C#"""
    print(f"[BILLING] Processing payment for invoice {invoice_id}, amount: ${amount}")
    
    payment_data = {
        "orderId": str(invoice_id),
        "amount": amount,
        "customerId": customer_id,
        "currency": "USD",
        "productId": product_id,
        "description": f"Payment for invoice {invoice_id}"
    }
    
    try:
        # Llamar al Payment Service en C# a través de Dapr
        dapr_url = f"http://localhost:3503"  # Puerto Dapr del Payment Service
        payment_url = f"{dapr_url}/v1.0/invoke/payment-service/method/api/payment/process"

        headers = {
            "Content-Type": "application/json",
            "dapr-api-token": settings.dapr_api_token
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(payment_url, json=payment_data, headers=headers)

            print(f"[BILLING] Payment service response: {response.status_code}")
            
            if response.status_code == 200:
                payment_response = response.json()
                
                # Verificar si el pago fue aprobado
                if payment_response.get("status") == "approved":
                    return {
                        "success": True,
                        "transaction_id": payment_response.get("transactionId"),
                        "message": payment_response.get("message", "Payment approved")
                    }
                else:
                    return {
                        "success": False,
                        "error": payment_response.get("message", "Payment rejected"),
                        "status": payment_response.get("status")
                    }
            else:
                error_text = response.text if response.text else "Unknown error"
                return {
                    "success": False,
                    "error": f"Payment service error: {response.status_code} - {error_text}"
                }
                
    except Exception as e:
        print(f"[BILLING] Error calling payment service: {e}")
        return {
            "success": False,
            "error": f"Payment service unavailable: {str(e)}"
        }
    
    
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.app_port)