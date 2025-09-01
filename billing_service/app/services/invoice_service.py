from sqlalchemy.orm import Session
from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.invoice import InvoiceCreate
import uuid
from datetime import datetime
from dapr.clients import DaprClient
from typing import Optional
import requests
from typing import List

DAPR_API_TOKEN = "dapr-microservices-poc-token-2025"
DAPR_HTTP_PORT = 3501  # Ajusta si usas otro puerto

class InvoiceService:
    def __init__(self, db: Session):
        self.db = db


    
    def get_invoices_by_customer(self, customer_id: str) -> List[Invoice]:
        """Obtener todas las facturas de un cliente específico"""
        return self.db.query(Invoice).filter(Invoice.customer_id == customer_id).all()
        
    async def update_customer_status(self, invoice_id: int, status: str) -> Invoice:
        """Actualizar solo el estado del cliente de una factura"""
        invoice = self.db.query(Invoice).filter(Invoice.id == invoice_id).first()
        
        if invoice:
            invoice.customer_status = status
            invoice.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(invoice)
        
        return invoice

    async def update_inventory_status(self, invoice_id: int, status: str) -> Invoice:
        """Actualizar solo el estado del inventario de una factura"""
        invoice = self.db.query(Invoice).filter(Invoice.id == invoice_id).first()
        
        if invoice:
            invoice.inventory_status = status
            invoice.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(invoice)
        
        return invoice

    async def update_payment_status(self, invoice_id: int, status: str) -> Invoice:
        """Actualizar solo el estado del pago de una factura"""
        invoice = self.db.query(Invoice).filter(Invoice.id == invoice_id).first()
        
        if invoice:
            invoice.payment_status = status
            invoice.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(invoice)
        
        return invoice

    
    async def ensure_customer_exists(self, customer_data: dict) -> dict:
        customer_id = customer_data["customer_id"]
        url = f"http://localhost:{DAPR_HTTP_PORT}/v1.0/invoke/accounts-service/method/api/v1/customers/{customer_id}"
        headers = {"dapr-api-token": DAPR_API_TOKEN}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json()
        # Si no existe, crearlo
        url_create = f"http://localhost:{DAPR_HTTP_PORT}/v1.0/invoke/accounts-service/method/api/v1/customers"
        response = requests.post(
            url_create,
            json=customer_data,
            headers={**headers, "Content-Type": "application/json"},
            timeout=10
        )
        if response.status_code not in (200, 201):
            raise Exception(f"Error creating customer: {response.text}")
        return response.json()

    async def create_invoice(self, invoice_data: InvoiceCreate) -> Invoice:
        """Crear nueva factura con todos los campos requeridos"""
        
        # Generar número de factura único
        invoice_number = f"INV-{uuid.uuid4().hex[:8].upper()}"
        
        # Crear instancia de Invoice asegurando que customer_id no sea None
        db_invoice = Invoice(
            invoice_number=invoice_number,
            customer_id=invoice_data.customer_id,  # Asegurar que se asigne
            customer_email=invoice_data.customer_email,
            product_id=invoice_data.product_id,
            quantity=invoice_data.quantity,
            status=InvoiceStatus.PENDING.value,
            unit_price=None,  # Se asignará después de verificación de inventario
            total_amount=None,
            notes="Invoice created - Verifying customer and inventory"
        )
        
        # Verificar que customer_id no sea None antes de guardar
        if not db_invoice.customer_id:
            raise ValueError("customer_id is required and cannot be None")
        
        self.db.add(db_invoice)
        self.db.commit()
        self.db.refresh(db_invoice)
        
        print(f"[INVOICE_SERVICE] Created invoice {db_invoice.invoice_number} for customer {db_invoice.customer_id}")
        return db_invoice
    

    async def _get_customer_from_accounts_service(self, customer_id: str) -> Optional[dict]:
        """Obtener datos del cliente desde account_service vía Dapr"""
        try:
            with DaprClient() as dapr:
                response = dapr.invoke_method(
                    app_id="accounts-service",
                    method_name=f"api/v1/customers/{customer_id}",
                    http_verb="GET"
                )
                print(f" Response getting customer {response}")
                
                if response.status_code == 200:
                    return response.json()
                    
        except Exception as e:
            print(f" Error getting customer {customer_id}: {e}")
        
        return None


    
    async def update_invoice_notes(self, invoice_id: int, notes: str) -> Invoice:
        """Actualizar solo las notas de una factura sin cambiar el estado"""
        invoice = self.db.query(Invoice).filter(Invoice.id == invoice_id).first()
        
        if invoice:
            # Concatenar notas existentes con las nuevas
            if invoice.notes:
                invoice.notes = f"{invoice.notes}; {notes}"
            else:
                invoice.notes = notes
                
            invoice.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(invoice)
        
        return invoice


    async def update_invoice_status(self, invoice_id: int, status: InvoiceStatus, 
                            unit_price: float = None, notes: str = None) -> Invoice:
        """Actualizar estado de la factura"""
        invoice = self.db.query(Invoice).filter(Invoice.id == invoice_id).first()
        
        if invoice:
            invoice.status = status.value
            invoice.updated_at = datetime.utcnow()
            
            if unit_price:
                invoice.unit_price = unit_price
                invoice.total_amount = unit_price * invoice.quantity
            
            if notes:
                invoice.notes = notes
            
            self.db.commit()
            self.db.refresh(invoice)
        
        return invoice
    
    def get_invoice_by_id(self, invoice_id: int) -> Invoice:
        """Obtener factura por ID"""
        return self.db.query(Invoice).filter(Invoice.id == invoice_id).first()
    
    def get_invoice_by_number(self, invoice_number: str) -> Invoice:
        """Obtener factura por número"""
        return self.db.query(Invoice).filter(Invoice.invoice_number == invoice_number).first()
    
    def get_invoices_by_status(self, status: InvoiceStatus) -> list:
        """Obtener facturas por estado"""
        return self.db.query(Invoice).filter(Invoice.status == status.value).all()
    
    def get_all_invoices(self) -> list:
        """Obtener todas las facturas"""
        return self.db.query(Invoice).all()