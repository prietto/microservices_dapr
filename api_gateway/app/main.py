from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
import jwt
import requests
from datetime import datetime, timedelta
from typing import Dict, List

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

# Endpoints
from pydantic import BaseModel

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


from typing import Optional

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

@app.get("/health")
def health():
    return {"status": "healthy", "service": "api-gateway"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080, reload=False)