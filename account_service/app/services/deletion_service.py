from typing import Dict, List
from sqlalchemy.orm import Session
from dapr.clients import DaprClient
from datetime import datetime, timedelta
import json
import asyncio

from app.models.customer import Customer, CustomerStatus
from app.core.config import settings
import requests
import httpx


class CustomerDeletionService:
    def __init__(self, db: Session):
        self.db = db
        self.validation_timeout = 10  # 30 segundos para recibir respuestas

    async def request_customer_deletion(self, customer_id: str) -> Dict:
        """Iniciar proceso de eliminación de cliente con validación distribuida"""
        # Verificar que el cliente existe
        customer = self.db.query(Customer).filter(Customer.customer_id == customer_id).first()
        if not customer:
            raise ValueError(f"Customer {customer_id} not found")
        
        if customer.status == CustomerStatus.PENDING_DELETION:
            raise ValueError(f"Customer {customer_id} deletion already in progress")
        
        print(f"[ACCOUNT] Starting customer deletion process for {customer_id}")
        
        # Actualizar estado del cliente
        customer.status = CustomerStatus.PENDING_DELETION.value
        customer.deletion_requested_at = datetime.utcnow()
        customer.deletion_responses = "{}"  # JSON vacío
        customer.deletion_blocked_by = None
        self.db.commit()
        
        # Enviar evento de solicitud de eliminación
        try:
            await self._broadcast_deletion_request(customer_id)
            print(f"[ACCOUNT] Deletion request broadcasted for {customer_id}")
        except Exception as e:
            # Revertir estado si falla el envío
            customer.status = CustomerStatus.ACTIVE.value
            customer.deletion_requested_at = None
            self.db.commit()
            raise Exception(f"Failed to publish deletion request: {str(e)}")
        
        # Iniciar timeout en background
        import asyncio
        asyncio.create_task(self._start_deletion_timeout(customer_id))
        
        return {
            "customer_id": customer_id,
            "status": "pending_deletion",
            "message": "Customer deletion validation initiated",
            "validation_timeout": self.validation_timeout,
            "expected_services": ["billing-service", "inventory-service"]
        }

    async def _broadcast_deletion_request(self, customer_id: str):
        """Enviar solicitud de eliminación a todos los servicios relevantes - VERSIÓN SÍNCRONA"""
        deletion_request_data = {
            "customer_id": customer_id,
            "requested_by": "accounts-service",
            "timestamp": datetime.utcnow().isoformat(),
            "action": "validate_customer_deletion"
        }
        
        try:
            print(f"[ACCOUNT] Broadcasting deletion request for customer {customer_id}")
            
            dapr_url = f"http://localhost:{settings.dapr_http_port}"
            pubsub_url = f"{dapr_url}/v1.0/publish/rabbitmq-pubsub/customer.deletion.request"
            
            headers = {
                "Content-Type": "application/json",
                "dapr-api-token": settings.dapr_api_token
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(pubsub_url, json=deletion_request_data, headers=headers)

            if response.status_code == 204:
                print(f"[ACCOUNT] Deletion request sent successfully")
            else:
                print(f"[ACCOUNT] Failed to send deletion request: {response.status_code}")
                raise Exception(f"HTTP {response.status_code}: {response.text}")
                
        except Exception as e:
            print(f"[ACCOUNT] Error broadcasting deletion request: {e}")
            raise e

    def process_deletion_response(self, customer_id: str, service_name: str, 
                                can_delete: bool, blocking_reason: str = None) -> Dict:
        """Procesar respuesta de validación de eliminación"""
        
        customer = self.db.query(Customer).filter(Customer.customer_id == customer_id).first()
        if not customer or customer.status != CustomerStatus.PENDING_DELETION:
            return {"success": False, "message": "Customer not in deletion process"}

        # Cargar respuestas existentes
        try:
            responses = json.loads(customer.deletion_responses or "{}")
        except:
            responses = {}

        # Agregar nueva respuesta
        responses[service_name] = {
            "can_delete": can_delete,
            "blocking_reason": blocking_reason,
            "validated_at": datetime.utcnow().isoformat()
        }

        customer.deletion_responses = json.dumps(responses)
        self.db.commit()

        print(f"[ACCOUNT] Response from {service_name}: can_delete={can_delete}")
        if blocking_reason:
            print(f"[ACCOUNT] Blocking Reason: {blocking_reason}")

        # Evaluar si ya tenemos todas las respuestas
        expected_services = {"billing-service", "inventory-service"}
        responded_services = set(responses.keys())

        print(f"[ACCOUNT] Responses received: {list(responded_services)}")
        print(f"[ACCOUNT] Expected services: {list(expected_services)}")

        if expected_services.issubset(responded_services):
            print(f"[ACCOUNT] All services responded, finalizing decision...")
            return self._finalize_deletion_decision(customer_id, responses)
        else:
            pending = expected_services - responded_services
            print(f"[ACCOUNT] Still waiting for: {list(pending)}")
            return {
                "success": True, 
                "message": f"Waiting for responses from: {list(pending)}",
                "pending_services": list(pending)
            }

    
    def get_deletion_status(self, customer_id: str) -> Dict:
        """Obtener estado actual del proceso de eliminación"""
        customer = self.db.query(Customer).filter(Customer.customer_id == customer_id).first()
        if not customer:
            return {"error": "Customer not found"}

        result = {
            "customer_id": customer_id,
            "status": customer.status,
            "deletion_requested_at": customer.deletion_requested_at.isoformat() if customer.deletion_requested_at else None
        }

        if customer.deletion_responses:
            try:
                result["validation_responses"] = json.loads(customer.deletion_responses)
            except:
                pass

        if customer.deletion_blocked_by:
            try:
                result["blocked_by"] = json.loads(customer.deletion_blocked_by)
            except:
                pass

        return result



    async def _start_deletion_timeout(self, customer_id: str):
        """Iniciar timeout para eliminación con tiempo de espera configurable"""
        print(f"[ACCOUNT] Setting deletion timeout for {customer_id}: {self.validation_timeout} seconds")
        
        try:
            # Esperar el tiempo de timeout
            await asyncio.sleep(self.validation_timeout)
            
            # Verificar si el cliente sigue en estado PENDING_DELETION
            customer = self.db.query(Customer).filter(Customer.customer_id == customer_id).first()
            
            if customer and customer.status == CustomerStatus.PENDING_DELETION.value:
                print(f"[ACCOUNT] [TIMEOUT] Timeout reached for customer {customer_id}")
                
                # Cargar respuestas recibidas hasta ahora
                try:
                    responses = json.loads(customer.deletion_responses or "{}")
                except:
                    responses = {}
                
                expected_services = {"billing-service", "inventory-service"}
                responded_services = set(responses.keys())
                
                # Servicios que no respondieron se consideran como "no bloquean"
                for service in expected_services - responded_services:
                    responses[service] = {
                        "can_delete": True,
                        "blocking_reason": None,
                        "validated_at": datetime.utcnow().isoformat(),
                        "timeout": True
                    }
                    print(f"[ACCOUNT] Service {service} assumed OK due to timeout")
                
                # Actualizar respuestas y finalizar decisión
                customer.deletion_responses = json.dumps(responses)
                self.db.commit()
                
                # Finalizar decisión con respuestas disponibles
                result = self._finalize_deletion_decision(customer_id, responses)
                print(f"[ACCOUNT] Timeout decision for {customer_id}: {result['decision']}")
            else:
                print(f"[ACCOUNT] No timeout needed for {customer_id} - already processed")
        
        except Exception as e:
            print(f"[ACCOUNT] Error in deletion timeout check: {e}")


    def _send_deletion_result_notification(self, customer_id: str, result_data: dict):
        """Enviar notificación del resultado final de eliminación"""
        try:
            notification_data = {
                "customer_id": customer_id,
                "deletion_result": result_data,
                "timestamp": datetime.utcnow().isoformat(),
                "notified_by": "accounts-service"
            }
            
            dapr_url = f"http://localhost:{settings.dapr_http_port}"
            pubsub_url = f"{dapr_url}/v1.0/publish/rabbitmq-pubsub/customer.deletion.result"
            
            headers = {
                "Content-Type": "application/json",
                "dapr-api-token": settings.dapr_api_token
            }
            
            response = requests.post(
                pubsub_url,
                json=notification_data,
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 204:
                print(f"[ACCOUNT] Deletion result notification sent for {customer_id}")
            else:
                print(f"[ACCOUNT] Failed to send deletion notification: {response.status_code}")
                
        except Exception as e:
            print(f"[ACCOUNT] Error sending deletion notification: {e}")



    def _finalize_deletion_decision(self, customer_id: str, responses: Dict) -> Dict:
        """Finalizar decisión de eliminación basada en todas las respuestas"""
        
        customer = self.db.query(Customer).filter(Customer.customer_id == customer_id).first()
        
        # Verificar si algún servicio bloquea la eliminación
        blocking_services = []
        for service, response in responses.items():
            if not response["can_delete"]:
                blocking_services.append({
                    "service": service,
                    "reason": response["blocking_reason"]
                })

        if blocking_services:
            # Cancelar eliminación
            customer.status = CustomerStatus.ACTIVE.value
            customer.deletion_requested_at = None
            customer.deletion_blocked_by = json.dumps(blocking_services)
            self.db.commit()
            
            print(f"[ACCOUNT] Deletion CANCELLED for customer {customer_id}")
            for block in blocking_services:
                print(f"   Blocked by {block['service']}: {block['reason']}")
            
            result = {
                "success": False,
                "decision": "deletion_cancelled",
                "customer_id": customer_id,
                "blocked_by": blocking_services,
                "message": f"Customer deletion blocked by {len(blocking_services)} service(s)"
            }
        else:
            # Proceder con eliminación
            customer.status = CustomerStatus.DELETED.value
            self.db.commit()
            
            print(f"[ACCOUNT] Customer {customer_id} DELETED successfully")
            
            result = {
                "success": True,
                "decision": "customer_deleted",
                "customer_id": customer_id,
                "message": "Customer successfully deleted after validation"
            }
        
        # Enviar notificación del resultado
        self._send_deletion_result_notification(customer_id, result)
        
        return result