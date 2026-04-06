# Live Execution - Correlation Trading System

## Overview

This system implements an automated **correlation breakout trading strategy** that identifies trading opportunities when the correlation between two assets breaks out of its historical normal range. The system consists of two main components working together:

1. **`CorrelationStrategyIndicators`**: Handles strategy logic, feature transformations, and signal generation
2. **`PairTradingCorrelation`**: Manages live trading execution, position management, and risk controls

The architecture emphasizes **separation of concerns** - strategy logic is isolated from trading execution, making the system more modular, testable, and maintainable.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Live Trading Data Flow                       │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                Raw Glassnode Data                               │
│  • Price data, network metrics, social indicators               │
│  • Multiple assets and timeframes                               │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│            CorrelationStrategyIndicators.py                     │
│                                                                 │
│   Feature Transformation:                                       │
│    • Raw → Z-Score, Rate of Change, Bollinger Bands             │
│    • Threshold Crossing Detection                               │
│    • Rolling window calculations                                │
│                                                                 │
│   Signal Generation:                                            │
│    • Multi-indicator signal detection                           │
│    • Signal strength calculation                                │
│    • Entry/exit condition evaluation                            │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│              PairTradingCorrelation.py                          │
│                                                                 │
│   Position Management:                                          │
│    • Entry order placement with position sizing                 │
│    • Exit condition monitoring (stop-loss, take-profit, time)   │
│    • Real-time P&L tracking                                     │
│                                                                 │
│   Trading Execution:                                            │
│    • LimitExecutioner integration for order placement           │
│    • Database storage for positions and trades                  │
│    • Risk management and error handling                         │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Exchange & Database                           │
│  • Order execution via LimitExecutioner                         │
│  • Position tracking in ScryptDb                                │
│  • Trade history and performance metrics                        │
└─────────────────────────────────────────────────────────────────┘
```

---

# CorrelationStrategyIndicators

## Overview

The **CorrelationStrategyIndicators** class is the brain of the trading system, responsible for:
- **Feature transformation**: Converting raw Glassnode data into trading-ready indicators
- **Signal generation**: Detecting entry opportunities across multiple indicators
- **Strategy configuration**: Managing indicator parameters and thresholds

## Key Features

### 🔄 **Advanced Feature Transformation System**
Transforms raw market data into actionable trading signals using multiple transformation types:

#### **Supported Transformations**
| Transform Type | Description | Use Case |
|----------------|-------------|----------|
| `zscore` | Rolling Z-score normalization | Detect statistical outliers |
| `roc` | Rate of change over N periods | Momentum and trend detection |
| `bb_bandwidth` | Bollinger Bands bandwidth | Volatility measurement |
| `bb_percent_b` | Bollinger Bands %B | Mean reversion signals |
| `threshold_low`/`threshold_high` | Threshold crossing detection | Level breakouts |
| `raw` | No transformation | Direct value comparison |

#### **Feature Transformation Flow**
```python
# Raw data example: "Price temp" with timeframe=72hrs, type=zscore
raw_data = [45000, 45200, 44800, 45100, ...]  # Raw price data

# Transformation applied
if feature_type == 'zscore':
    # Calculate rolling Z-score with 72-hour window
    transformed_data = zscore_transformer.transform(raw_data, window=72)
    # Result: [-0.5, 1.2, -1.8, 0.3, ...]

# Now compare against thresholds
if transformed_data[-1] > entry_threshold_high:
    signal_triggered = True
```

### 🎯 **Multi-Indicator Signal Detection**
The system supports multiple indicators per strategy and selects the strongest signal:

```python
# Example strategy with 3 indicators
indicators = [
    {
        'feature_name': 'Price temp',
        'feature_timeframe': 72,  # hours
        'feature_type': 'zscore',
        'entry_threshold_high': 2.0,
        'entry_threshold_low': -2.0,
        'exit_threshold_high': 1.0,
        'exit_threshold_low': -1.0,
        'direction_on_high': 1,   # Long when above high threshold
        'direction_on_low': -1    # Short when below low threshold
    },
    # ... more indicators
]

# Signal selection logic
strongest_signal = max(signals, key=lambda x: abs(x.distance_from_threshold))
```

### 📊 **Strategy Configuration Structure**
```python
strategy_params = {
    'strategy_id': 'BTC_MULTI_001',
    'take_profit_pct': 0.03,
    'stop_loss_pct': 0.02,
    'indicators': [
        {
            'feature_name': 'Network Activity',
            'feature_timeframe': 48,
            'feature_type': 'roc',
            'base_hold_hours': 24,  # Hold time specific to this indicator
            'entry_threshold_high': 0.15,
            'entry_threshold_low': -0.15,
            'exit_threshold_high': 0.05,
            'exit_threshold_low': -0.05,
            'direction_on_high': 1,
            'direction_on_low': -1
        }
    ]
}
```

## Core Methods

### `transform_feature_data(feature_name, raw_data, feature_timeframe, feature_type)`
Transforms raw feature data based on configuration:
```python
# Transform raw network activity data using rate of change
transformed_data = indicator.transform_feature_data(
    feature_name='Network Activity',
    raw_data=[100, 105, 98, 110, 115],
    feature_timeframe=24,
    feature_type='roc'
)
# Returns: [0.05, -0.067, 0.122, 0.045]  # Rate of change values
```

### `transform_all_features(raw_feature_dict)`
Batch processes all features for a strategy:
```python
raw_features = {
    'Price temp': [45000, 45200, 44800],
    'Network Activity': [100, 105, 98],
    'Social Sentiment': [0.6, 0.7, 0.5]
}

transformed_features = strategy_config.transform_all_features(raw_features)
# Returns transformed values ready for signal detection
```

### `get_signal(transformed_feature_values)`
Evaluates all indicators and returns the strongest signal:
```python
has_signal, signal_direction, signal_info = strategy_config.get_signal(feature_values)

if has_signal:
    print(f"Signal: {signal_direction}")
    print(f"Triggered by: {signal_info['triggered_by']}")
    print(f"Signal strength: {signal_info['signal_strength']:.3f}")
```

## Usage Example

```python
# Initialize strategy configuration
from CorrelationStrategyIndicators import CorrelationStrategyIndicators

strategy_config = CorrelationStrategyIndicators(strategy_params)

# Transform raw data
raw_data = fetch_glassnode_data()
transformed_data = strategy_config.transform_all_features(raw_data)

# Check for signals
has_signal, direction, info = strategy_config.get_signal(transformed_data)

if has_signal:
    print(f"🚀 {info['triggered_by']} signal: {direction}")
    print(f"Signal strength: {info['signal_strength']:.3f}")
```

---

# PairTradingCorrelation (Live Trading Engine)

## Overview

The **PairTradingCorrelation** class handles all live trading execution, including:
- **Position management**: Entry, exit, and risk monitoring
- **Order execution**: Integration with LimitExecutioner for optimal fills
- **Database operations**: Position tracking and trade history
- **Risk controls**: Stop-loss, take-profit, and time-based exits

## Key Features

### 🎯 **Dual-Mode Monitoring System**
- **Hourly Checks (Top of Hour)**: Entry signal detection + position management
- **5-Minute Checks**: Position monitoring only (exits, P&L tracking)
- Optimizes computational resources while maintaining trading responsiveness

### 💱 **Intelligent Position Management**
- **Entry Logic**: Sigmoid-based position sizing with feature-driven signals
- **Exit Logic**: Multi-condition exit monitoring (stop-loss, take-profit, time, feature-based)
- **Real-time P&L**: Continuous position value tracking

### 🛡️ **Comprehensive Risk Management**
- **Stop Loss**: Automatic exit when position P&L hits loss threshold
- **Take Profit**: Automatic exit when profit target reached  
- **Time-Based Exits**: Close positions after each indicator's `base_hold_hours` limit
- **Feature-Based Exits**: Exit when transformed features hit exit thresholds

### 🕐 **Individual Hold Time Management**
Each indicator has its own `base_hold_hours` parameter, allowing different features to have different maximum hold times:
- **Price signals**: May be held for 48 hours (longer-term mean reversion)
- **Network activity**: May be held for 36 hours (medium-term momentum)  
- **Social sentiment**: May be held for 12 hours (short-term contrarian signals)

This flexibility allows the system to optimize hold times based on each feature's signal persistence characteristics.

**Database Storage**: Each indicator's `base_hold_hours` is stored individually in the `mf_trading_strategies` table, allowing for precise per-indicator time management.

## Core Trading Methods

### `check_exit_conditions(strategy_id, current_prices, feature_values)`
Evaluates all exit conditions for active positions:
```python
should_exit, exit_reason = trader.check_exit_conditions(
    strategy_id='BTC_MULTI_001',
    current_prices={'BTC': 45000},
    feature_values={'Price temp': 1.5}  # Transformed value
)

if should_exit:
    print(f"Exit triggered: {exit_reason}")
```

**Exit Conditions Checked:**
1. **Max hold time**: Position held longer than indicator's `base_hold_hours` limit
2. **Feature-based**: Transformed features cross exit thresholds  
3. **Stop-loss**: Position P&L below stop-loss threshold
4. **Take-profit**: Position P&L above take-profit threshold

### `place_entry_order(strategy_id, signal_direction, current_prices, feature_values)`
Places new position based on signal:
```python
success = await trader.place_entry_order(
    strategy_id='BTC_MULTI_001',
    signal_direction=1,  # Long position
    current_prices={'BTC': 45000},
    feature_values={'Price temp': 2.1}  # Strong signal
)
```

**Entry Process:**
1. **Position sizing**: Calculate size using sigmoid function based on signal strength
2. **Order placement**: Use LimitExecutioner for optimal execution
3. **Position tracking**: Store position details in database
4. **Logging**: Record entry with signal information

### `close_position(strategy_id, reason, current_prices)`
Closes existing position and calculates P&L:
```python
await trader.close_position(
    strategy_id='BTC_MULTI_001',
    reason='take_profit',
    current_prices={'BTC': 46500}
)
```

**Close Process:**
1. **P&L calculation**: Determine final position performance
2. **Order execution**: Place closing order via LimitExecutioner
3. **Database update**: Store completed trade with metrics
4. **Position cleanup**: Remove from active tracking

### `monitor_signals()`
Main monitoring loop that orchestrates the trading process:
```python
async def monitor_signals(self):
    current_time = datetime.now()
    
    # Determine check type based on time
    is_hourly = current_time.minute <= 4
    
    if is_hourly:
        # FULL CHECK: Entry signals + position management
        print("🔍 HOURLY CHECK: Entry signals + Position management")
        
        # 1. Fetch raw feature data
        raw_features = await self.fetch_live_feature_data()
        
        # 2. Transform features using strategy configuration
        for strategy_id, strategy_config in self.strategies.items():
            transformed_features = strategy_config.transform_all_features(raw_features)
            
            # 3. Check for entry signals
            has_signal, signal_direction, signal_info = strategy_config.get_signal(transformed_features)
            
            if has_signal and strategy_id not in self.active_positions:
                await self.place_entry_order(strategy_id, signal_direction, current_prices, transformed_features)
            
            # 4. Check exit conditions for existing positions
            if strategy_id in self.active_positions:
                should_exit, exit_reason = self.check_exit_conditions(strategy_id, current_prices, transformed_features)
                if should_exit:
                    await self.close_position(strategy_id, exit_reason, current_prices)
    else:
        # POSITION CHECK: Monitor existing positions only
        print("👁️ Position monitoring only")
        
        for strategy_id in self.active_positions:
            should_exit, exit_reason = self.check_exit_conditions(strategy_id, current_prices, {})
            if should_exit:
                await self.close_position(strategy_id, exit_reason, current_prices)
```

## Advanced Features

### 🔢 **Sigmoid Position Sizing**
Position size adapts to signal strength:
```python
def _calculate_position_size_factor(self, feature_values, indicators):
    # Calculate how far the signal is from threshold
    signal_strength = max(abs(val - threshold) for val, threshold in signal_data)
    
    # Apply sigmoid function for smooth scaling
    position_factor = 2 / (1 + math.exp(-signal_strength)) - 1
    
    # Result: Stronger signals get larger position sizes
    return min(position_factor, 1.0)  # Cap at 100%
```

### 📊 **Database Integration**
Comprehensive position and trade tracking:
```python
# Position storage
position_data = {
    'strategy_id': 'BTC_MULTI_001',
    'entry_time': datetime.now(),
    'entry_price': 45000.0,
    'position_size': 0.1,
    'signal_info': json.dumps(signal_details),
    'stop_loss': 44100.0,
    'take_profit': 46350.0
}

# Trade history
trade_data = {
    'strategy_id': 'BTC_MULTI_001',
    'entry_time': position['entry_time'],
    'exit_time': datetime.now(),
    'entry_price': 45000.0,
    'exit_price': 46200.0,
    'pnl_pct': 0.0267,
    'exit_reason': 'take_profit',
    'hold_time_hours': 8.5
}
```

### 🔄 **Error Handling & Recovery**
Robust error handling throughout the trading process:
```python
try:
    # Attempt feature transformation
    transformed_features = strategy_config.transform_all_features(raw_features)
except Exception as e:
    print(f"⚠️ Feature transformation failed for {strategy_id}: {e}")
    continue  # Skip this strategy for now

try:
    # Attempt order placement
    success = await self.place_entry_order(...)
except Exception as e:
    print(f"❌ Order placement failed: {e}")
    # Log error and continue monitoring
```

## Trading Workflow

### 1. **System Initialization**
```python
# Load strategy configurations
strategies_df = pd.read_csv('strategies.csv')

# Initialize trading system
trader = PairTradingCorrelation(
    api_config=api_config,
    strategies_df=strategies_df
)

# Start live trading
await trader.start_live_trading()
```

### 2. **Live Trading Loop**
```
Every 5 Minutes:
├── Check current time
├── If hour:00-04 → HOURLY CHECK
│   ├── Fetch raw Glassnode data
│   ├── Transform features using strategy configs
│   ├── Check for entry signals via get_signal()
│   ├── Place orders for new signals
│   └── Monitor existing positions
└── Else → 5-MINUTE CHECK
    ├── Monitor existing positions only
    ├── Check exit conditions
    ├── Execute closes if needed
    └── Report P&L status
```

### 3. **Signal-to-Trade Flow**
```python
# 1. Raw data fetched from Glassnode
raw_features = {
    'Price temp': [45000, 45200, 44800, 45100],
    'Network Activity': [100, 105, 98, 110]
}

# 2. Strategy transforms features
transformed_features = strategy_config.transform_all_features(raw_features)
# Result: {'Price temp': 2.1, 'Network Activity': 0.15}

# 3. Strategy evaluates signals
has_signal, direction, info = strategy_config.get_signal(transformed_features)
# Result: (True, 1, {'triggered_by': 'Price temp', 'signal_strength': 2.1})

# 4. Trading engine places order
if has_signal:
    success = await trader.place_entry_order(strategy_id, direction, prices, transformed_features)
```

## Strategy Configuration

### Multi-Indicator Strategy Example
```python
strategy_params = {
    'strategy_id': 'BTC_MULTI_MOMENTUM_001',
    'take_profit_pct': 0.04,
    'stop_loss_pct': 0.025,
    'indicators': [
        {
            'feature_name': 'Price temp',
            'feature_timeframe': 72,
            'feature_type': 'zscore',
            'base_hold_hours': 48,    # Price signals held for 48 hours max
            'entry_threshold_high': 2.0,
            'entry_threshold_low': -2.0,
            'exit_threshold_high': 1.0,
            'exit_threshold_low': -1.0,
            'direction_on_high': -1,  # Short on high Z-score (mean reversion)
            'direction_on_low': 1     # Long on low Z-score
        },
        {
            'feature_name': 'Network Activity',
            'feature_timeframe': 24,
            'feature_type': 'roc',
            'base_hold_hours': 36,    # Network activity signals held for 36 hours max
            'entry_threshold_high': 0.20,
            'entry_threshold_low': -0.20,
            'exit_threshold_high': 0.05,
            'exit_threshold_low': -0.05,
            'direction_on_high': 1,   # Long on high network activity (momentum)
            'direction_on_low': -1    # Short on low network activity
        },
        {
            'feature_name': 'Social Sentiment',
            'feature_timeframe': 12,
            'feature_type': 'bb_percent_b',
            'base_hold_hours': 12,    # Social sentiment signals held for 12 hours max
            'entry_threshold_high': 0.9,
            'entry_threshold_low': 0.1,
            'exit_threshold_high': 0.7,
            'exit_threshold_low': 0.3,
            'direction_on_high': -1,  # Short on extreme optimism
            'direction_on_low': 1     # Long on extreme pessimism
        }
    ]
}
```

## Performance Monitoring

### Real-Time Console Output
```
🔍 2024-12-20 14:00:05 - HOURLY CHECK: Entry signals + Position management
📊 Fetching feature data for 3 strategies...
🔄 BTC_MULTI_001: Transforming 3 features...
   • Price temp: 45000 → 2.1 (zscore, max_hold: 48h)
   • Network Activity: 110 → 0.15 (roc, max_hold: 36h)  
   • Social Sentiment: 0.8 → 0.85 (bb_percent_b, max_hold: 12h)
🎯 BTC_MULTI_001: Signal detected!
   • Triggered by: Price temp
   • Signal direction: -1 (SHORT)
   • Signal strength: 2.1
✅ Order placed: SELL 0.1 BTC at $44,950 (limit order)
📈 Position opened: BTC_MULTI_001 SHORT (max_hold: 48h)

👁️ 2024-12-20 14:05:02 - Position monitoring only
📊 BTC_MULTI_001: SHORT position, P&L: +1.2% (+$540)
   • Entry: $45,000, Current: $44,460
   • Hold time: 5 minutes (max: 48h)
   • Exit conditions: None triggered
```

### Database Tracking
```sql
-- Active positions
SELECT strategy_id, entry_time, entry_price, current_pnl_pct 
FROM live_positions 
WHERE is_active = 1;

-- Trade history
SELECT strategy_id, entry_time, exit_time, pnl_pct, exit_reason
FROM completed_trades 
ORDER BY exit_time DESC;

-- Strategy performance
SELECT strategy_id, 
       COUNT(*) as total_trades,
       AVG(pnl_pct) as avg_pnl,
       SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) / COUNT(*) as win_rate
FROM completed_trades 
GROUP BY strategy_id;
```

## Key Improvements in New Architecture

### 1. **Separation of Concerns**
- **Strategy Logic**: `CorrelationStrategyIndicators` handles all feature transformation and signal generation
- **Trading Execution**: `PairTradingCorrelation` focuses on order management and risk controls
- **Result**: Cleaner, more maintainable, and testable code

### 2. **Feature Transformation Pipeline**
- **Before**: Raw values compared directly against thresholds
- **After**: Proper transformation (Z-score, ROC, etc.) before threshold comparison
- **Result**: More accurate and meaningful trading signals

### 3. **Enhanced Signal Selection**
- **Before**: Simple threshold checks
- **After**: Multi-indicator evaluation with signal strength ranking
- **Result**: Better signal quality and reduced false positives

### 4. **Improved Error Handling**
- **Before**: Basic try-catch blocks
- **After**: Comprehensive error handling with graceful degradation
- **Result**: More robust live trading system

### 5. **Better Logging and Monitoring**
- **Before**: Basic console output
- **After**: Detailed signal information, transformation results, and performance metrics
- **Result**: Better system observability and debugging capabilities

---

# Integration Components

## LimitExecutioner Integration

The trading system uses `LimitExecutioner` for optimal order execution:

### Overview
The **Limit Executioner** is an intelligent order execution algorithm designed to minimize market impact and achieve better average prices when executing large orders. Instead of placing a single large market order that could move the price against you, it breaks the order into smaller "clips" and uses adaptive limit orders to capture better prices over time.

### Key Features

#### 🎯 **Smart Order Slicing**
- Splits large orders into configurable smaller clips
- Executes clips sequentially to minimize market impact
- Calculates optimal clip sizes based on remaining quantity

#### 💰 **Price Improvement Strategy**
- Places limit orders at better prices than current market
- Uses basis points offset from best bid/ask (default: 2 bps)
- Adapts to changing market conditions in real-time

#### 🔄 **Adaptive Order Management**
- Periodically checks order status (default: every 5 seconds)
- Cancels and replaces unfilled orders with updated prices
- Automatically adjusts to market price movements

#### 🚨 **Market Order Fallback**
- Switches to market orders if limit strategy takes too long
- Configurable maximum attempt count (default: 12 attempts = 1 minute)
- Ensures order completion even in fast-moving markets

### Usage in Trading System
```python
# Intelligent order placement with price improvement
executioner = LimitExecutioner(
    rest_trader=self.trader,
    market_quadra=f"{asset}_USDT_SPOT",
    trade_direction="buy" if signal_direction > 0 else "sell",
    qty_to_execute=position_size,
    no_of_clips=3,  # Split large orders
    max_count=12    # 1-minute maximum execution time
)

# Execute the order
await executioner.start_execution()
```

## Database Operations (ScryptDb)

Comprehensive data persistence for all trading operations:

### Position Tracking
```python
# Store new position
self.db.execute_query("""
    INSERT INTO live_positions (strategy_id, entry_time, entry_price, position_size, signal_info)
    VALUES (?, ?, ?, ?, ?)
""", (strategy_id, entry_time, entry_price, position_size, json.dumps(signal_info)))

# Update position P&L
self.db.execute_query("""
    UPDATE live_positions 
    SET current_price = ?, current_pnl_pct = ?, last_update = ?
    WHERE strategy_id = ? AND is_active = 1
""", (current_price, pnl_pct, datetime.now(), strategy_id))
```

### Trade History
```python
# Store completed trade
self.db.execute_query("""
    INSERT INTO completed_trades (
        strategy_id, entry_time, exit_time, entry_price, exit_price,
        pnl_pct, exit_reason, hold_time_hours, signal_info
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
""", (strategy_id, entry_time, exit_time, entry_price, exit_price,
      pnl_pct, exit_reason, hold_time_hours, json.dumps(signal_info)))
```

### Performance Analytics
```python
# Strategy performance metrics
performance_data = self.db.fetch_query("""
    SELECT 
        strategy_id,
        COUNT(*) as total_trades,
        AVG(pnl_pct) as avg_pnl,
        STDDEV(pnl_pct) as pnl_volatility,
        SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) / COUNT(*) as win_rate,
        MAX(pnl_pct) as max_win,
        MIN(pnl_pct) as max_loss
    FROM completed_trades 
    WHERE entry_time >= ?
    GROUP BY strategy_id
""", (start_date,))
```

## Glassnode Data Integration

Real-time feature data fetching and processing:

### Data Fetching
```python
# Fetch multiple features efficiently
async def fetch_live_feature_data(self):
    feature_data = {}
    required_features = self.get_all_required_features()
    
    for feature_name in required_features:
        try:
            data = await self.glassnode_client.get_feature_data(
                feature=feature_name,
                timeframe='1h',
                limit=200  # Sufficient for rolling calculations
            )
            feature_data[feature_name] = data
        except Exception as e:
            print(f"⚠️ Failed to fetch {feature_name}: {e}")
            # Use cached data or skip this feature
            
    return feature_data
```

### Data Processing Pipeline
```python
# Raw data → Transformed features → Trading signals
async def process_feature_pipeline(self, strategy_id):
    # 1. Fetch raw data
    raw_features = await self.fetch_live_feature_data()
    
    # 2. Transform using strategy configuration
    strategy_config = self.strategies[strategy_id]
    transformed_features = strategy_config.transform_all_features(raw_features)
    
    # 3. Generate trading signals
    has_signal, signal_direction, signal_info = strategy_config.get_signal(transformed_features)
    
    return has_signal, signal_direction, signal_info, transformed_features
```

---

# Deployment and Usage

## Quick Start

### 1. Configure Strategies
```python
import pandas as pd
import json

strategies_df = pd.DataFrame({
    'strategy_id': ['BTC_MOMENTUM_001'],
    'take_profit_pct': [0.03],
    'stop_loss_pct': [0.02],
    'indicators': [json.dumps([{
        'feature_name': 'Price temp',
        'feature_timeframe': 72,
        'feature_type': 'zscore',
        'base_hold_hours': 24,  # Individual hold time per indicator
        'entry_threshold_high': 2.0,
        'entry_threshold_low': -2.0,
        'exit_threshold_high': 1.0,
        'exit_threshold_low': -1.0,
        'direction_on_high': -1,
        'direction_on_low': 1
    }])]
})
```

### 2. Initialize Trading System
```python
from PairTradingCorrelation import PairTradingCorrelation

api_config = {
    "company_exchange_id": "your-company-id",
    "exchange_id": "binance_usdm",
    "default_position_size_usd": 100,
    "glassnode_api_key": "your-glassnode-key"
}

trader = PairTradingCorrelation(api_config, strategies_df)
```

### 3. Start Live Trading
```python
# Start the monitoring loop
await trader.start_live_trading()

# Or run single check manually
await trader.monitor_signals()
```

## Production Considerations

### System Requirements
- **Python 3.8+** with asyncio support
- **Database**: SQLite or PostgreSQL for trade storage
- **API Access**: Glassnode API key and exchange API credentials
- **Network**: Stable internet connection with low latency to exchange
- **Memory**: Sufficient RAM for feature transformation calculations
- **Storage**: Database storage for position tracking and trade history

### Monitoring and Alerts
- **Health Checks**: Monitor system uptime and API connectivity
- **Performance Tracking**: Track strategy performance and system metrics
- **Error Alerts**: Set up notifications for critical failures
- **Position Monitoring**: Real-time P&L and risk exposure tracking
- **Feature Data Quality**: Monitor for missing or stale feature data

### Risk Management
- **Position Limits**: Configure maximum position sizes per strategy
- **Total Exposure**: Set overall system risk limits
- **Emergency Stops**: Implement manual override capabilities
- **Backup Systems**: Ensure redundancy for critical components
- **Feature Validation**: Validate transformed feature data before trading

### Performance Optimization
- **Feature Caching**: Cache transformed features to reduce computation
- **Batch Processing**: Process multiple strategies efficiently
- **Connection Pooling**: Reuse API connections where possible
- **Memory Management**: Efficient DataFrame operations and cleanup

## Testing and Validation

### Paper Trading Mode
```python
# Enable paper trading for testing
trader = PairTradingCorrelation(
    api_config=api_config,
    strategies_df=strategies_df,
    paper_trading=True  # No real orders placed
)

# All logic runs normally but orders are simulated
await trader.start_live_trading()
```

### Strategy Backtesting
```python
# Test strategy configuration on historical data
from backtest_framework import BacktestFramework

backtest = BacktestFramework(
    strategy_config=strategy_params,
    start_date='2023-01-01',
    end_date='2024-01-01'
)

results = backtest.run()
print(f"Backtest Results: {results['total_return']:.2%}")
```

### Feature Transformation Testing
```python
# Test feature transformations independently
strategy_config = CorrelationStrategyIndicators(strategy_params)

# Test with sample data
sample_data = {'Price temp': [45000, 45200, 44800, 45100]}
transformed = strategy_config.transform_all_features(sample_data)

print(f"Transformed features: {transformed}")
```

---

**💡 Pro Tip**: Start with paper trading mode to validate strategy performance before deploying live capital. The modular architecture makes it easy to test individual components separately.

**⚠️ Important**: Always monitor the system closely during initial deployment. Market conditions can change rapidly, and live trading systems require ongoing supervision and adjustment.

**🔧 Maintenance**: Regular system maintenance should include database cleanup, performance monitoring, API key rotation, and strategy parameter optimization based on recent performance data.
