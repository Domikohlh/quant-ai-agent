# helper_func.py
import re
import pandas as pd
import numpy as np
from datetime import datetime, date
import logging
import os
import json
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

#====================================================================================

# Data  Fetching Module

#====================================================================================
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

def get_fred():
    global _fred
    if _fred is not None:
        return _fred
    _require_env("FRED_API_KEY")
    from fredapi import Fred  # local import: only required if macro tool is called

    _fred = Fred(api_key=os.getenv("FRED_API_KEY"))
    logger.info("Initialized FRED client")
    return _fred

def sanitize_ticker(raw: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", raw.strip().upper())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        raise ValueError("ticker is empty/invalid after sanitization")
    return cleaned

def validate_stock_params(ticker: str, period: str, interval: str) -> None:
    if not isinstance(ticker, str) or not ticker.strip():
        raise ValueError("ticker must be a non-empty string")

    allowed_periods = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"}
    allowed_intervals = {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo"}
    if period not in allowed_periods:
        raise ValueError(f"period must be one of {sorted(allowed_periods)}")
    if interval not in allowed_intervals:
        raise ValueError(f"interval must be one of {sorted(allowed_intervals)}")

def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    if isinstance(obj, (np.int64, np.int32)):
        return int(obj)
    if isinstance(obj, (np.float64, np.float32)):
        return float(obj)
    raise TypeError(f"Type {type(obj)} not serializable")

def get_volatility(close_prices: pd.Series, span: int = 20) -> pd.Series:
    """Compute dynamic volatility (standard deviation of returns) for Triple Barrier."""
    # Simple returns
    returns = close_prices.pct_change()
    # EWM standard deviation
    return returns.ewm(span=span).std()

#====================================================================================

# Machine Learning Module

#====================================================================================

def run_feature_analysis_core(
    ticker: str, 
    basket: str = None, 
    barrier_width: float = 1.0, 
    time_horizon: int = 5,
    correlation_threshold: float = 0.85, 
    top_n: int = 15
) -> dict:
    """Core logic: Load BQ data, Cluster, Random Forest, Save to BQ."""
    try:
        db = _get_db()
        raw_table_id = os.getenv("BQ_TECH_TABLE_ID", "market_data.processed_tech_indicators")
        
        # Parse inputs
        target_ticker = sanitize_ticker(ticker)
        if basket:
            ticker_list = [sanitize_ticker(t) for t in basket.split(",")]
        else:
            ticker_list = [target_ticker]
            
        # Ensure target is in the list
        if target_ticker not in ticker_list:
            ticker_list.append(target_ticker)

        all_dfs = []
        
        # --- PHASE 1: LOAD & LABEL (Triple Barrier) ---
        for t in ticker_list:
            query = f"SELECT * FROM `{db.project_id}.{raw_table_id}` WHERE ticker = '{t}' ORDER BY timestamp ASC"
            df_t = db.bq_client.query(query).to_dataframe()
            
            if df_t.empty:
                continue

            # A. Calculate Volatility
            df_t['volatility'] = get_volatility(df_t['close'])
            
            # B. Apply Triple Barrier Labeling
            labels = []
            # We iterate until len-horizon because we need to look ahead
            for i in range(len(df_t) - time_horizon):
                current_price = df_t.iloc[i]['close']
                vol = df_t.iloc[i]['volatility']
                
                if pd.isna(vol) or vol == 0:
                    labels.append(0)
                    continue
                    
                upper = current_price * (1 + (vol * barrier_width))
                lower = current_price * (1 - (vol * barrier_width))
                
                # Look ahead window
                future_window = df_t.iloc[i+1 : i+1+time_horizon]['close']
                
                hit_upper = future_window[future_window >= upper].any()
                hit_lower = future_window[future_window <= lower].any()
                
                # Label Logic: 1 = Buy (Hit Upper), 0 = Neutral/Sell (Hit Lower or Time Expire)
                if hit_upper and not hit_lower:
                    labels.append(1)
                else:
                    labels.append(0)
            
            # Fill remaining rows with 0 (cannot predict end of data)
            labels.extend([0] * time_horizon)
            df_t['target'] = labels
            
            # Drop NaN volatility rows (start of data)
            df_t.dropna(subset=['volatility'], inplace=True)
            all_dfs.append(df_t)

        if not all_dfs:
            return json.dumps({"status": "error", "message": "No data found for any ticker in basket."})

        combined_df = pd.concat(all_dfs)

        # --- PHASE 2: FEATURE SELECTION (On Combined Data) ---
        # Define candidate features
        metadata_cols = ['timestamp', 'ticker', 'source', 'target', 'volatility']
        candidate_cols = [c for c in combined_df.columns if c not in metadata_cols and c in combined_df.select_dtypes(include=[np.number]).columns]
        
        # Drop rows with NaN in candidates for calculation
        calc_df = combined_df.dropna(subset=candidate_cols + ['target']).copy()
        
        # A. Correlation Clustering
        from scipy.cluster import hierarchy
        from scipy.spatial.distance import squareform

        corr = calc_df[candidate_cols].corr().fillna(0)
        dist_matrix = 1 - np.abs(corr.values)
        linkage = hierarchy.ward(squareform(dist_matrix))
        cluster_labels = hierarchy.fcluster(linkage, 1 - correlation_threshold, criterion='distance')
        
        cluster_leaders = []
        for cluster_id in np.unique(cluster_labels):
            members = [candidate_cols[i] for i, label in enumerate(cluster_labels) if label == cluster_id]
            cluster_leaders.append(members[0])
            
        # B. Importance Ranking (Random Forest)
        X = calc_df[cluster_leaders]
        y = calc_df['target']
        
        from sklearn.ensemble import RandomForestClassifier
        rf = RandomForestClassifier(n_estimators=100, random_state=42, n_jobs=-1)
        rf.fit(X, y)
        
        importance = pd.Series(rf.feature_importances_, index=cluster_leaders).sort_values(ascending=False)
        selected_features = importance.head(top_n).index.tolist()
        
        # --- PHASE 3: SPLIT & SAVE ---
        # Final Columns: Metadata + Selected Features
        final_cols = ['timestamp', 'ticker', 'target'] + selected_features
        final_df = combined_df[final_cols].copy().dropna()
        
        # Split Logic:
        # 1. Test Set: Only the TARGET ticker, and only the recent 20%
        target_only = final_df[final_df['ticker'] == target_ticker].copy()
        split_idx = int(len(target_only) * 0.8)
        cutoff_date = target_only.iloc[split_idx]['timestamp']
        
        test_df = target_only[target_only['timestamp'] >= cutoff_date]
        
        # 2. Train Set: EVERYTHING (Basket + Old Target) before the cutoff
        # This prevents data leakage while using the basket to learn patterns
        train_df = final_df[final_df['timestamp'] < cutoff_date]

        # Save tables
        train_table_id = f"market_data.training_basket"
        test_table_id = f"market_data.testing_target_{target_ticker}"
        
        db.save_market_data(train_df, table_id=train_table_id) 
        db.save_market_data(test_df, table_id=test_table_id)
        
        return json.dumps({
            "status": "success",
            "message": f"Created Triple Barrier datasets using basket: {ticker_list}",
            "train_set_size": len(train_df),
            "test_set_size": len(test_df),
            "selected_features": selected_features,
            "training_table": train_table_id,
            "testing_table": test_table_id
        }, default=json_serial, indent=2)

    except Exception as e: 
        logger.error(f"Core Analysis failed: {e}")
        return json.dumps({"status": "error", "message": f"Core analysis error: {str(e)}"})

def train_basket_model_core(target_ticker: str, save_bucket: str):
    """
    The actual training logic (Heavy Lifting).
    Run this inside the Cloud Run Job.
    """
    try:
        db = _get_db()
        train_table = f"market_data.training_basket_{sanitize_ticker(target_ticker)}"
        test_table = f"market_data.testing_target_{sanitize_ticker(target_ticker)}"
        
        # 1. Load Data
        df_train = db.bq_client.query(f"SELECT * FROM `{db.project_id}.{train_table}`").to_dataframe()
        df_test = db.bq_client.query(f"SELECT * FROM `{db.project_id}.{test_table}` ORDER BY timestamp ASC").to_dataframe()
        
        # 2. Setup Features
        meta = ['timestamp', 'ticker', 'source', 'target', 'volatility']
        features = [c for c in df_train.columns if c not in meta and c in df_train.select_dtypes(include=[np.number]).columns]
        
        X_train, y_train = df_train[features], df_train['target']
        X_test, y_test = df_test[features], df_test['target']

        # Safety Check: Does the basket provide both classes?
        if y_train.nunique() < 2:
                return json.dumps({"status": "error", "message": f"Training set (Basket) has insufficient class variety: {y_train.unique()}"})
        
        # XGBoost Setup
        default_params = {
            'n_estimators': 200,          # Increased for larger basket data
            'learning_rate': 0.05,        # Slower learning for robustness
            'max_depth': 5,
            'objective': 'binary:logistic',
            'eval_metric': 'logloss',
            'use_label_encoder': False
        }
        import xgboost as xgb

        # 3. Train/Recall model
        latest_model_file = db.get_latest_model_file(save_bucket, target_ticker)
        existing_model = None
    
        if latest_model_file:
            logger.info(f"🔄 Incremental Mode: Attempting to update {latest_model_file}...")
            existing_model = db.load_model_from_gcs(save_bucket, latest_model_file)

        if existing_model:
            model=existing_model
            logger.info(f"Resuming training from: {save_bucket}")
            model.fit(X_train, y_train, xgb_model=model.get_booster())

        else:
            logger.info("🆕 Fresh Mode: Training model from scratch...")
            model = xgb.XGBClassifier(**default_params)
            model.fit(X_train, y_train)
        
        # 4. Save to GCS (Binary)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"models/{target_ticker}_basket_{timestamp}.joblib"
        gcs_path = db.save_model_to_gcs(model, save_bucket, filename)
        
        # 5. Metrics
        preds = model.predict(X_test)

        from sklearn.metrics import accuracy_score, classification_report
        report = classification_report(y_test, preds, labels=[0, 1], output_dict=True, zero_division=0)
        up_metrics = report.get('1', {})
        
        return json.dumps({"status": "success",
                "model_path": gcs_path, 
                "features_used": len(features),
                "model_type": "XGBoost (Basket Trained)",
                "test_accuracy": round(accuracy_score(y_test, preds), 4),
                "precision_up": round(up_metrics.get('precision', 0.0), 4),
                "recall_up": round(up_metrics.get('recall', 0.0), 4),
                "f1_up": round(up_metrics.get('f1-score', 0.0), 4),
            }, default=json_serial, indent=2)
        
    except Exception as e:
        logger.error(f"Training failed: {e}")
        return json.dumps({"status": "error", "message": f"Training engine error: {str(e)}"})

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