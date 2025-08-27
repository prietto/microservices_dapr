from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    project_name: str = "Billing Service"
    api_v1_str: str = "/api/v1"
    app_port: int = 8001
    dapr_http_port: int = 3501
    database_url: str = "sqlite:///./billing.db"
    dapr_api_token: str = "dapr-microservices-poc-token-2025"

    class Config:
        env_file = ".env"

settings = Settings()