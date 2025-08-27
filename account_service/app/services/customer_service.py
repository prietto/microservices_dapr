import asyncio
from datetime import datetime, timedelta
import json
from typing import Dict, List, Optional, Set
from app.models.customer import Customer, CustomerCreate, CustomerUpdate, CustomerStatus
from sqlalchemy.orm import Session

class CustomerService:
    def __init__(self, db: Session):
        self.db = db
        self.deletion_timeout_minutes = 5  # Configurar timeout

    def mark_for_deletion(self, customer_id: str) -> Optional[Customer]:
        """Marcar cliente para eliminación (inicia proceso de validación)"""
        db_customer = self.get_customer_by_id(customer_id)
        if not db_customer:
            return None
        
        if db_customer.status == CustomerStatus.DELETED:
            return db_customer
        
        now = datetime.utcnow()
        timeout_at = now + timedelta(minutes=self.deletion_timeout_minutes)
        
        db_customer.status = CustomerStatus.PENDING_DELETION
        db_customer.deletion_requested_at = now
        db_customer.deletion_timeout_at = timeout_at  # ← NUEVO
        db_customer.deletion_responses = json.dumps({})  # ← NUEVO
        db_customer.deletion_blocked_by = None
        db_customer.deletion_completed = False  # ← NUEVO
        
        self.db.commit()
        self.db.refresh(db_customer)
        return db_customer

    def add_deletion_response(self, customer_id: str, service_name: str, response_data: Dict) -> bool:
        """Agregar respuesta de un servicio al proceso de validación"""
        db_customer = self.get_customer_by_id(customer_id)
        if not db_customer or db_customer.deletion_completed:
            return False
        
        # Cargar respuestas existentes
        try:
            responses = json.loads(db_customer.deletion_responses or '{}')
        except json.JSONDecodeError:
            responses = {}
        
        # Agregar nueva respuesta
        responses[service_name] = {
            'can_delete': response_data['can_delete'],
            'blocking_reason': response_data.get('blocking_reason'),
            'blocking_details': response_data.get('blocking_details'),
            'responded_at': datetime.utcnow().isoformat()
        }
        
        db_customer.deletion_responses = json.dumps(responses)
        self.db.commit()
        
        print(f"[ACCOUNTS] Recorded response from {service_name} for customer {customer_id}: {'CAN DELETE' if response_data['can_delete'] else 'CANNOT DELETE'}")
        
        # Verificar si ya podemos tomar una decisión
        self._evaluate_deletion_decision(customer_id)
        return True

    def _evaluate_deletion_decision(self, customer_id: str) -> None:
        """Evaluar si ya se puede tomar decisión de eliminación"""
        db_customer = self.get_customer_by_id(customer_id)
        if not db_customer or db_customer.deletion_completed:
            return
        
        now = datetime.utcnow()
        
        # Cargar respuestas
        try:
            responses = json.loads(db_customer.deletion_responses or '{}')
        except json.JSONDecodeError:
            responses = {}
        
        # Lista de servicios que deben responder
        expected_services = {'billing-service', 'inventory-service', 'payment-service'}
        responded_services = set(responses.keys())
        
        # Verificar si hay objeciones inmediatas
        blocking_services = []
        for service, response in responses.items():
            if not response['can_delete']:
                blocking_services.append({
                    'service': service,
                    'reason': response.get('blocking_reason', 'Service blocked deletion'),
                    'details': response.get('blocking_details'),
                    'responded_at': response['responded_at']
                })
        
        # Si hay objeciones, bloquear inmediatamente
        if blocking_services:
            print(f"[ACCOUNTS] ❌ Customer {customer_id} CANNOT be deleted. Blocked by: {[b['service'] for b in blocking_services]}")
            self._finalize_deletion_decision(customer_id, can_delete=False, blocking_services=blocking_services)
            return
        
        # Si todos los servicios esperados respondieron positivamente
        if expected_services.issubset(responded_services):
            print(f"[ACCOUNTS] ✅ All services approved deletion of customer {customer_id}")
            self._finalize_deletion_decision(customer_id, can_delete=True, blocking_services=[])
            return
        
        # Si alcanzamos el timeout
        if now >= db_customer.deletion_timeout_at:
            missing_services = expected_services - responded_services
            print(f"[ACCOUNTS] ⏰ Timeout reached for customer {customer_id}. Missing responses from: {missing_services}")
            print(f"[ACCOUNTS] ✅ Proceeding with deletion due to timeout (silence = consent)")
            self._finalize_deletion_decision(customer_id, can_delete=True, blocking_services=[], timeout_reached=True)
            return
        
        # Aún esperando respuestas
        remaining_time = (db_customer.deletion_timeout_at - now).total_seconds()
        print(f"[ACCOUNTS] ⏳ Still waiting for responses. Time remaining: {remaining_time:.0f} seconds")

    def _finalize_deletion_decision(self, customer_id: str, can_delete: bool, blocking_services: List[Dict], timeout_reached: bool = False) -> None:
        """Finalizar decisión de eliminación"""
        db_customer = self.get_customer_by_id(customer_id)
        if not db_customer:
            return
        
        if can_delete:
            db_customer.status = CustomerStatus.DELETED
            db_customer.deletion_blocked_by = None
            print(f"[ACCOUNTS] ✅ Customer {customer_id} successfully deleted{'(by timeout)' if timeout_reached else ''}")
        else:
            db_customer.status = CustomerStatus.ACTIVE
            db_customer.deletion_blocked_by = json.dumps(blocking_services)
            print(f"[ACCOUNTS] ❌ Customer {customer_id} deletion blocked")
        
        db_customer.deletion_completed = True
        db_customer.updated_at = datetime.utcnow()
        self.db.commit()

    def check_pending_deletions_timeout(self) -> None:
        """Verificar timeouts de eliminaciones pendientes (ejecutar periódicamente)"""
        now = datetime.utcnow()
        
        pending_deletions = self.db.query(Customer).filter(
            Customer.status == CustomerStatus.PENDING_DELETION,
            Customer.deletion_completed == False,
            Customer.deletion_timeout_at <= now
        ).all()
        
        for customer in pending_deletions:
            print(f"[ACCOUNTS] ⏰ Processing timeout for customer {customer.customer_id}")
            self._evaluate_deletion_decision(customer.customer_id)

    def get_deletion_status_detailed(self, customer_id: str) -> Dict:
        """Obtener estado detallado de eliminación"""
        db_customer = self.get_customer_by_id(customer_id)
        if not db_customer:
            return None
        
        try:
            responses = json.loads(db_customer.deletion_responses or '{}')
        except json.JSONDecodeError:
            responses = {}
        
        try:
            blockers = json.loads(db_customer.deletion_blocked_by or '[]')
        except json.JSONDecodeError:
            blockers = []
        
        remaining_time = None
        if db_customer.deletion_timeout_at and not db_customer.deletion_completed:
            remaining_seconds = (db_customer.deletion_timeout_at - datetime.utcnow()).total_seconds()
            remaining_time = max(0, remaining_seconds)
        
        return {
            'customer_id': customer_id,
            'status': db_customer.status,
            'deletion_requested_at': db_customer.deletion_requested_at,
            'deletion_timeout_at': db_customer.deletion_timeout_at,
            'deletion_completed': db_customer.deletion_completed,
            'remaining_time_seconds': remaining_time,
            'can_delete': db_customer.status == CustomerStatus.DELETED,
            'responses_received': responses,
            'blocking_services': blockers,
            'expected_services': ['billing-service', 'inventory-service', 'payment-service'],
            'responded_services': list(responses.keys())
        }