"""
Centralized logging configuration with structured logging.
"""
import sys
import logging
from pathlib import Path
from typing import Any, Dict
from datetime import datetime
import structlog
from pythonjsonlogger import jsonlogger
from backend.core.config.settings import settings


def setup_logging() -> None:
    """Configure structured logging for the application."""
    
    # Create log directory
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer() if settings.log_format == "json"
            else structlog.dev.ConsoleRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    # Configure standard logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level.upper()),
    )
    
    # File handlers for different log types
    log_files = {
        "api": log_dir / "api" / f"{datetime.now().strftime('%Y-%m-%d')}.log",
        "trading": log_dir / "trading" / f"{datetime.now().strftime('%Y-%m-%d')}.log",
        "model": log_dir / "model" / f"{datetime.now().strftime('%Y-%m-%d')}.log",
        "errors": log_dir / "errors" / f"{datetime.now().strftime('%Y-%m-%d')}.log",
    }
    
    for log_type, log_file in log_files.items():
        log_file.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.INFO if log_type != "errors" else logging.ERROR)
        
        if settings.log_format == "json":
            formatter = jsonlogger.JsonFormatter(
                "%(timestamp)s %(level)s %(name)s %(message)s"
            )
        else:
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
        
        file_handler.setFormatter(formatter)
        logging.getLogger(log_type).addHandler(file_handler)


def get_logger(name: str) -> structlog.BoundLogger:
    """
    Get a configured logger instance.
    
    Args:
        name: Logger name (typically __name__)
    
    Returns:
        Configured structlog logger
    """
    return structlog.get_logger(name)


class LoggerMixin:
    """Mixin class to add logging capabilities to any class."""
    
    @property
    def logger(self) -> structlog.BoundLogger:
        """Get logger for this class."""
        if not hasattr(self, "_logger"):
            self._logger = get_logger(self.__class__.__name__)
        return self._logger
    
    def log_info(self, message: str, **kwargs: Any) -> None:
        """Log info message with context."""
        self.logger.info(message, **kwargs)
    
    def log_error(self, message: str, **kwargs: Any) -> None:
        """Log error message with context."""
        self.logger.error(message, **kwargs)
    
    def log_warning(self, message: str, **kwargs: Any) -> None:
        """Log warning message with context."""
        self.logger.warning(message, **kwargs)
    
    def log_debug(self, message: str, **kwargs: Any) -> None:
        """Log debug message with context."""
        self.logger.debug(message, **kwargs)


class HalluccinationLogger:
    """Specialized logger for tracking potential model hallucinations."""
    
    def __init__(self):
        self.logger = get_logger("hallucination")
        self.log_file = Path(settings.log_dir) / "model" / "hallucinations.jsonl"
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
    
    def log_potential_hallucination(
        self,
        query: str,
        response: str,
        confidence: float,
        detected_issues: list[str],
        context: Dict[str, Any],
    ) -> None:
        """
        Log a potential hallucination event.
        
        Args:
            query: User query
            response: Model response
            confidence: Model confidence score
            detected_issues: List of detected issues
            context: Additional context
        """
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "query": query,
            "response": response,
            "confidence": confidence,
            "issues": detected_issues,
            "context": context,
        }
        
        self.logger.warning(
            "Potential hallucination detected",
            **log_entry
        )
        
        # Write to dedicated hallucination log file
        with open(self.log_file, "a") as f:
            import json
            f.write(json.dumps(log_entry) + "\n")


class TradingLogger:
    """Specialized logger for trading activities."""
    
    def __init__(self):
        self.logger = get_logger("trading")
        self.log_file = Path(settings.log_dir) / "trading" / "trade_decisions.jsonl"
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
    
    def log_trade_signal(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: float,
        confidence: float,
        reasoning: str,
        indicators: Dict[str, Any],
    ) -> None:
        """
        Log a trade signal generation.
        
        Args:
            symbol: Stock symbol
            action: Trade action (buy/sell)
            quantity: Number of shares
            price: Price per share
            confidence: Signal confidence
            reasoning: AI reasoning for the trade
            indicators: Technical indicators used
        """
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "action": action,
            "quantity": quantity,
            "price": price,
            "confidence": confidence,
            "reasoning": reasoning,
            "indicators": indicators,
        }
        
        self.logger.info(
            f"Trade signal generated: {action} {quantity} {symbol} @ ${price}",
            **log_entry
        )
        
        with open(self.log_file, "a") as f:
            import json
            f.write(json.dumps(log_entry) + "\n")
    
    def log_trade_execution(
        self,
        trade_id: str,
        symbol: str,
        action: str,
        quantity: int,
        price: float,
        status: str,
        error: str = None,
    ) -> None:
        """Log trade execution result."""
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "trade_id": trade_id,
            "symbol": symbol,
            "action": action,
            "quantity": quantity,
            "price": price,
            "status": status,
            "error": error,
        }
        
        if status == "success":
            self.logger.info(
                f"Trade executed successfully: {action} {quantity} {symbol}",
                **log_entry
            )
        else:
            self.logger.error(
                f"Trade execution failed: {error}",
                **log_entry
            )


# Initialize logging on module import
setup_logging()

# Global logger instances
hallucination_logger = HalluccinationLogger()
trading_logger = TradingLogger()
