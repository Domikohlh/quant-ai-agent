"""
Main FastAPI application entry point.
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration

from backend.core.config.settings import settings
from backend.core.database import init_db, close_db
from backend.models.llm.manager import model_manager
from backend.utils.logging.logger import get_logger

logger = get_logger(__name__)


# Initialize Sentry for error tracking
if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        integrations=[FastApiIntegration()],
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifecycle manager for FastAPI application.
    Handles startup and shutdown events.
    """
    # Startup
    logger.info("Starting Quant AI API Server", environment=settings.environment)
    
    try:
        # Initialize database
        await init_db()
        logger.info("Database initialized")
        
        # Initialize model manager
        await model_manager.initialize()
        logger.info("Model manager initialized")
        
        # Start background tasks
        from backend.services.monitoring.news_monitor import start_news_monitoring
        from backend.services.monitoring.price_monitor import start_price_monitoring
        
        if settings.enable_news_monitoring:
            await start_news_monitoring()
            logger.info("News monitoring started")
        
        if settings.enable_price_alerts:
            await start_price_monitoring()
            logger.info("Price monitoring started")
        
        logger.info("✅ Application startup complete")
        
    except Exception as e:
        logger.error(f"Startup failed: {e}")
        raise
    
    yield
    
    # Shutdown
    logger.info("Shutting down Quant AI API Server")
    
    try:
        await model_manager.shutdown()
        await close_db()
        logger.info("✅ Application shutdown complete")
    except Exception as e:
        logger.error(f"Shutdown error: {e}")


# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    description="AI-powered quantitative finance assistant with dynamic model switching",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)


# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.is_development else ["https://yourdomain.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)


# Prometheus metrics endpoint
if settings.metrics_enabled:
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)


# Exception handlers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler."""
    logger.error(
        "Unhandled exception",
        path=request.url.path,
        method=request.method,
        error=str(exc),
        exc_info=True,
    )
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal server error",
            "message": str(exc) if settings.debug else "An error occurred",
            "path": request.url.path,
        },
    )


# Health check endpoints
@app.get("/health")
async def health_check():
    """Basic health check endpoint."""
    return {
        "status": "healthy",
        "environment": settings.environment,
        "version": "1.0.0",
    }


@app.get("/health/ready")
async def readiness_check():
    """Readiness check - verifies all dependencies are ready."""
    from backend.core.database import engine
    
    checks = {
        "database": False,
        "model": False,
        "redis": False,
    }
    
    # Check database
    try:
        async with engine.connect() as conn:
            await conn.execute("SELECT 1")
        checks["database"] = True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
    
    # Check model
    try:
        model_status = await model_manager.get_status()
        checks["model"] = model_status.is_active
    except Exception as e:
        logger.error(f"Model health check failed: {e}")
    
    # Check Redis
    try:
        from backend.core.cache import redis_client
        await redis_client.ping()
        checks["redis"] = True
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
    
    all_healthy = all(checks.values())
    
    return JSONResponse(
        status_code=status.HTTP_200_OK if all_healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "status": "ready" if all_healthy else "not ready",
            "checks": checks,
        },
    )


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "Quant AI API",
        "version": "1.0.0",
        "environment": settings.environment,
        "docs": "/docs",
        "health": "/health",
    }


# Import and include routers
from backend.api.routes import (
    auth,
    chat,
    trading,
    portfolio,
    backtest,
    news,
    alerts,
)

app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(chat.router, prefix="/api/v1/chat", tags=["Chat"])
app.include_router(trading.router, prefix="/api/v1/trading", tags=["Trading"])
app.include_router(portfolio.router, prefix="/api/v1/portfolio", tags=["Portfolio"])
app.include_router(backtest.router, prefix="/api/v1/backtest", tags=["Backtesting"])
app.include_router(news.router, prefix="/api/v1/news", tags=["News"])
app.include_router(alerts.router, prefix="/api/v1/alerts", tags=["Alerts"])


# Middleware to log requests
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all HTTP requests."""
    import time
    
    start_time = time.time()
    
    # Process request
    response = await call_next(request)
    
    # Calculate duration
    duration = time.time() - start_time
    
    # Log request
    logger.info(
        "HTTP request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration=f"{duration:.3f}s",
        client_ip=request.client.host if request.client else "unknown",
    )
    
    # Add custom headers
    response.headers["X-Process-Time"] = str(duration)
    response.headers["X-App-Version"] = "1.0.0"
    
    return response


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "backend.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.api_reload,
        workers=1 if settings.api_reload else settings.api_workers,
        log_level=settings.log_level.lower(),
    )
