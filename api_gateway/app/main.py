from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
import jwt
import requests
from datetime import datetime, timedelta
from typing import Dict, List
from pydantic import BaseModel
from typing import Optional

# Agregar modelo para actualización de stock
class StockUpdateRequest(BaseModel):
    quantity: int
    operation: str  # "add" o "set" o "subtract"
    reason: Optional[str] = None

app = FastAPI(title="Microservices API Gateway with JWT", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer()

# Configuración
JWT_SECRET = "microservices-poc-jwt-secret-2025"
JWT_ALGORITHM = "HS256"
DAPR_API_TOKEN = "dapr-microservices-poc-token-2025"

# Usuarios demo
DEMO_USERS = {
    "admin@microservices.com": {
        "password": "admin123",
        "roles": ["admin", "billing"],
        "permissions": ["read:inventory", "write:billing", "read:payments"]
    },
    "billing@microservices.com": {
        "password": "billing123",
        "roles": ["billing"],
        "permissions": ["read:inventory", "write:billing"]
    },
    "customer@microservices.com": {
        "password": "customer123",
        "roles": ["customer"],
        "permissions": ["read:inventory"]
    }
}

def create_jwt_token(email: str, user_data: dict) -> str:
    payload = {
        "sub": email,
        "email": email,
        "roles": user_data["roles"],
        "permissions": user_data["permissions"],
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(hours=24),
        "iss": "microservices-api-gateway"
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def verify_jwt_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")



class LoginRequest(BaseModel):
    email: str
    password: str

@app.post("/auth/login")
def login(login_data: LoginRequest):
    user = DEMO_USERS.get(login_data.email.lower())
    if not user or user["password"] != login_data.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token = create_jwt_token(login_data.email, user)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"email": login_data.email, "roles": user["roles"], "permissions": user["permissions"]}
    }

@app.get("/auth/me")
def get_current_user(payload: dict = Depends(verify_jwt_token)):
    return {
        "email": payload["email"],
        "roles": payload["roles"],
        "permissions": payload["permissions"]
    }





@app.patch("/api/inventory/{item_id}/stock")
def update_item_stock(
    item_id: str,
    stock_data: StockUpdateRequest,
    payload: dict = Depends(verify_jwt_token)
):
    """Actualizar stock de un item específico"""
    # Verificar permisos - solo admin puede modificar stock
    if "admin" not in payload.get("roles", []):
        raise HTTPException(status_code=403, detail="Insufficient permissions - admin role required")
    
    try:
        # Preparar datos para enviar al inventory service
        update_data = {
            "quantity": stock_data.quantity,
            "operation": stock_data.operation,
            "reason": stock_data.reason or f"Stock updated by {payload['email']}",
            "updated_by": payload["email"]
        }
        
        url = f"http://localhost:3501/v1.0/invoke/inventory-service/method/api/v1/items/{item_id}/stock"
        
        response = requests.patch(
            url,
            json=update_data,
            headers={
                "dapr-api-token": DAPR_API_TOKEN,
                "Content-Type": "application/json"
            },
            timeout=10
        )
        
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Item '{item_id}' not found")
        elif response.status_code == 400:
            try:
                detail = response.json().get("detail", "Bad request")
            except Exception:
                detail = response.text or "Invalid stock operation"
            raise HTTPException(status_code=400, detail=detail)
        elif response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Service error")
            
        return response.json()
        
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Service unavailable: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.get("/api/inventory")
def get_inventory(
    item_id: Optional[str] = None,  # ← Parámetro opcional
    payload: dict = Depends(verify_jwt_token)
):
    if "read:inventory" not in payload.get("permissions", []):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        # Construir URL dinámicamente
        if item_id:
            # Para item específico
            url = f"http://localhost:3501/v1.0/invoke/inventory-service/method/api/v1/items/{item_id}"
        else:
            # Para todos los items
            url = "http://localhost:3501/v1.0/invoke/inventory-service/method/api/v1/items"
        
        response = requests.get(
            url,
            headers={"dapr-api-token": DAPR_API_TOKEN},
            timeout=10
        )
        
        # Verificar si el response es exitoso
        if response.status_code == 404 and item_id:
            raise HTTPException(status_code=404, detail=f"Item '{item_id}' not found")
        elif response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Service error")
            
        return response.json()
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Service unavailable: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.post("/api/invoices")
def create_invoice(invoice_data: dict, payload: dict = Depends(verify_jwt_token)):
    if "write:billing" not in payload.get("permissions", []):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    invoice_data["created_by"] = payload["email"]
    

    try:
        response = requests.post(
            "http://localhost:3501/v1.0/invoke/billing-service/method/api/v1/create-invoice",
            json=invoice_data,
            headers={
                "dapr-api-token": DAPR_API_TOKEN,
                "Content-Type": "application/json"
            },
            timeout=30
        )
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Service unavailable: {str(e)}")




@app.get("/api/customers")
def get_customers(payload: dict = Depends(verify_jwt_token)):
    if "admin" not in payload.get("roles", []) and "billing" not in payload.get("roles", []):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    try:
        url = "http://localhost:3501/v1.0/invoke/accounts-service/method/api/v1/customers"
        response = requests.get(
            url,
            headers={"dapr-api-token": DAPR_API_TOKEN},
            timeout=10
        )
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Service error")
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Service unavailable: {str(e)}")

@app.get("/api/customers/{customer_id}")
def get_customer(customer_id: str, payload: dict = Depends(verify_jwt_token)):
    if "admin" not in payload.get("roles", []) and "billing" not in payload.get("roles", []):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    try:
        url = f"http://localhost:3501/v1.0/invoke/accounts-service/method/api/v1/customers/{customer_id}"
        response = requests.get(
            url,
            headers={"dapr-api-token": DAPR_API_TOKEN},
            timeout=10
        )
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="Customer not found")
        elif response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Service error")
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Service unavailable: {str(e)}")

@app.post("/api/customers")
def create_customer(customer_data: dict, payload: dict = Depends(verify_jwt_token)):
    if "admin" not in payload.get("roles", []):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    url = "http://localhost:3501/v1.0/invoke/accounts-service/method/api/v1/customers"
    try:
        response = requests.post(
            url,
            json=customer_data,
            headers={
                "dapr-api-token": DAPR_API_TOKEN,
                "Content-Type": "application/json"
            },
            timeout=10
        )
        
        if response.status_code == 400:
            try:
                detail = response.json().get("detail", "Bad request")
            except Exception:
                detail = response.text or "Bad request"
            raise HTTPException(status_code=400, detail=detail)
        elif response.status_code != 200 and response.status_code != 201:
            raise HTTPException(status_code=response.status_code, detail="Service error")
        return response.json()
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Service unavailable: {str(e)}")
    
    
@app.delete("/api/customers/{customer_id}/request-deletion")
def request_customer_deletion(customer_id: str, payload: dict = Depends(verify_jwt_token)):
    if "admin" not in payload.get("roles", []):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    try:
        url = f"http://localhost:3501/v1.0/invoke/accounts-service/method/api/v1/customers/{customer_id}/request-deletion"
        response = requests.delete(
            url,
            headers={"dapr-api-token": DAPR_API_TOKEN},
            timeout=10
        )
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Service error")
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Service unavailable: {str(e)}")

@app.get("/api/customers/{customer_id}/deletion-status")
def get_deletion_status(customer_id: str, payload: dict = Depends(verify_jwt_token)):
    if "admin" not in payload.get("roles", []):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    try:
        url = f"http://localhost:3501/v1.0/invoke/accounts-service/method/api/v1/customers/{customer_id}/deletion-status"
        response = requests.get(
            url,
            headers={"dapr-api-token": DAPR_API_TOKEN},
            timeout=10
        )
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Service error")
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Service unavailable: {str(e)}")



@app.delete("/api/customers/{customer_id}")
def delete_customer(customer_id: str, payload: dict = Depends(verify_jwt_token)):
    """Eliminar cliente con validación distribuida"""
    if "admin" not in payload.get("roles", []):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        url = f"http://localhost:3501/v1.0/invoke/accounts-service/method/api/v1/customers/{customer_id}"
        response = requests.delete(
            url,
            headers={"dapr-api-token": DAPR_API_TOKEN},
            timeout=30  # Timeout más largo para proceso distribuido
        )

        print('response=> ',response)
        
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="Customer not found")
        elif response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Service error")
            
        return response.json()
        
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=503, detail=f"Service unavailable: {str(e)}")




@app.post("/api/customers/{customer_id}/reset-deletion")
def reset_customer_deletion_status(customer_id: str, payload: dict = Depends(verify_jwt_token)):
    """🔧 TEMPORAL: Resetear estado de eliminación para testing"""
    if "admin" not in payload.get("roles", []):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        url = f"http://localhost:3501/v1.0/invoke/accounts-service/method/api/v1/customers/{customer_id}/reset-deletion"
        response = requests.post(
            url,
            headers={"dapr-api-token": DAPR_API_TOKEN},
            timeout=10
        )
        
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="Customer not found")
        elif response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Service error")
            
        return response.json()
        
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Service unavailable: {str(e)}")



@app.get("/health")
def health():
    return {"status": "healthy", "service": "api-gateway"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080, reload=False)