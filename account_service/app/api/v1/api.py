from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.db.database import get_db
from app.services.customer_service import CustomerService
from app.services.deletion_service import CustomerDeletionService
from app.models.customer import CustomerCreate, CustomerUpdate, CustomerResponse
from app.models.customer import Customer, CustomerStatus


router = APIRouter()

def get_customer_service(db: Session = Depends(get_db)) -> CustomerService:
    return CustomerService(db)

def get_deletion_service(db: Session = Depends(get_db)) -> CustomerDeletionService:
    return CustomerDeletionService(db)

# Endpoints básicos de clientes (ya existentes)
@router.get("/customers", response_model=List[CustomerResponse])
def get_customers(
    skip: int = 0,
    limit: int = 100,
    service: CustomerService = Depends(get_customer_service)
):
    """Obtener lista de clientes"""
    return service.get_customers(skip=skip, limit=limit)

@router.get("/customers/{customer_id}", response_model=CustomerResponse)
def get_customer(
    customer_id: str,
    service: CustomerService = Depends(get_customer_service)
):
    """Obtener cliente por ID - USADO POR OTROS SERVICIOS"""
    customer = service.get_customer_by_id(customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer

@router.post("/customers", response_model=CustomerResponse)
def create_customer(
    customer_data: CustomerCreate,
    service: CustomerService = Depends(get_customer_service)
):
    """Crear nuevo cliente"""
    try:
        return service.create_customer(customer_data)
    except ValueError as e:
        print('error ===> ',e)
        raise HTTPException(status_code=400, detail=str(e))

@router.put("/customers/{customer_id}", response_model=CustomerResponse)
def update_customer(
    customer_id: str,
    customer_data: CustomerUpdate,
    service: CustomerService = Depends(get_customer_service)
):
    """Actualizar cliente"""
    try:
        customer = service.update_customer(customer_id, customer_data)
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")
        return customer
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

# NUEVOS ENDPOINTS PARA ELIMINACIÓN DISTRIBUIDA

@router.delete("/customers/{customer_id}/request-deletion")
async def request_customer_deletion(
    customer_id: str,
    deletion_service: CustomerDeletionService = Depends(get_deletion_service)
):
    """🧪 LABORATORIO: Solicitar eliminación distribuida de cliente"""
    try:
        result = await deletion_service.request_customer_deletion(customer_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/customers/{customer_id}/deletion-response")
def receive_deletion_response(
    customer_id: str,
    service_name: str,
    can_delete: bool,
    blocking_reason: str = None,
    deletion_service: CustomerDeletionService = Depends(get_deletion_service)
):
    """Recibir respuesta de validación desde otros servicios"""
    result = deletion_service.process_deletion_response(
        customer_id, service_name, can_delete, blocking_reason
    )
    return result



@router.delete("/customers/{customer_id}")
async def delete_customer(customer_id: str, db: Session = Depends(get_db)):
    print('api account service => ')
    """Iniciar proceso de eliminación distribuida de cliente"""
    try:
        deletion_service = CustomerDeletionService(db)
        result = await deletion_service.request_customer_deletion(customer_id)
        print('result=> ',result)

        return result
        
    except ValueError as e:
        print('error api account => ',e)
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        print(f"[ACCOUNT] Error initiating deletion: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    


@router.get("/customers/{customer_id}/deletion-status")
async def get_deletion_status(customer_id: str, db: Session = Depends(get_db)):
    """Obtener estado del proceso de eliminación"""
    deletion_service = CustomerDeletionService(db)
    status = deletion_service.get_deletion_status(customer_id)
    
    if "error" in status:
        raise HTTPException(status_code=404, detail=status["error"])
    
    return status




@router.post("/customers/{customer_id}/reset-deletion")
async def reset_deletion_status(customer_id: str, db: Session = Depends(get_db)):
    """🔧 TEMPORAL: Resetear estado de eliminación para testing"""
    try:
        customer = db.query(Customer).filter(Customer.customer_id == customer_id).first()
        
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")
        
        # Resetear campos de eliminación
        customer.status = CustomerStatus.ACTIVE.value
        customer.deletion_requested_at = None
        customer.deletion_responses = None
        customer.deletion_blocked_by = None
        
        db.commit()
        
        print(f"[ACCOUNT] Reset deletion status for customer {customer_id}")
        
        return {
            "customer_id": customer_id,
            "message": "Deletion status reset successfully",
            "new_status": "active"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))