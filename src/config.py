import os
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "sqlite:///./sno_state.db"
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Knowledge Nexus
    QDRANT_URL: str = "http://localhost:6333"
    NEO4J_URL: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "password"
    
    # LLM
    OPENAI_API_KEY: Optional[str] = None
    CLAUDE_API_KEY: Optional[str] = None
    
    # SNO Config
    LOG_LEVEL: str = "INFO"
    SNO_VERSION: str = "1.0.0-beta"

    class Config:
        env_file = ".env"

settings = Settings()
