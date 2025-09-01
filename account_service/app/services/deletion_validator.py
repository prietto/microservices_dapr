from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Dict

from app.db.database import get_db
from app.services.deletion_validator import CustomerDeletionValidator

router = APIRouter()

def get_deletion_validator(db: Session = Depends(get_db)) -> CustomerDeletionValidator:
    return CustomerDeletionValidator(db)

@router.get("/dapr/subscribe")
def get_subscriptions():
    """Endpoint requerido por Dapr para descubrir suscripciones"""
    return [
        {
            "pubsubname": "rabbitmq-pubsub",
            "topic": "customer.deletion.request",
            "route": "/api/v1/events/customer-deletion-request"
        }
    ]

@router.post("/events/customer-deletion-request")
async def handle_customer_deletion_request(
    event_data: Dict,
    validator: CustomerDeletionValidator = Depends(get_deletion_validator)
):
    """🧪 LABORATORIO: Manejar solicitud de eliminación de cliente"""
    customer_id = event_data.get('customer_id')
    
    if not customer_id:
        raise HTTPException(status_code=400, detail="Missing customer_id in event")
    
    print(f"📨 Received deletion request for customer: {customer_id}")
    
    try:
        result = await validator.validate_customer_deletion(customer_id)
        return result
    except Exception as e:
        print(f"❌ Error processing deletion validation: {e}")
        raise HTTPException(status_code=500, detail="Failed to process validation")