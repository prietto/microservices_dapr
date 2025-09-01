import uuid
from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session

from app.models.customer import Customer, CustomerCreate, CustomerUpdate, CustomerStatus

class CustomerService:
    def __init__(self, db: Session):
        self.db = db

    def get_customers(self, skip: int = 0, limit: int = 100) -> List[Customer]:
        """Obtener lista de clientes"""
        return self.db.query(Customer).offset(skip).limit(limit).all()

    def get_customer_by_id(self, customer_id: str) -> Optional[Customer]:
        """Obtener cliente por customer_id"""
        return self.db.query(Customer).filter(Customer.customer_id == customer_id).first()

    def get_customer_by_email(self, email: str) -> Optional[Customer]:
        """Obtener cliente por email"""
        return self.db.query(Customer).filter(Customer.email == email).first()

    def create_customer(self, customer_data) -> Customer:
        """Crear nuevo cliente - acepta CustomerCreate o dict"""
        
        # Si recibimos un dict, convertirlo a los campos necesarios
        if isinstance(customer_data, dict):
            email = customer_data.get("email", "")
            first_name = customer_data.get("name", "").split()[0] if customer_data.get("name") else "Unknown"
            last_name = " ".join(customer_data.get("name", "").split()[1:]) if customer_data.get("name") and len(customer_data.get("name", "").split()) > 1 else ""
            phone = customer_data.get("phone", "")
            address = customer_data.get("address", "")
            city = customer_data.get("city", "")
            country = customer_data.get("country", "")
            customer_id = customer_data.get("customer_id")  # Usar el customer_id que viene del billing
        else:
            # Es un objeto CustomerCreate
            email = customer_data.email
            first_name = customer_data.first_name
            last_name = customer_data.last_name
            phone = customer_data.phone
            address = customer_data.address
            city = customer_data.city
            country = customer_data.country
            customer_id = None  # Se generará automáticamente
        
        # Verificar email único
        if email:
            existing = self.get_customer_by_email(email)
            if existing:
                raise ValueError(f"Customer {existing.customer_id} with email {email} already exists")

        # Usar customer_id provisto o generar uno nuevo
        if not customer_id:
            customer_id = f"CUST-{uuid.uuid4().hex[:8].upper()}"
        
        db_customer = Customer(
            customer_id=customer_id,
            email=email,
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            address=address,
            city=city,
            country=country,
            status=CustomerStatus.ACTIVE
        )
        
        self.db.add(db_customer)
        self.db.commit()
        self.db.refresh(db_customer)
        
        print(f"[SUCCESS] Created customer {customer_id}: {first_name} {last_name}")
        return db_customer

    def update_customer(self, customer_id: str, customer_data: CustomerUpdate) -> Optional[Customer]:
        """Actualizar cliente"""
        db_customer = self.get_customer_by_id(customer_id)
        if not db_customer:
            return None

        # Verificar email único si cambia
        if customer_data.email and customer_data.email != db_customer.email:
            existing = self.get_customer_by_email(customer_data.email)
            if existing:
                raise ValueError(f"Email {customer_data.email} already exists")

        # Aplicar cambios
        update_data = customer_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(db_customer, field) and value is not None:
                setattr(db_customer, field, value)

        db_customer.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(db_customer)
        
        print(f"[UPDATE] Updated customer {customer_id}")
        return db_customer

    def delete_customer(self, customer_id: str) -> bool:
        """Eliminación directa (sin validación distribuida)"""
        db_customer = self.get_customer_by_id(customer_id)
        if not db_customer:
            return False

        db_customer.status = CustomerStatus.DELETED
        db_customer.updated_at = datetime.utcnow()
        self.db.commit()
        
        print(f"[DELETE] Deleted customer {customer_id}")
        return True