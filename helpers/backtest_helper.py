import re
import numpy as np
from datetime import datetime, date
import logging
import os
from pathlib import Path
import sys
from numba import njit

current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
sys.path.append(str(project_root))

from core.database import DatabaseManager

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("DataHelper")  # <--- 3. Define the logger object

_db = None


def _get_db() -> DatabaseManager:
    """
    Singleton pattern to get the DatabaseManager.
    This allows both the MCP Server and the Cloud Run Job (Worker) to connect.
    """
    global _db
    if _db is not None:
        return _db

    # Ensure required env vars exist
    project_id = os.getenv("GCP_PROJECT_ID")
    region = os.getenv("GCP_COMPUTE_REGION", "us-central1") # Default to us-central1 if missing

    if not project_id:
        raise ValueError("GCP_PROJECT_ID is missing from environment variables.")

    # Initialize the manager
    _db = DatabaseManager(
        project_id=project_id,
        region=region,
        sql_instance_name=os.getenv("SQL_INSTANCE_NAME", "dummy"),
        sql_db_name=os.getenv("SQL_DB_NAME", "dummy"),
    )
    return _db

#====================================================================================

# Backtesting calculation module

#====================================================================================

@njit(fastmath=True)
def simulate_triple_barrier(
    prices: np.ndarray, 
    timestamps: np.ndarray, 
    signals: np.ndarray,
    stop_loss_pct: float,
    take_profit_pct: float,
    max_horizon_bars: int
):
    """
    Simulates the path of every trade to see which barrier is hit first.
    Returns: PnL % for each trade.
    """
    n = len(prices)
    trade_pnl = np.zeros(n)
    outcomes = np.zeros(n) # 1=Profit, -1=Stop, 0=Time
    
    for i in range(n):
        if signals[i] == 0:
            continue
            
        entry_price = prices[i]
        direction = np.sign(signals[i]) # 1 (Long) or -1 (Short)
        
        # Define Barriers
        if direction == 1:
            stop_price = entry_price * (1 - stop_loss_pct)
            target_price = entry_price * (1 + take_profit_pct)
        else:
            stop_price = entry_price * (1 + stop_loss_pct)
            target_price = entry_price * (1 - take_profit_pct)
            
        end_idx = min(i + max_horizon_bars, n)
        hit_barrier = False
        
        for j in range(i + 1, end_idx):
            curr_p = prices[j]
            
            # Check Stop Loss
            if (direction == 1 and curr_p <= stop_price) or \
               (direction == -1 and curr_p >= stop_price):
                trade_pnl[i] = -stop_loss_pct
                outcomes[i] = -1
                hit_barrier = True
                break
                
            # Check Take Profit
            elif (direction == 1 and curr_p >= target_price) or \
                 (direction == -1 and curr_p <= target_price):
                trade_pnl[i] = take_profit_pct
                outcomes[i] = 1
                hit_barrier = True
                break
        
        # Time Limit Exit
        if not hit_barrier and i < n-1:
            exit_price = prices[min(end_idx, n-1)]
            if direction == 1:
                ret = (exit_price - entry_price) / entry_price
            else:
                ret = (entry_price - exit_price) / entry_price
            trade_pnl[i] = ret
            outcomes[i] = 0
            
    return trade_pnl, outcomes

class VectorizedBacktester:
    def __init__(self, db_manager):
        self.db = db_manager

    def run_backtest(self, ticker, model, start_date, end_date, leverage_scalar=2.0, transaction_cost=0.0005):
        # 1. Fetch Data (Prices + Indicators)
        table_id = os.getenv("BQ_TECH_TABLE_ID", "market_data.processed_tech_indicators")
        query = f"""
            SELECT * FROM `{self.db.project_id}.{table_id}` 
            WHERE ticker = '{ticker}' 
            AND timestamp BETWEEN '{start_date}' AND '{end_date}'
            ORDER BY timestamp ASC
        """
        df = self.db.bq_client.query(query).to_dataframe()
        
        if df.empty:
            return {"error": "No data found for backtest period."}
            
        prices = df['close'].values
        timestamps = df['timestamp'].values
        
        # 2. Reconstruct Features & Inference
        # We assume the table already has the indicators calculated by 'update_stock_data'
        # We select columns that match the model's expected features
        try:
            valid_features = df[model.feature_names_in_]
        except KeyError as e:
            # Fallback: Intersect columns if exact match fails
            available = [c for c in model.feature_names_in_ if c in df.columns]
            valid_features = df[available]
            if len(available) < len(model.feature_names_in_):
                logger.warning(f"Feature mismatch. Missing: {set(model.feature_names_in_) - set(df.columns)}")

        probs = model.predict_proba(valid_features)[:, 1] # Probability of Class 1 (Up)
        
        # 3. Weight Conversion (Scalar / Kelly Strategy)
        # Logic: If Prob > 0.5, Go Long. Size = (Prob - 0.5) * Scalar
        raw_signals = (probs - 0.5) * leverage_scalar
        
        # Filter: Only trade if confidence is high enough (e.g. > 53% prob)
        active_signals = np.where(np.abs(probs - 0.5) > 0.03, raw_signals, 0)
        
        # 4. Run Numba Simulation
        pnl_stream, outcomes = simulate_triple_barrier(
            prices, timestamps, active_signals,
            stop_loss_pct=0.03, 
            take_profit_pct=0.05,
            max_horizon_bars=120
        )
        
        # 5. Apply Transaction Costs (Entry + Exit)
        costs = np.where(active_signals != 0, transaction_cost * 2, 0)
        net_pnl = pnl_stream - costs
        
        # 6. Compile Results
        df['trade_pnl'] = net_pnl
        trades = df[active_signals != 0]
        
        if len(trades) == 0:
            return {"status": "No trades generated."}
            
        total_trades = len(trades)
        win_rate = len(trades[trades['trade_pnl'] > 0]) / total_trades
        avg_return = trades['trade_pnl'].mean()
        
        # Equity Curve
        df['cumulative_return'] = (1 + df['trade_pnl'].fillna(0)).cumprod()
        total_return = df['cumulative_return'].iloc[-1] - 1
        
        # Max Drawdown
        rolling_max = df['cumulative_return'].cummax()
        drawdown = df['cumulative_return'] / rolling_max - 1
        max_drawdown = drawdown.min()
        
        # Sharpe Ratio (Annualized)
        sharpe = (avg_return / trades['trade_pnl'].std()) * np.sqrt(252 * 6.5) if trades['trade_pnl'].std() != 0 else 0
        
        return {
            "total_return_pct": round(total_return * 100, 2),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown_pct": round(max_drawdown * 100, 2),
            "win_rate_pct": round(win_rate * 100, 2),
            "total_trades": total_trades,
            "Kelly_Fraction": f"Dynamic (Scalar {leverage_scalar})"
        }

def run_backtest_core(ticker, model_uri, start_date, end_date):
    """Wrapper for the MCP Tool"""
    try:
        db = _get_db()
        
        if model_uri.startswith("gs://"):
            # Remove the "gs://" prefix
            clean_uri = model_uri.replace("gs://", "")
            # Split into [bucket, path_part1, path_part2...]
            parts = clean_uri.split("/")
            bucket_name = parts[0]
            # Rejoin the rest to get "models/filename.joblib"
            model_filename = "/".join(parts[1:])
        else:
            # Fallback for local paths or direct filenames
            bucket_name = os.getenv("GCS_MODEL_BUCKET")
            model_filename = model_uri

        logger.info(f"Attempting to load: Bucket={bucket_name}, File={model_filename}")
        
        model = db.load_model_from_gcs(bucket_name, model_filename)
        if not model:
            return {"error": f"Could not load model file: {model_filename} from bucket {bucket_name}"}
            
        engine = VectorizedBacktester(db)
        return engine.run_backtest(ticker, model, start_date, end_date)
    except Exception as e:
        logger.error(f"Backtest failed: {e}")
        return {"error": str(e)}