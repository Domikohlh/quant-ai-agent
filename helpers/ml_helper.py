import re
import pandas as pd
import numpy as np
from datetime import datetime, date
import logging
import os
import json
from pathlib import Path
import sys

current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
sys.path.append(str(project_root))

from core.database import DatabaseManager
from helpers.data_helper import sanitize_ticker, get_volatility, json_serial

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

# Machine Learning Module

#====================================================================================

def run_feature_analysis_core(
    ticker: str, 
    basket: str = None, 
    barrier_width: float = 1.0, 
    time_horizon: int = 5,
    correlation_threshold: float = 0.85, 
    top_n: int = 15,
    training_end_date: str = "2024-12-31"
) -> dict:
    """Core logic: Load BQ data, Cluster, Random Forest, cut the data till 2024-12-31 for backtesting, Save to BQ."""
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
        
        # Parse the cutoff date to 2024-12-31
        cutoff_dt = pd.to_datetime(training_end_date).tz_localize(None)
        
       # 1. Test Set: STRICTLY AFTER Cutoff
        test_df = final_df[
            (final_df['ticker'] == target_ticker) & 
            (final_df['timestamp'] > cutoff_dt)
        ].copy()
        
        # 2. Train Set: STRICTLY BEFORE Cutoff
        # (Includes Basket + Target)
        train_df = final_df[final_df['timestamp'] <= cutoff_dt].copy()

        if test_df.empty or train_df.empty:
            return json.dumps({
                "status": "error", 
                "message": f"Split failed. No data found after {training_end_date}. Check if 'update_stock_data' fetched enough history."
            })

        # Save tables (Overwrite existing)
        # We embed the DATE in the table name to prevent mixing up versions
        safe_date = training_end_date.replace("-", "")
        train_table_id = f"market_data.training_basket_{target_ticker}_{safe_date}"
        test_table_id = f"market_data.testing_target_{target_ticker}_{safe_date}"
        
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

def train_basket_model_core(target_ticker: str, save_bucket: str, training_end_date: str="2024-12-31"):
    """
    The actual training logic (Heavy Lifting).
    Run this inside the Cloud Run Job.
    """
    try:
        db = _get_db()
        safe_date = training_end_date.replace("-", "")

        train_table = f"market_data.training_basket_{sanitize_ticker(target_ticker)}_{safe_date}"
        test_table = f"market_data.testing_target_{sanitize_ticker(target_ticker)}_{safe_date}"
        
        # 1. Load Data
        df_train = db.bq_client.query(f"SELECT * FROM `{db.project_id}.{train_table}`").to_dataframe()
        df_test = db.bq_client.query(f"SELECT * FROM `{db.project_id}.{test_table}` ORDER BY timestamp ASC").to_dataframe()

        logger.info(f"Looking for training data in: {train_table}")

        # 2. Verify Data Exists (Fail Fast)
        try:
            # Quick check to ensure we aren't training on air
            db.bq_client.get_table(f"{db.project_id}.{train_table}")
        except Exception:
             return json.dumps({
                 "status": "error", 
                 "message": f"Table '{train_table}' not found. You MUST run 'ml_feature_analysis' with training_end_date='{training_end_date}' first."
             })
        
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