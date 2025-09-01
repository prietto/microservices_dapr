from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from app.core.config import settings
from app.api.v1.api import router
from app.db import get_db, create_tables
from app.services.invoice_service import InvoiceService
from app.models.invoice import InvoiceStatus
import httpx
import asyncio
from dapr.clients import DaprClient
from app.migration import run_migration
from datetime import datetime
from typing import List

app = FastAPI(title=settings.project_name)

# Crear las tablas al iniciar la aplicación
@app.on_event("startup")
async def startup_event():
    create_tables()
    run_migration()

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
        },
        {
            "pubsubname": "rabbitmq-pubsub",
            "topic": "customer.deletion.request",
            "route": "/customer-deletion-request"
        },

        {
            "pubsubname": "rabbitmq-pubsub", 
            "topic": "customer-response",
            "route": "/customer-response"
        }
    ]



@app.post("/customer-response")
async def handle_customer_response(event_data: dict, db: Session = Depends(get_db)):
    """Manejar respuesta de verificación de cliente desde account service"""
    try:
        print(f"[BILLING] Received customer response: {event_data}")
        
        data = event_data.get("data", event_data)
        invoice_id = data.get("invoice_id")
        customer_exists = data.get("customer_exists", False)
        customer_created = data.get("customer_created", False)
        error_message = data.get("error")
        
        if not invoice_id:
            print(f"[BILLING] No invoice_id in customer response")
            return {"success": False, "error": "No invoice_id"}
        
        invoice_service = InvoiceService(db)
        invoice = invoice_service.get_invoice_by_id(invoice_id)
        
        if not invoice:
            print(f"[BILLING] Invoice {invoice_id} not found for customer response")
            return {"success": False, "error": "Invoice not found"}
        
        # Crear mensaje para customer_status
        if error_message:
            # Error en la verificación/creación del cliente
            status_message = f"Customer verification failed: {error_message}"
            await invoice_service.update_customer_status(invoice_id, status_message)
            
            # Actualizar estado general de la factura
            await invoice_service.update_invoice_status(
                invoice_id,
                InvoiceStatus.FAILED,
                notes=f"Invoice failed due to customer verification issues"
            )
            print(f"[BILLING] Customer error for invoice {invoice.invoice_number}: {error_message}")
        elif customer_exists:
            # Cliente existe
            status_message = "Customer exists and verified"
            await invoice_service.update_customer_status(invoice_id, status_message)
            print(f"[BILLING] Customer exists for invoice {invoice.invoice_number}")
        elif customer_created:
            # Cliente fue creado exitosamente
            status_message = "Customer created successfully"
            await invoice_service.update_customer_status(invoice_id, status_message)
            print(f"[BILLING] Customer created for invoice {invoice.invoice_number}")
        else:
            # Caso no manejado - actualizar estado
            status_message = "Customer verification result unclear"
            await invoice_service.update_customer_status(invoice_id, status_message)
            print(f"[BILLING] Unclear customer verification result for {invoice.invoice_number}")
        
        return {"success": True}
            
    except Exception as e:
        import traceback
        print(f"[BILLING] Error handling customer response: {e}")
        print(traceback.format_exc())
        return {"success": False, "error": str(e)}





@app.post("/customer-deletion-request")
async def handle_customer_deletion_request(event_data: dict, db: Session = Depends(get_db)):
    """Validar si se puede eliminar cliente desde perspectiva de facturación"""
    try:
        print(f"[BILLING] Received customer deletion request: {event_data}")
        
        data = event_data.get("data", event_data)
        customer_id = data.get("customer_id")
        
        if not customer_id:
            print(f"[BILLING] No customer_id in deletion request")
            return {"success": False, "error": "No customer_id"}
        
        print(f"[BILLING] Validating customer deletion for {customer_id}")
        
        # Verificar si el cliente tiene facturas activas que impidan eliminación
        invoice_service = InvoiceService(db)
        
        # Contar facturas en estados que bloquean eliminación
        active_invoices = invoice_service.get_invoices_by_customer(customer_id)
        blocking_invoices = [
            inv for inv in active_invoices 
            if inv.status in [InvoiceStatus.PENDING.value, InvoiceStatus.PROCESSING.value]
        ]
        
        can_delete = len(blocking_invoices) == 0
        blocking_reason = None
        
        if not can_delete:
            blocking_reason = f"Customer has {len(blocking_invoices)} active invoices in processing/pending status"
            print(f"[BILLING] Customer deletion BLOCKED: {blocking_reason}")
        else:
            print(f"[BILLING] Customer deletion APPROVED: No blocking invoices found")
        
        # Responder al Account Service
        response_data = {
            "customer_id": customer_id,
            "service_name": "billing-service",
            "can_delete": can_delete,
            "blocking_reason": blocking_reason,
            "active_invoices_count": len(active_invoices),
            "blocking_invoices_count": len(blocking_invoices),
            "validated_at": datetime.utcnow().isoformat()
        }
        
        # Enviar respuesta via Dapr PubSub
        await send_deletion_response(response_data)
        
        return {"success": True}
        
    except Exception as e:
        print(f"[BILLING] Error validating customer deletion: {e}")
        import traceback
        print(f"[BILLING] Full traceback: {traceback.format_exc()}")
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
            print(f"[BILLING] Deletion validation response sent successfully")
        else:
            print(f"[BILLING] Failed to send deletion response: {response.status_code}")
            
    except Exception as e:
        print(f"[BILLING] Error sending deletion response: {e}")




@app.post("/inventory-response")
async def handle_inventory_response(event_data: dict, db: Session = Depends(get_db)):
    """Manejar respuesta de verificación de inventario"""
    try:
        print(f"[BILLING] Received inventory response: {event_data}")
        
        data = event_data.get("data", event_data)
        invoice_id = data.get("invoice_id")
        available = data.get("available", False)
        unit_price = data.get("unit_price")
        message = data.get("message", "")
        
        if not invoice_id:
            print(f"[BILLING] No invoice_id in inventory response")
            return {"success": False}
        
        invoice_service = InvoiceService(db)
        invoice = invoice_service.get_invoice_by_id(invoice_id)
        
        if not invoice:
            print(f"[BILLING] Invoice {invoice_id} not found")
            return {"success": False}
        
        # Actualizar estado del inventario en campo dedicado
        inventory_status = f"Inventory {'' if available else 'not '}available: {message}"
        await invoice_service.update_inventory_status(invoice_id, inventory_status)
        
        if available and unit_price:
            
            # AÑADIR ESTO: Actualizar estado del pago ANTES de solicitarlo
            await invoice_service.update_payment_status(invoice_id, "Payment processing initiated")
            
            # Proceder con el pago
            await request_payment_processing(
                invoice_id, 
                unit_price * invoice.quantity,
                invoice.customer_id,
                invoice.product_id
            )
        else:
            # Inventario no disponible - marcar como fallida
            await invoice_service.update_invoice_status(
                invoice_id,
                InvoiceStatus.FAILED,
                notes=f"Invoice failed due to inventory issues"
            )
            print(f"[BILLING] Invoice {invoice.invoice_number} failed due to inventory")
        
        return {"success": True}
        
    except Exception as e:
        print(f"[BILLING] Error handling inventory response: {e}")
        
        # AÑADIR MANEJO ROBUSTO DE ERRORES
        try:
            # Obtener ID de factura del evento si es posible
            invoice_id = event_data.get("data", event_data).get("invoice_id")
            if invoice_id:
                invoice_service = InvoiceService(db)
                invoice = invoice_service.get_invoice_by_id(invoice_id)
                
                if invoice:
                    # Marcar factura como fallida
                    await invoice_service.update_invoice_status(
                        invoice_id,
                        InvoiceStatus.FAILED,
                        notes=f"System error processing inventory response: {str(e)}"
                    )
                    
                    # Actualizar estados específicos
                    await invoice_service.update_payment_status(invoice_id, "Payment not processed due to system error")
                    
                    print(f"[BILLING] Invoice {invoice.invoice_number} marked as FAILED due to error")
                    
                    # Si el error ocurrió después de verificar inventario, compensar
                    product_id = invoice.product_id
                    if product_id:
                        await trigger_inventory_compensation(
                            invoice_id=invoice_id,
                            product_id=product_id,
                            quantity=invoice.quantity,
                            reason=f"System error: {str(e)}"
                        )
        except Exception as recovery_error:
            print(f"[BILLING] CRITICAL ERROR: Failed to handle exception recovery: {recovery_error}")
        
        return {"success": False, "error": str(e)}




# FUNCION PARA ENVIAR EVENTO DE PROCESAMIENTO DE PAGO
async def request_payment_processing(invoice_id: int, amount: float, customer_id: str, product_id: str):
    """Enviar evento para solicitar procesamiento de pago con timeout"""
    print(f"[BILLING] Requesting payment for invoice {invoice_id}, amount: ${amount}")
    
    # Actualizar estado de pago ANTES de enviar la solicitud
    db = next(get_db())
    invoice_service = InvoiceService(db)
    await invoice_service.update_payment_status(invoice_id, "Payment processing initiated")
    
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
    
    # Iniciar tarea de timeout en segundo plano
    # No espera a que termine para continuar con el flujo
    asyncio.create_task(check_payment_timeout(invoice_id, 60))  # 60 segundos timeout
    
    try:
        # Enviar evento de solicitud de pago
        dapr_url = f"http://localhost:{settings.dapr_http_port}"
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



async def check_payment_timeout(invoice_id: int, timeout_seconds: int = 60):
    """Verificar si un pago ha expirado después del tiempo especificado"""
    print(f"[BILLING] Setting payment timeout for invoice {invoice_id}: {timeout_seconds} seconds")
    
    try:
        # Esperar el tiempo de timeout
        await asyncio.sleep(timeout_seconds)
        
        # Verificar si la factura sigue en estado PROCESSING
        db = next(get_db())
        invoice_service = InvoiceService(db)
        invoice = invoice_service.get_invoice_by_id(invoice_id)
        
        if invoice and invoice.status == InvoiceStatus.PROCESSING.value:
            print(f"[BILLING] Payment TIMEOUT for invoice {invoice.invoice_number} after {timeout_seconds} seconds")
            
            # Cancelar factura por timeout
            await invoice_service.update_invoice_status(
                invoice_id,
                InvoiceStatus.CANCELLED,
                notes=f"Payment processing timed out after {timeout_seconds} seconds"
            )
            
            # Actualizar estado del pago
            await invoice_service.update_payment_status(
                invoice_id, 
                f"Payment failed: Timeout after waiting {timeout_seconds} seconds without response"
            )
            
            # Compensar inventario
            await trigger_inventory_compensation(
                invoice_id=invoice_id,
                product_id=invoice.product_id,
                quantity=invoice.quantity,
                reason="Payment processing timeout"
            )
            
            # Enviar notificación
            await send_invoice_notification(invoice, "cancelled")
            print(f"[BILLING] Invoice {invoice.invoice_number} cancelled due to payment timeout")
        else:
            print(f"[BILLING] No timeout needed for invoice {invoice_id} - already processed")
    
    except Exception as e:
        print(f"[BILLING] Error in payment timeout check: {e}")



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
        
        invoice = await invoice_service.update_invoice_status(
            invoice_id=invoice_id,
            status=InvoiceStatus.CANCELLED,
            notes=f"Payment request failed: {reason}. Inventory compensation triggered."
        )
        
        print(f"[BILLING] Invoice {invoice.invoice_number} cancelled due to payment failure")
        
    except Exception as e:
        print(f"[BILLING] Error handling payment request failure: {e}")



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
        invoice = invoice_service.get_invoice_by_id(invoice_id)
        
        if not invoice:
            print(f"[BILLING] Invoice {invoice_id} not found for payment completion")
            return {"success": False, "error": "Invoice not found"}
        
        # VERIFICAR ESTADO ACTUAL - Solo permitir cambio si está en PROCESSING
        if invoice.status == InvoiceStatus.CANCELLED.value:
            print(f"[BILLING] IGNORED payment completion for cancelled invoice {invoice.invoice_number}")
            await invoice_service.update_payment_status(
                invoice_id, 
                f"Payment received after cancellation (timeout). Transaction ID: {transaction_id}. No state change."
            )
            return {"success": True, "message": "Invoice already cancelled, payment ignored"}
        
        elif invoice.status == InvoiceStatus.COMPLETED.value:
            print(f"[BILLING] IGNORED duplicate payment completion for invoice {invoice.invoice_number}")
            return {"success": True, "message": "Invoice already completed"}
        
        elif invoice.status == InvoiceStatus.FAILED.value:
            print(f"[BILLING] IGNORED payment completion for failed invoice {invoice.invoice_number}")
            await invoice_service.update_payment_status(
                invoice_id, 
                f"Late payment received for failed invoice. Transaction ID: {transaction_id}. No state change."
            )
            return {"success": True, "message": "Invoice already failed, payment ignored"}

        # Actualizar estado de pago
        await invoice_service.update_payment_status(
            invoice_id, 
            f"Payment completed successfully. Transaction ID: {transaction_id}, Amount: ${amount}"
        )
        
        # Actualizar factura como completada SOLO si está en PROCESSING
        invoice = await invoice_service.update_invoice_status(
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
            await invoice_service.update_invoice_status(
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

                await invoice_service.update_invoice_status(
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
        invoice = await invoice_service.update_invoice_status(
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