from sqlalchemy.orm import Session
from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.invoice import InvoiceCreate
import uuid
from datetime import datetime

class InvoiceService:
    def __init__(self, db: Session):
        self.db = db
    
    def create_invoice(self, invoice_data: InvoiceCreate) -> Invoice:
        """Crear nueva factura en estado pendiente"""
        invoice_number = f"INV-{uuid.uuid4().hex[:8].upper()}"
        
        invoice = Invoice(
            invoice_number=invoice_number,
            product_id=invoice_data.product_id,
            quantity=invoice_data.quantity,
            customer_email=invoice_data.customer_email,
            status=InvoiceStatus.PENDING.value
        )
        
        self.db.add(invoice)
        self.db.commit()
        self.db.refresh(invoice)
        
        return invoice
    
    def update_invoice_status(self, invoice_id: int, status: InvoiceStatus, 
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