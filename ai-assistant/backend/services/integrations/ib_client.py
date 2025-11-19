"""
Interactive Brokers API Client for live trading and portfolio management.
Requires TWS (Trader Workstation) or IB Gateway running.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
import asyncio

from ib_insync import IB, Stock, Order, MarketOrder, LimitOrder, util
from backend.core.config.settings import settings
from backend.utils.logging.logger import get_logger, trading_logger

logger = get_logger(__name__)


class InteractiveBrokersClient:
    """
    Interactive Brokers API client for portfolio management and trading.
    
    Features:
    - Real-time portfolio tracking
    - Order execution with human-in-the-loop
    - Position management
    - Account information
    
    Requirements:
    - TWS or IB Gateway must be running
    - API connections must be enabled
    - Paper trading account recommended for testing
    """
    
    def __init__(self):
        """Initialize IB client."""
        self.ib = IB()
        self.is_connected = False
        self.account_id = settings.ib_account
        
        # Connection settings
        self.host = settings.ib_host
        self.port = settings.ib_port
        self.client_id = settings.ib_client_id
        
        logger.info(
            "IB client initialized",
            host=self.host,
            port=self.port,
            client_id=self.client_id
        )
    
    async def connect(self) -> bool:
        """
        Connect to Interactive Brokers TWS/Gateway.
        
        Returns:
            True if connected successfully
        """
        try:
            if settings.mock_ib_api:
                logger.warning("IB API in mock mode - no real connection")
                self.is_connected = True
                return True
            
            self.ib.connect(
                host=self.host,
                port=self.port,
                clientId=self.client_id,
                timeout=settings.ib_timeout
            )
            
            self.is_connected = True
            
            logger.info("Connected to Interactive Brokers")
            
            return True
        
        except Exception as e:
            logger.error(f"Failed to connect to IB: {e}")
            self.is_connected = False
            raise
    
    async def disconnect(self) -> None:
        """Disconnect from IB."""
        if self.ib.isConnected():
            self.ib.disconnect()
            self.is_connected = False
            logger.info("Disconnected from Interactive Brokers")
    
    def _ensure_connected(self):
        """Ensure connection is active."""
        if not self.is_connected:
            raise ConnectionError("Not connected to Interactive Brokers")
    
    # ==================
    # Account Information
    # ==================
    
    async def get_account_summary(self) -> Dict[str, Any]:
        """
        Get account summary information.
        
        Returns:
            Account balance, equity, and margin info
        """
        self._ensure_connected()
        
        try:
            account_values = self.ib.accountSummary(self.account_id)
            
            summary = {}
            for item in account_values:
                summary[item.tag] = {
                    "value": item.value,
                    "currency": item.currency,
                }
            
            # Extract key metrics
            account_summary = {
                "account_id": self.account_id,
                "net_liquidation": float(summary.get("NetLiquidation", {}).get("value", 0)),
                "total_cash": float(summary.get("TotalCashValue", {}).get("value", 0)),
                "buying_power": float(summary.get("BuyingPower", {}).get("value", 0)),
                "equity_with_loan": float(summary.get("EquityWithLoanValue", {}).get("value", 0)),
                "gross_position_value": float(summary.get("GrossPositionValue", {}).get("value", 0)),
                "currency": summary.get("NetLiquidation", {}).get("currency", "USD"),
                "timestamp": datetime.utcnow().isoformat(),
            }
            
            logger.info(
                "Retrieved account summary",
                net_liquidation=account_summary["net_liquidation"]
            )
            
            return account_summary
        
        except Exception as e:
            logger.error(f"Failed to get account summary: {e}")
            raise
    
    # ==================
    # Portfolio Management
    # ==================
    
    async def get_portfolio_positions(self) -> List[Dict[str, Any]]:
        """
        Get all portfolio positions.
        
        Returns:
            List of position details
        """
        self._ensure_connected()
        
        try:
            positions = self.ib.portfolio()
            
            positions_data = []
            for pos in positions:
                position_data = {
                    "symbol": pos.contract.symbol,
                    "exchange": pos.contract.exchange,
                    "position": pos.position,
                    "market_price": pos.marketPrice,
                    "market_value": pos.marketValue,
                    "average_cost": pos.averageCost,
                    "unrealized_pnl": pos.unrealizedPNL,
                    "realized_pnl": pos.realizedPNL,
                    "account": pos.account,
                }
                positions_data.append(position_data)
            
            logger.info(f"Retrieved {len(positions_data)} portfolio positions")
            
            return positions_data
        
        except Exception as e:
            logger.error(f"Failed to get portfolio positions: {e}")
            raise
    
    async def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get position for a specific symbol.
        
        Args:
            symbol: Stock symbol
        
        Returns:
            Position details or None
        """
        self._ensure_connected()
        
        try:
            positions = await self.get_portfolio_positions()
            
            for pos in positions:
                if pos["symbol"] == symbol:
                    return pos
            
            return None
        
        except Exception as e:
            logger.error(f"Failed to get position for {symbol}: {e}")
            raise
    
    # ==================
    # Order Execution
    # ==================
    
    async def place_market_order(
        self,
        symbol: str,
        quantity: int,
        action: str,
        require_approval: bool = True
    ) -> Dict[str, Any]:
        """
        Place a market order (with human-in-the-loop approval).
        
        Args:
            symbol: Stock symbol
            quantity: Number of shares
            action: 'BUY' or 'SELL'
            require_approval: Require human approval before execution
        
        Returns:
            Order details and approval status
        """
        self._ensure_connected()
        
        try:
            # Create contract
            contract = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(contract)
            
            # Create order
            order = MarketOrder(action.upper(), quantity)
            
            # Get current price for logging
            ticker = self.ib.reqMktData(contract)
            await asyncio.sleep(1)  # Wait for price data
            current_price = ticker.marketPrice()
            
            order_details = {
                "symbol": symbol,
                "quantity": quantity,
                "action": action.upper(),
                "order_type": "MARKET",
                "estimated_price": current_price,
                "estimated_value": current_price * quantity if current_price else None,
                "timestamp": datetime.utcnow().isoformat(),
                "requires_approval": require_approval,
                "status": "pending_approval" if require_approval else "submitted",
            }
            
            # Log trade signal
            trading_logger.log_trade_signal(
                symbol=symbol,
                action=action.upper(),
                quantity=quantity,
                price=current_price or 0,
                confidence=1.0,  # Market orders have high confidence
                reasoning="Market order execution request",
                indicators={"order_type": "market"},
            )
            
            if require_approval:
                logger.warning(
                    "Order requires human approval",
                    **order_details
                )
                
                # In production, this would trigger notification system
                # For now, we just log it
                order_details["approval_required"] = True
                order_details["approval_method"] = "human_in_the_loop"
                
                return order_details
            
            # Execute order
            trade = self.ib.placeOrder(contract, order)
            
            # Wait for order to be acknowledged
            await asyncio.sleep(2)
            
            order_details.update({
                "order_id": trade.order.orderId,
                "status": trade.orderStatus.status,
                "filled": trade.orderStatus.filled,
                "remaining": trade.orderStatus.remaining,
            })
            
            trading_logger.log_trade_execution(
                trade_id=str(trade.order.orderId),
                symbol=symbol,
                action=action.upper(),
                quantity=quantity,
                price=current_price or 0,
                status="submitted",
            )
            
            logger.info(
                f"Market order placed: {action} {quantity} {symbol}",
                order_id=trade.order.orderId
            )
            
            return order_details
        
        except Exception as e:
            logger.error(f"Failed to place market order: {e}")
            
            trading_logger.log_trade_execution(
                trade_id="error",
                symbol=symbol,
                action=action.upper(),
                quantity=quantity,
                price=0,
                status="failed",
                error=str(e),
            )
            
            raise
    
    async def place_limit_order(
        self,
        symbol: str,
        quantity: int,
        action: str,
        limit_price: float,
        require_approval: bool = True
    ) -> Dict[str, Any]:
        """
        Place a limit order.
        
        Args:
            symbol: Stock symbol
            quantity: Number of shares
            action: 'BUY' or 'SELL'
            limit_price: Limit price
            require_approval: Require human approval
        
        Returns:
            Order details
        """
        self._ensure_connected()
        
        try:
            contract = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(contract)
            
            order = LimitOrder(action.upper(), quantity, limit_price)
            
            order_details = {
                "symbol": symbol,
                "quantity": quantity,
                "action": action.upper(),
                "order_type": "LIMIT",
                "limit_price": limit_price,
                "estimated_value": limit_price * quantity,
                "timestamp": datetime.utcnow().isoformat(),
                "requires_approval": require_approval,
                "status": "pending_approval" if require_approval else "submitted",
            }
            
            trading_logger.log_trade_signal(
                symbol=symbol,
                action=action.upper(),
                quantity=quantity,
                price=limit_price,
                confidence=0.9,
                reasoning="Limit order execution request",
                indicators={"order_type": "limit", "limit_price": limit_price},
            )
            
            if require_approval:
                logger.warning(
                    "Order requires human approval",
                    **order_details
                )
                return order_details
            
            trade = self.ib.placeOrder(contract, order)
            
            await asyncio.sleep(2)
            
            order_details.update({
                "order_id": trade.order.orderId,
                "status": trade.orderStatus.status,
                "filled": trade.orderStatus.filled,
                "remaining": trade.orderStatus.remaining,
            })
            
            logger.info(
                f"Limit order placed: {action} {quantity} {symbol} @ ${limit_price}",
                order_id=trade.order.orderId
            )
            
            return order_details
        
        except Exception as e:
            logger.error(f"Failed to place limit order: {e}")
            raise
    
    async def cancel_order(self, order_id: int) -> bool:
        """
        Cancel an order.
        
        Args:
            order_id: Order ID to cancel
        
        Returns:
            True if cancelled
        """
        self._ensure_connected()
        
        try:
            trades = self.ib.trades()
            
            for trade in trades:
                if trade.order.orderId == order_id:
                    self.ib.cancelOrder(trade.order)
                    logger.info(f"Order cancelled", order_id=order_id)
                    return True
            
            logger.warning(f"Order not found", order_id=order_id)
            return False
        
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            raise
    
    async def get_open_orders(self) -> List[Dict[str, Any]]:
        """
        Get all open orders.
        
        Returns:
            List of open orders
        """
        self._ensure_connected()
        
        try:
            trades = self.ib.openTrades()
            
            orders_data = []
            for trade in trades:
                order_data = {
                    "order_id": trade.order.orderId,
                    "symbol": trade.contract.symbol,
                    "action": trade.order.action,
                    "quantity": trade.order.totalQuantity,
                    "order_type": trade.order.orderType,
                    "limit_price": trade.order.lmtPrice if hasattr(trade.order, 'lmtPrice') else None,
                    "status": trade.orderStatus.status,
                    "filled": trade.orderStatus.filled,
                    "remaining": trade.orderStatus.remaining,
                }
                orders_data.append(order_data)
            
            logger.info(f"Retrieved {len(orders_data)} open orders")
            
            return orders_data
        
        except Exception as e:
            logger.error(f"Failed to get open orders: {e}")
            raise
    
    # ==================
    # Market Data
    # ==================
    
    async def get_real_time_price(self, symbol: str) -> Optional[float]:
        """
        Get real-time price for a symbol.
        
        Args:
            symbol: Stock symbol
        
        Returns:
            Current market price
        """
        self._ensure_connected()
        
        try:
            contract = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(contract)
            
            ticker = self.ib.reqMktData(contract)
            await asyncio.sleep(2)  # Wait for data
            
            price = ticker.marketPrice()
            
            logger.debug(f"Real-time price for {symbol}: ${price}")
            
            return price
        
        except Exception as e:
            logger.error(f"Failed to get price for {symbol}: {e}")
            return None


# Global instance
ib_client = InteractiveBrokersClient()
