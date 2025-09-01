from sqlalchemy import create_engine, text
from app.core.config import settings
from app.db import Base

def run_migration():
    """Ejecutar migración para agregar nuevos campos de estado"""
    # Usar database_url (minúsculas) según el archivo config.py
    engine = create_engine(settings.database_url)
    
    # Verificar si las columnas ya existen
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(invoices)"))
        columns = [row[1] for row in result]
        
        # Agregar columnas si no existen
        if "customer_status" not in columns:
            conn.execute(text("ALTER TABLE invoices ADD COLUMN customer_status TEXT"))
            print("Added customer_status column")
            
        if "inventory_status" not in columns:
            conn.execute(text("ALTER TABLE invoices ADD COLUMN inventory_status TEXT"))
            print("Added inventory_status column")
            
        if "payment_status" not in columns:
            conn.execute(text("ALTER TABLE invoices ADD COLUMN payment_status TEXT"))
            print("Added payment_status column")
    
    print("Migration completed successfully")

if __name__ == "__main__":
    run_migration()