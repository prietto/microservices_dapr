from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.services.customer_service import CustomerService
from app.models.customer import CustomerCreate, CustomerUpdate, CustomerResponse, CustomerStatus, DeletionValidationResponse
from typing import List, Optional
import httpx
from app.core.config import settings
import asyncio
from datetime import datetime

router = APIRouter()

@router.post("/customers", response_model=CustomerResponse)
def create_customer(customer_data: CustomerCreate, db: Session = Depends(get_db)):
    """Crear nuevo cliente"""
    service = CustomerService(db)
    
    # Verificar si el email ya existe
    existing = service.get_customer_by_email(customer_data.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    customer = service.create_customer(customer_data)
    return customer

@router.get("/customers", response_model=List[CustomerResponse])
def get_customers(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    status: Optional[CustomerStatus] = Query(None),
    db: Session = Depends(get_db)
):
    """Obtener lista de clientes"""
    service = CustomerService(db)
    customers = service.get_customers(skip=skip, limit=limit, status=status)
    return customers

@router.get("/customers/{customer_id}", response_model=CustomerResponse)
def get_customer(customer_id: str, db: Session = Depends(get_db)):
    """Obtener cliente por ID"""
    service = CustomerService(db)
    customer = service.get_customer_by_id(customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer

@router.put("/customers/{customer_id}", response_model=CustomerResponse)
def update_customer(customer_id: str, customer_data: CustomerUpdate, db: Session = Depends(get_db)):
    """Actualizar cliente"""
    service = CustomerService(db)
    customer = service.update_customer(customer_id, customer_data)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer

@router.delete("/customers/{customer_id}")
async def delete_customer(customer_id: str, db: Session = Depends(get_db)):
    """
    Solicitar eliminación de cliente (inicia proceso de validación distribuido)
    """
    service = CustomerService(db)
    
    # Verificar que el cliente existe
    customer = service.get_customer_by_id(customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    if customer.status == CustomerStatus.DELETED:
        raise HTTPException(status_code=400, detail="Customer already deleted")
    
    if customer.status == CustomerStatus.PENDING_DELETION:
        raise HTTPException(status_code=400, detail="Customer deletion already in progress")
    
    try:
        # 1. Marcar cliente como pendiente de eliminación
        service.mark_for_deletion(customer_id)
        print(f"[ACCOUNTS] Customer {customer_id} marked for deletion")
        
        # 2. Publicar evento de solicitud de validación
        dapr_url = f"http://localhost:{settings.dapr_http_port}"
        pubsub_url = f"{dapr_url}/v1.0/publish/rabbitmq-pubsub/customer-deletion-request"
        
        event_data = {
            "customer_id": customer_id,
            "customer_email": customer.email,
            "customer_name": f"{customer.first_name} {customer.last_name}",
            "requested_at": datetime.utcnow().isoformat(),
            "requested_by": "accounts-service"
        }
        
        print(f"[ACCOUNTS] Publishing deletion validation request for {customer_id}")
        
        headers = {
            "dapr-api-token": settings.dapr_api_token,
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(pubsub_url, json=event_data, headers=headers)
        
        if response.status_code == 204:
            print(f"[ACCOUNTS] Deletion validation request published for customer {customer_id}")
            return {
                "message": "Customer deletion validation started",
                "customer_id": customer_id,
                "status": "pending_validation",
                "note": "Please check back in a few moments for validation results"
            }
        else:
            print(f"[ACCOUNTS] Failed to publish deletion request: {response.status_code} - {response.text}")
            raise HTTPException(status_code=500, detail="Failed to initiate deletion validation")
            
    except Exception as e:
        print(f"[ACCOUNTS] Error during deletion request: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/customers/{customer_id}/deletion-status")
def get_deletion_status(customer_id: str, db: Session = Depends(get_db)):
    """Verificar estado de eliminación de cliente"""
    service = CustomerService(db)
    customer = service.get_customer_by_id(customer_id)
    
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    blockers = service.get_deletion_blockers(customer_id)
    
    return {
        "customer_id": customer_id,
        "status": customer.status,
        "deletion_requested_at": customer.deletion_requested_at,
        "can_delete": customer.status == CustomerStatus.DELETED,
        "blocking_services": blockers if blockers else []
    }

# Endpoint para recibir validaciones de otros servicios
@router.post("/customer-deletion-validation")
async def handle_deletion_validation(event_data: dict, db: Session = Depends(get_db)):
    """Recibir respuesta de validación de eliminación de otros servicios"""
    try:
        print(f"[ACCOUNTS] Received deletion validation: {event_data}")
        
        data = event_data.get('data', event_data)
        
        validation = DeletionValidationResponse(
            service=data['service'],
            customer_id=data['customer_id'],
            can_delete=data['can_delete'],
            blocking_reason=data.get('blocking_reason'),
            blocking_details=data.get('blocking_details'),
            checked_at=datetime.fromisoformat(data['checked_at']) if 'checked_at' in data else datetime.utcnow()
        )
        
        service = CustomerService(db)
        
        # Por simplicidad, procesamos cada validación individualmente
        # En un sistema real, esperarías a recibir todas antes de decidir
        service.record_deletion_validation(validation.customer_id, [validation])
        
        print(f"[ACCOUNTS] Processed validation from {validation.service} for customer {validation.customer_id}")
        
        return {"message": "Validation processed successfully"}
        
    except Exception as e:
        print(f"[ACCOUNTS] Error processing deletion validation: {e}")
        raise HTTPException(status_code=500, detail=str(e))