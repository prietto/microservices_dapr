from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.customers import router as customers_router
from app.db.database import create_tables
from app.core.config import settings

# Crear tablas
create_tables()

app = FastAPI(
    title="Accounts Service (Customers)",
    description="Servicio de gestión de clientes con validación distribuida de eliminación",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(customers_router, prefix="/api/v1", tags=["customers"])

@app.get("/health")
def health():
    return {"status": "healthy", "service": "accounts-service"}

@app.get("/")
def root():
    return {"message": "Accounts Service - Customer Management", "version": "1.0.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.app_port)