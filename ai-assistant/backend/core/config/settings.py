"""
Application configuration settings loaded from environment variables.
"""
from typing import Optional, List
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Main application settings."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # Application
    app_name: str = "quant_ai"
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"
    
    # API Server
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_workers: int = 4
    api_reload: bool = True
    
    # Security
    secret_key: str = Field(..., min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    
    # Database
    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    database_url: str
    
    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: Optional[str] = None
    redis_url: str
    
    # AWS
    aws_region: str = "us-east-1"
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    s3_bucket_name: Optional[str] = None
    s3_logs_prefix: str = "logs/"
    s3_models_prefix: str = "models/"
    
    # Model Server
    model_server_url: str
    model_server_api_key: Optional[str] = None
    
    # Primary Model (AWS)
    primary_model_name: str = "gpt-oss-20b"
    primary_model_path: str = "/models/gpt-oss-20b"
    primary_model_max_tokens: int = 4096
    primary_model_temperature: float = 0.7
    
    # Local Model
    local_model_name: str = "llama-3.2-3b-instruct"
    local_model_path: str = "/models/llama-3.2-3b-instruct"
    local_model_quantization: str = "4bit"
    local_model_max_tokens: int = 2048
    
    # Model Switching
    idle_timeout_minutes: int = 30
    critical_news_threshold: float = 0.8
    price_change_threshold: float = 2.0
    high_volatility_threshold: float = 3.0
    
    # RAG
    chroma_persist_dir: str = "./data/vectors"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dimension: int = 384
    rag_top_k: int = 5
    rag_chunk_size: int = 512
    rag_chunk_overlap: int = 50
    
    # Alpaca
    alpaca_api_key: str
    alpaca_secret_key: str
    alpaca_base_url: str = "https://paper-api.alpaca.markets"
    alpaca_data_url: str = "https://data.alpaca.markets"
    
    # Interactive Brokers
    ib_host: str = "127.0.0.1"
    ib_port: int = 7497
    ib_client_id: int = 1
    ib_account: Optional[str] = None
    ib_timeout: int = 30
    
    # Google News API
    google_api_key: str
    google_cx: str
    news_fetch_interval_minutes: int = 5
    news_max_results: int = 10
    
    # Trading Configuration
    paper_trading_enabled: bool = True
    paper_initial_capital: float = 100000.0
    paper_commission: float = 0.0
    
    # Risk Management
    max_position_size: float = 0.1
    max_daily_loss: float = 0.05
    max_portfolio_risk: float = 0.15
    stop_loss_percent: float = 0.02
    
    # Backtesting
    backtest_start_date: str = "2019-01-01"
    backtest_end_date: str = "2024-01-31"
    backtest_initial_capital: float = 100000.0
    backtest_commission: float = 0.0
    
    # Strategy Parameters
    strategy_evaluation_days: int = 30
    min_sharpe_ratio: float = 1.5
    min_win_rate: float = 0.55
    max_drawdown_threshold: float = 0.20
    
    # Monitoring
    price_check_interval_seconds: int = 60
    price_alert_threshold: float = 2.0
    price_websocket_enabled: bool = True
    news_sentiment_threshold: float = 0.7
    critical_news_keywords: str = "bankruptcy,fraud,lawsuit,investigation,recall,scandal,crash"
    default_watchlist: str = "AAPL,MSFT,GOOGL,AMZN,TSLA,NVDA,META,SPY,QQQ"
    
    # Human-in-the-Loop
    hitl_enabled: bool = True
    hitl_timeout_minutes: int = 60
    hitl_notification_channels: str = "push,email"
    auto_approve_threshold: float = 0.95
    
    # Notifications
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    alert_email: Optional[str] = None
    
    # APNs (iOS Push Notifications)
    apns_key_id: Optional[str] = None
    apns_team_id: Optional[str] = None
    apns_bundle_id: Optional[str] = None
    apns_key_path: Optional[str] = None
    apns_use_sandbox: bool = True
    
    # Celery
    celery_broker_url: str
    celery_result_backend: str
    celery_task_serializer: str = "json"
    celery_result_serializer: str = "json"
    celery_accept_content: List[str] = ["json"]
    celery_timezone: str = "America/New_York"
    celery_enable_utc: bool = True
    
    # Logging
    log_dir: str = "./data/logs"
    log_rotation: str = "daily"
    log_retention_days: int = 90
    log_format: str = "json"
    
    # Sentry
    sentry_dsn: Optional[str] = None
    sentry_environment: Optional[str] = None
    sentry_traces_sample_rate: float = 0.1
    
    # Prometheus
    prometheus_port: int = 9090
    metrics_enabled: bool = True
    
    # Feature Flags
    enable_rag: bool = True
    enable_paper_trading: bool = True
    enable_live_trading: bool = False
    enable_portfolio_analysis: bool = True
    enable_news_monitoring: bool = True
    enable_price_alerts: bool = True
    enable_backtesting: bool = True
    enable_hallucination_detection: bool = True
    
    # Development
    mock_ib_api: bool = False
    mock_alpaca_api: bool = False
    mock_model_server: bool = False
    seed_database: bool = False
    
    @field_validator("critical_news_keywords")
    @classmethod
    def parse_keywords(cls, v: str) -> List[str]:
        """Parse comma-separated keywords into list."""
        return [k.strip().lower() for k in v.split(",")]
    
    @field_validator("default_watchlist")
    @classmethod
    def parse_watchlist(cls, v: str) -> List[str]:
        """Parse comma-separated symbols into list."""
        return [s.strip().upper() for s in v.split(",")]
    
    @property
    def is_production(self) -> bool:
        """Check if running in production."""
        return self.environment.lower() == "production"
    
    @property
    def is_development(self) -> bool:
        """Check if running in development."""
        return self.environment.lower() == "development"


# Global settings instance
settings = Settings()
