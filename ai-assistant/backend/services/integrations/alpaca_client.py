"""
Alpaca API Client for market data and trading.
Handles stock prices, historical data, and order execution.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from decimal import Decimal

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    GetOrdersRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame

from backend.core.config.settings import settings
from backend.utils.logging.logger import get_logger

logger = get_logger(__name__)


class AlpacaClient:
    """
    Alpaca API client for market data and trading operations.
    
    Features:
    - Real-time and historical market data
    - Paper trading and live trading
    - Portfolio management
    - Order execution with paper trading validation
    """
    
    def __init__(self):
        """Initialize Alpaca clients."""
        # Trading client (for orders, positions, account)
        self.trading_client = TradingClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
            paper=settings.paper_trading_enabled,
        )
        
        # Data client (for market data)
        self.data_client = StockHistoricalDataClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
        )
        
        self.is_paper_trading = settings.paper_trading_enabled
        
        logger.info(
            "Alpaca client initialized",
            paper_trading=self.is_paper_trading,
            base_url=settings.alpaca_base_url
        )
    
    # ==================
    # Account Information
    # ==================
    
    async def get_account(self) -> Dict[str, Any]:
        """
        Get account information.
        
        Returns:
            Account details including buying power, equity, etc.
        """
        try:
            account = self.trading_client.get_account()
            
            account_data = {
                "account_number": account.account_number,
                "status": account.status,
                "currency": account.currency,
                "buying_power": float(account.buying_power),
                "cash": float(account.cash),
                "portfolio_value": float(account.portfolio_value),
                "equity": float(account.equity),
                "last_equity": float(account.last_equity),
                "initial_margin": float(account.initial_margin),
                "maintenance_margin": float(account.maintenance_margin),
                "daytrade_count": account.daytrade_count,
                "daytrading_buying_power": float(account.daytrading_buying_power),
                "regt_buying_power": float(account.regt_buying_power),
            }
            
            logger.info(
                "Retrieved account info",
                portfolio_value=account_data["portfolio_value"],
                buying_power=account_data["buying_power"]
            )
            
            return account_data
        
        except Exception as e:
            logger.error(f"Failed to get account info: {e}")
            raise
    
    # ==================
    # Market Data
    # ==================
    
    async def get_latest_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Get latest quote for a symbol.
        
        Args:
            symbol: Stock symbol (e.g., 'AAPL')
        
        Returns:
            Latest bid/ask prices and sizes
        """
        try:
            request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
            quotes = self.data_client.get_stock_latest_quote(request)
            
            quote = quotes[symbol]
            
            quote_data = {
                "symbol": symbol,
                "ask_price": float(quote.ask_price),
                "ask_size": quote.ask_size,
                "bid_price": float(quote.bid_price),
                "bid_size": quote.bid_size,
                "timestamp": quote.timestamp.isoformat(),
            }
            
            logger.debug(f"Latest quote for {symbol}", **quote_data)
            
            return quote_data
        
        except Exception as e:
            logger.error(f"Failed to get quote for {symbol}: {e}")
            raise
    
    async def get_historical_bars(
        self,
        symbol: str,
        timeframe: str = "1Day",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get historical price bars.
        
        Args:
            symbol: Stock symbol
            timeframe: Bar timeframe (1Min, 5Min, 15Min, 1Hour, 1Day)
            start: Start datetime
            end: End datetime
            limit: Maximum number of bars
        
        Returns:
            List of price bars with OHLCV data
        """
        try:
            # Set default date range if not provided
            if not end:
                end = datetime.now()
            if not start:
                start = end - timedelta(days=30)
            
            # Map timeframe string to Alpaca TimeFrame
            timeframe_map = {
                "1Min": TimeFrame.Minute,
                "5Min": TimeFrame(5, "Min"),
                "15Min": TimeFrame(15, "Min"),
                "1Hour": TimeFrame.Hour,
                "1Day": TimeFrame.Day,
            }
            
            tf = timeframe_map.get(timeframe, TimeFrame.Day)
            
            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=tf,
                start=start,
                end=end,
                limit=limit
            )
            
            bars = self.data_client.get_stock_bars(request)
            
            # Convert to list of dicts
            bars_data = []
            for bar in bars[symbol]:
                bars_data.append({
                    "timestamp": bar.timestamp.isoformat(),
                    "open": float(bar.open),
                    "high": float(bar.high),
                    "low": float(bar.low),
                    "close": float(bar.close),
                    "volume": bar.volume,
                    "vwap": float(bar.vwap) if bar.vwap else None,
                })
            
            logger.info(
                f"Retrieved {len(bars_data)} bars for {symbol}",
                timeframe=timeframe,
                start=start.isoformat(),
                end=end.isoformat()
            )
            
            return bars_data
        
        except Exception as e:
            logger.error(f"Failed to get historical bars for {symbol}: {e}")
            raise
    
    # ==================
    # Positions
    # ==================
    
    async def get_positions(self) -> List[Dict[str, Any]]:
        """
        Get all open positions.
        
        Returns:
            List of position details
        """
        try:
            positions = self.trading_client.get_all_positions()
            
            positions_data = []
            for pos in positions:
                positions_data.append({
                    "symbol": pos.symbol,
                    "qty": float(pos.qty),
                    "side": "long" if float(pos.qty) > 0 else "short",
                    "market_value": float(pos.market_value),
                    "cost_basis": float(pos.cost_basis),
                    "unrealized_pl": float(pos.unrealized_pl),
                    "unrealized_plpc": float(pos.unrealized_plpc),
                    "current_price": float(pos.current_price),
                    "avg_entry_price": float(pos.avg_entry_price),
                })
            
            logger.info(f"Retrieved {len(positions_data)} positions")
            
            return positions_data
        
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            raise
    
    async def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get position for a specific symbol.
        
        Args:
            symbol: Stock symbol
        
        Returns:
            Position details or None if no position
        """
        try:
            position = self.trading_client.get_open_position(symbol)
            
            position_data = {
                "symbol": position.symbol,
                "qty": float(position.qty),
                "side": "long" if float(position.qty) > 0 else "short",
                "market_value": float(position.market_value),
                "cost_basis": float(position.cost_basis),
                "unrealized_pl": float(position.unrealized_pl),
                "unrealized_plpc": float(position.unrealized_plpc),
                "current_price": float(position.current_price),
                "avg_entry_price": float(position.avg_entry_price),
            }
            
            logger.debug(f"Retrieved position for {symbol}", **position_data)
            
            return position_data
        
        except Exception as e:
            # Position not found is not an error
            if "position does not exist" in str(e).lower():
                return None
            logger.error(f"Failed to get position for {symbol}: {e}")
            raise
    
    # ==================
    # Order Management
    # ==================
    
    async def place_market_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        time_in_force: str = "day"
    ) -> Dict[str, Any]:
        """
        Place a market order.
        
        Args:
            symbol: Stock symbol
            qty: Quantity of shares
            side: 'buy' or 'sell'
            time_in_force: Order duration (day, gtc, ioc, fok)
        
        Returns:
            Order details
        """
        try:
            # Validate side
            order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
            
            # Map time in force
            tif_map = {
                "day": TimeInForce.DAY,
                "gtc": TimeInForce.GTC,
                "ioc": TimeInForce.IOC,
                "fok": TimeInForce.FOK,
            }
            tif = tif_map.get(time_in_force.lower(), TimeInForce.DAY)
            
            # Create order request
            order_request = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=order_side,
                time_in_force=tif,
            )
            
            # Submit order
            order = self.trading_client.submit_order(order_request)
            
            order_data = {
                "id": str(order.id),
                "symbol": order.symbol,
                "qty": float(order.qty),
                "side": order.side.value,
                "type": order.type.value,
                "time_in_force": order.time_in_force.value,
                "status": order.status.value,
                "filled_qty": float(order.filled_qty) if order.filled_qty else 0,
                "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,
                "submitted_at": order.submitted_at.isoformat() if order.submitted_at else None,
            }
            
            logger.info(
                f"Market order placed: {side} {qty} {symbol}",
                order_id=order_data["id"],
                paper_trading=self.is_paper_trading
            )
            
            return order_data
        
        except Exception as e:
            logger.error(f"Failed to place market order: {e}")
            raise
    
    async def place_limit_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        limit_price: float,
        time_in_force: str = "day"
    ) -> Dict[str, Any]:
        """
        Place a limit order.
        
        Args:
            symbol: Stock symbol
            qty: Quantity of shares
            side: 'buy' or 'sell'
            limit_price: Limit price
            time_in_force: Order duration
        
        Returns:
            Order details
        """
        try:
            order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
            
            tif_map = {
                "day": TimeInForce.DAY,
                "gtc": TimeInForce.GTC,
                "ioc": TimeInForce.IOC,
                "fok": TimeInForce.FOK,
            }
            tif = tif_map.get(time_in_force.lower(), TimeInForce.DAY)
            
            order_request = LimitOrderRequest(
                symbol=symbol,
                qty=qty,
                side=order_side,
                time_in_force=tif,
                limit_price=limit_price,
            )
            
            order = self.trading_client.submit_order(order_request)
            
            order_data = {
                "id": str(order.id),
                "symbol": order.symbol,
                "qty": float(order.qty),
                "side": order.side.value,
                "type": order.type.value,
                "limit_price": float(order.limit_price) if order.limit_price else None,
                "time_in_force": order.time_in_force.value,
                "status": order.status.value,
                "filled_qty": float(order.filled_qty) if order.filled_qty else 0,
                "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,
                "submitted_at": order.submitted_at.isoformat() if order.submitted_at else None,
            }
            
            logger.info(
                f"Limit order placed: {side} {qty} {symbol} @ ${limit_price}",
                order_id=order_data["id"],
                paper_trading=self.is_paper_trading
            )
            
            return order_data
        
        except Exception as e:
            logger.error(f"Failed to place limit order: {e}")
            raise
    
    async def get_orders(
        self,
        status: str = "all",
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get orders by status.
        
        Args:
            status: Order status filter (open, closed, all)
            limit: Maximum number of orders
        
        Returns:
            List of orders
        """
        try:
            status_map = {
                "open": QueryOrderStatus.OPEN,
                "closed": QueryOrderStatus.CLOSED,
                "all": QueryOrderStatus.ALL,
            }
            
            request = GetOrdersRequest(
                status=status_map.get(status, QueryOrderStatus.ALL),
                limit=limit,
            )
            
            orders = self.trading_client.get_orders(request)
            
            orders_data = []
            for order in orders:
                orders_data.append({
                    "id": str(order.id),
                    "symbol": order.symbol,
                    "qty": float(order.qty),
                    "side": order.side.value,
                    "type": order.type.value,
                    "status": order.status.value,
                    "filled_qty": float(order.filled_qty) if order.filled_qty else 0,
                    "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,
                    "limit_price": float(order.limit_price) if order.limit_price else None,
                    "submitted_at": order.submitted_at.isoformat() if order.submitted_at else None,
                    "filled_at": order.filled_at.isoformat() if order.filled_at else None,
                })
            
            logger.info(f"Retrieved {len(orders_data)} orders", status=status)
            
            return orders_data
        
        except Exception as e:
            logger.error(f"Failed to get orders: {e}")
            raise
    
    async def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an order.
        
        Args:
            order_id: Order ID to cancel
        
        Returns:
            True if cancelled successfully
        """
        try:
            self.trading_client.cancel_order_by_id(order_id)
            
            logger.info(f"Order cancelled", order_id=order_id)
            
            return True
        
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            raise
    
    async def cancel_all_orders(self) -> int:
        """
        Cancel all open orders.
        
        Returns:
            Number of orders cancelled
        """
        try:
            cancelled = self.trading_client.cancel_orders()
            
            count = len(cancelled)
            
            logger.info(f"Cancelled {count} orders")
            
            return count
        
        except Exception as e:
            logger.error(f"Failed to cancel all orders: {e}")
            raise
    
    # ==================
    # Helper Methods
    # ==================
    
    async def is_market_open(self) -> bool:
        """
        Check if the market is currently open.
        
        Returns:
            True if market is open
        """
        try:
            clock = self.trading_client.get_clock()
            return clock.is_open
        
        except Exception as e:
            logger.error(f"Failed to get market status: {e}")
            raise
    
    async def get_market_hours(self) -> Dict[str, Any]:
        """
        Get market open/close times.
        
        Returns:
            Market hours information
        """
        try:
            clock = self.trading_client.get_clock()
            
            return {
                "is_open": clock.is_open,
                "next_open": clock.next_open.isoformat(),
                "next_close": clock.next_close.isoformat(),
                "timestamp": clock.timestamp.isoformat(),
            }
        
        except Exception as e:
            logger.error(f"Failed to get market hours: {e}")
            raise


# Global instance
alpaca_client = AlpacaClient()
