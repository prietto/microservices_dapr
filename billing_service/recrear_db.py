import os
from app.db import create_tables

# Eliminar la base de datos existente
db_path = "billing.db"
if os.path.exists(db_path):
    os.remove(db_path)
    print(f"[DB] Removed existing database: {db_path}")

# Crear nuevas tablas con el esquema actualizado
create_tables()
print("[DB] Created new database with updated schema")