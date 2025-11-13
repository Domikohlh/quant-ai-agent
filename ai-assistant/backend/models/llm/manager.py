"""
Model Manager: Handles dynamic switching between AWS and local models.
"""
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from enum import Enum

import httpx
from pydantic import BaseModel

from backend.core.config.settings import settings
from backend.utils.logging.logger import get_logger

logger = get_logger(__name__)


class ModelType(str, Enum):
    """Model types."""
    PRIMARY = "primary"
    LOCAL = "local"


class ModelStatus(BaseModel):
    """Model status information."""
    model_type: ModelType
    is_active: bool
    last_used: datetime
    total_requests: int
    avg_response_time: float


class ModelSwitchReason(str, Enum):
    """Reasons for model switching."""
    CRITICAL_NEWS = "critical_news"
    HIGH_VOLATILITY = "high_volatility"
    USER_REQUEST = "user_request"
    IDLE_TIMEOUT = "idle_timeout"
    AWS_UNAVAILABLE = "aws_unavailable"
    COST_OPTIMIZATION = "cost_optimization"


class ModelManager:
    """Manages dynamic switching between primary (AWS) and local models."""
    
    def __init__(self):
        self.current_model = ModelType.LOCAL
        self.last_switch_time = datetime.utcnow()
        self.last_request_time = datetime.utcnow()
        self.request_count = 0
        self.aws_available = False
        
        self.http_client = httpx.AsyncClient(
            timeout=60.0,
            headers={"X-API-Key": settings.model_server_api_key}
        )
        
        self._local_model = None
        self._local_tokenizer = None
        
        logger.info("ModelManager initialized", current_model=self.current_model)
    
    async def initialize(self) -> None:
        """Initialize the model manager."""
        await self._check_aws_availability()
        
        if settings.enable_rag:
            await self._load_local_model()
        
        asyncio.create_task(self._monitor_idle_timeout())
    
    async def _check_aws_availability(self) -> bool:
        """Check if AWS model server is available."""
        try:
            response = await self.http_client.get(
                f"{settings.model_server_url}/health",
                timeout=5.0
            )
            self.aws_available = response.status_code == 200
            logger.info("AWS model server check", available=self.aws_available)
            return self.aws_available
        except Exception as e:
            self.aws_available = False
            logger.warning(f"AWS model server unavailable: {e}")
            return False
    
    async def _load_local_model(self) -> None:
        """Load local model for fallback."""
        if self._local_model is not None:
            return
        
        try:
            import torch
            from transformers import AutoTokenizer, AutoModelForCausalLM
            
            logger.info("Loading local model", model=settings.local_model_name)
            
            self._local_tokenizer = AutoTokenizer.from_pretrained(
                settings.local_model_path,
                trust_remote_code=True,
            )
            
            self._local_model = AutoModelForCausalLM.from_pretrained(
                settings.local_model_path,
                torch_dtype=torch.float16,
                device_map="auto",
                load_in_4bit=True,
                trust_remote_code=True,
            )
            
            logger.info("Local model loaded successfully")
        
        except Exception as e:
            logger.error(f"Failed to load local model: {e}")
            self._local_model = None
    
    async def _monitor_idle_timeout(self) -> None:
        """Monitor idle time and switch to local model if idle."""
        while True:
            await asyncio.sleep(60)
            
            idle_time = datetime.utcnow() - self.last_request_time
            idle_minutes = idle_time.total_seconds() / 60
            
            if (
                self.current_model == ModelType.PRIMARY
                and idle_minutes > settings.idle_timeout_minutes
            ):
                logger.info("Switching to local model due to idle timeout", idle_minutes=idle_minutes)
                await self.switch_model(ModelType.LOCAL, ModelSwitchReason.IDLE_TIMEOUT)
    
    async def switch_model(self, target_model: ModelType, reason: ModelSwitchReason) -> bool:
        """Switch to a different model."""
        if self.current_model == target_model:
            return True
        
        logger.info("Switching model", from_model=self.current_model, to_model=target_model, reason=reason)
        
        if target_model == ModelType.PRIMARY:
            available = await self._check_aws_availability()
            if not available:
                logger.warning("Cannot switch to AWS model - unavailable")
                return False
        
        self.current_model = target_model
        self.last_switch_time = datetime.utcnow()
        
        logger.info("Model switched successfully", current_model=self.current_model)
        
        return True
    
    def should_use_primary_model(
        self,
        query_type: str,
        news_sentiment: Optional[float] = None,
        price_volatility: Optional[float] = None,
    ) -> bool:
        """Determine if primary (AWS) model should be used."""
        if query_type in ["trading", "portfolio_analysis", "backtest"]:
            return True
        
        if news_sentiment and news_sentiment >= settings.critical_news_threshold:
            return True
        
        if price_volatility and price_volatility >= settings.high_volatility_threshold:
            return True
        
        if query_type in ["chat", "simple_query"]:
            return False
        
        return self.current_model == ModelType.PRIMARY
    
    async def generate(
        self,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
        query_type: str = "chat",
        **kwargs
    ) -> Dict[str, Any]:
        """Generate text using appropriate model."""
        self.last_request_time = datetime.utcnow()
        self.request_count += 1
        
        should_use_primary = self.should_use_primary_model(
            query_type,
            kwargs.get("news_sentiment"),
            kwargs.get("price_volatility"),
        )
        
        target_model = ModelType.PRIMARY if should_use_primary else ModelType.LOCAL
        if target_model != self.current_model:
            await self.switch_model(target_model, ModelSwitchReason.USER_REQUEST)
        
        if self.current_model == ModelType.PRIMARY and self.aws_available:
            return await self._generate_aws(prompt, max_tokens, temperature, **kwargs)
        else:
            return await self._generate_local(prompt, max_tokens, temperature, **kwargs)
    
    async def _generate_aws(self, prompt: str, max_tokens: int, temperature: float, **kwargs) -> Dict[str, Any]:
        """Generate using AWS model."""
        try:
            response = await self.http_client.post(
                f"{settings.model_server_url}/generate",
                json={
                    "prompt": prompt,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    **kwargs
                }
            )
            response.raise_for_status()
            
            result = response.json()
            result["model_used"] = "primary"
            
            logger.info("AWS generation completed", tokens=result.get("tokens_generated"))
            
            return result
        
        except Exception as e:
            logger.error(f"AWS generation failed: {e}")
            self.aws_available = False
            await self.switch_model(ModelType.LOCAL, ModelSwitchReason.AWS_UNAVAILABLE)
            return await self._generate_local(prompt, max_tokens, temperature, **kwargs)
    
    async def _generate_local(self, prompt: str, max_tokens: int, temperature: float, **kwargs) -> Dict[str, Any]:
        """Generate using local model."""
        if self._local_model is None:
            await self._load_local_model()
        
        if self._local_model is None:
            raise RuntimeError("Local model not available")
        
        try:
            import torch
            
            start_time = datetime.utcnow()
            
            inputs = self._local_tokenizer(
                prompt,
                return_tensors="pt",
                truncation=True,
                max_length=settings.local_model_max_tokens - max_tokens,
            ).to(self._local_model.device)
            
            with torch.no_grad():
                outputs = self._local_model.generate(
                    **inputs,
                    max_new_tokens=max_tokens,
                    temperature=temperature,
                    do_sample=True,
                    top_p=kwargs.get("top_p", 0.9),
                    pad_token_id=self._local_tokenizer.pad_token_id,
                )
            
            generated_text = self._local_tokenizer.decode(
                outputs[0][inputs["input_ids"].shape[1]:],
                skip_special_tokens=True,
            )
            
            inference_time = (datetime.utcnow() - start_time).total_seconds()
            
            logger.info("Local generation completed", tokens=len(outputs[0]), time=inference_time)
            
            return {
                "text": generated_text,
                "tokens_generated": len(outputs[0]),
                "inference_time": inference_time,
                "model_used": "local",
                "model_name": settings.local_model_name,
            }
        
        except Exception as e:
            logger.error(f"Local generation failed: {e}")
            raise
    
    async def get_status(self) -> ModelStatus:
        """Get current model status."""
        return ModelStatus(
            model_type=self.current_model,
            is_active=True,
            last_used=self.last_request_time,
            total_requests=self.request_count,
            avg_response_time=0.0,
        )
    
    async def shutdown(self) -> None:
        """Cleanup resources."""
        await self.http_client.aclose()
        
        if self._local_model is not None:
            del self._local_model
            del self._local_tokenizer
            
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        
        logger.info("ModelManager shut down")


model_manager = ModelManager()
