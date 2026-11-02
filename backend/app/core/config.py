from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"
    database_url: str = "sqlite:///./ai_orchestra.db"
    frontend_origin: str = "http://localhost:8443"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
