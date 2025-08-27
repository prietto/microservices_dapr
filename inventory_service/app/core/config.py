from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # Database
    database_url: str = "sqlite:///./inventory.db"
    
    # Dapr
    dapr_http_port: int = 3500
    dapr_grpc_port: int = 50001
    app_port: int = 8000
    
    # RabbitMQ
    rabbitmq_host: str = "localhost"
    rabbitmq_port: int = 5672
    rabbitmq_username: str = "guest"
    rabbitmq_password: str = "guest"
    
    # Inventory
    low_stock_threshold: int = 10
    
    # API
    api_v1_str: str = "/api/v1"
    project_name: str = "Inventory Service"

    dapr_api_token: str = "your_dapr_api_token"

    class Config:
        env_file = ".env"

settings = Settings()