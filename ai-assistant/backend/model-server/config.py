from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Model configuration - Updated for GPT-OSS-20B
    MODEL_NAME: str = "openai/gpt-oss-20b"  # Or your specific model path
    MODEL_CACHE_DIR: str = "./model_cache"
    MAX_LENGTH: int = 2048
    DEVICE: str = "cuda"
    
    # GPT-OSS specific settings
    USE_QUANTIZATION: bool = True  # Highly recommended for 20B model
    QUANTIZATION_BITS: int = 4  # 4-bit or 8-bit
    
    # Generation settings optimized for GPT-OSS
    DEFAULT_TEMPERATURE: float = 0.7
    DEFAULT_TOP_P: float = 0.9
    DEFAULT_TOP_K: int = 50
    
    # Server configuration
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 1
    
    # Security
    API_KEY: str = "your-secret-api-key-here"
    
    # Hugging Face token (needed for gated models)
    HUGGINGFACE_TOKEN: str = ""  # Add your token if model is gated
    
    class Config:
        env_file = ".env"

settings = Settings()
