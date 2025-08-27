from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Database
    database_url: str = "sqlite:///./customers.db"
    
    # Dapr
    dapr_http_port: int = 3502
    dapr_api_token: str = "dapr-microservices-poc-token-2025"

    app_port: int = 8002

    class Config:
        env_file = ".env"

settings = Settings()