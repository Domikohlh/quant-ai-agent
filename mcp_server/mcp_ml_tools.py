import os
import uuid
import threading
import pandas as pd
from datetime import datetime
from google.cloud import bigquery, firestore
from sklearn.ensemble import RandomForestClassifier
from fastmcp import FastMCP

# Initialize the MCP server
mcp = FastMCP("QuantMLServer")

# Configure your GCP environment
PROJECT_ID = os.getenv("GCP_PROJECT_ID")
DATASET_ID = "market_data"
TABLE_ID = "historical_data"

def _async_pipeline_worker(job_id: str, target_ticker: str, basket: list):
    """The background thread that does the heavy lifting."""
    bq_client = bigquery.Client(project=PROJECT_ID)
    fs_client = firestore.Client(project=PROJECT_ID)
    
    def write_log(status, step, message, metrics=None):
        """Writes the current state directly to Firestore."""
        doc_ref = fs_client.collection("ml_pipeline_logs").document(target_ticker)
        doc_ref.set({
            "job_id": job_id,
            "status": status,
            "step": step,
            "message": message,
            "metrics": metrics or {},
            "updated_at": firestore.SERVER_TIMESTAMP
        }, merge=True)

    try:
        # 1. Download Basket Data to Pandas
        write_log("RUNNING", "DATA_DOWNLOAD", f"Downloading {len(basket)} tickers from BigQuery...")
        basket_str = "','".join(basket)
        
        query = f"""
            SELECT * FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`
            WHERE ticker IN ('{basket_str}')
            AND target_5d IS NOT NULL
        """
        df = bq_client.query(query).to_dataframe()
        
        if df.empty:
            raise ValueError("No training data found for the specified basket.")

        # 2. Dimensionality Reduction (Correlation + Random Forest)
        write_log("RUNNING", "DIMENSIONALITY_REDUCTION", "Running Correlation Matrix and Random Forest Importance...")
        
        exclude_cols = ['timestamp', 'ticker', 'source', 'target_5d', 'target_10d']
        features = [c for c in df.columns if c not in exclude_cols]
        
        X = df[features].fillna(0)
        y = df['target_5d']
        
        # Correlation Filter
        corr_matrix = X.corr().abs()
        upper = corr_matrix.where(pd.np.triu(pd.np.ones(corr_matrix.shape), k=1).astype(bool))
        to_drop = [column for column in upper.columns if any(upper[column] > 0.85)]
        X_filtered = X.drop(columns=to_drop)
        
        # Random Forest Importance
        rf = RandomForestClassifier(n_estimators=50, max_depth=5, random_state=42, n_jobs=-1)
        rf.fit(X_filtered, y)
        
        importances = pd.Series(rf.feature_importances_, index=X_filtered.columns)
        top_20_features = importances.nlargest(20).index.tolist()
        
        # 3. BQML Model Training
        write_log("RUNNING", "BQML_TRAINING", f"Training XGBoost on top 20 features...")
        model_name = f"{target_ticker}_model_v1"
        model_id = f"{PROJECT_ID}.{DATASET_ID}.{model_name}"
        
        feature_sql = ",\n  ".join(top_20_features)
        
        create_model_sql = f"""
            CREATE OR REPLACE MODEL `{model_id}`
            OPTIONS(
                model_type='BOOSTED_TREE_CLASSIFIER',
                input_label_cols=['target_5d'],
                auto_class_weights=TRUE
            ) AS
            SELECT 
                {feature_sql}, 
                target_5d 
            FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`
            WHERE ticker IN ('{basket_str}')
            AND target_5d IS NOT NULL
        """
        bq_client.query(create_model_sql).result()
        
        # 4. Evaluation & Prime Logic
        write_log("RUNNING", "EVALUATION", "Evaluating model metrics...")
        eval_sql = f"SELECT * FROM ML.EVALUATE(MODEL `{model_id}`)"
        eval_results = bq_client.query(eval_sql).to_dataframe()
        
        # Extract the full suite of metrics
        accuracy = eval_results['accuracy'].iloc[0]
        precision = eval_results.get('precision', pd.Series([0])).iloc[0]
        recall = eval_results.get('recall', pd.Series([0])).iloc[0]
        f1_score = eval_results.get('f1_score', pd.Series([0])).iloc[0]
        roc_auc = eval_results.get('roc_auc', pd.Series([0])).iloc[0]
        
        if accuracy > 0.50:
            final_status = "SUCCESS_PRIME"
            msg = f"Model achieved {accuracy:.2%} accuracy and is stored as PRIME."
        else:
            final_status = "REJECTED"
            msg = f"Model achieved {accuracy:.2%} accuracy (below 50% threshold). Discarding model."
            bq_client.query(f"DROP MODEL IF EXISTS `{model_id}`").result()

        # Save all metrics to Firestore so the Agent can analyze them
        metrics_dict = {
            "accuracy": float(accuracy),
            "precision": float(precision),
            "recall": float(recall),
            "f1_score": float(f1_score),
            "roc_auc": float(roc_auc),
            "features_used": top_20_features
        }
        
        write_log(final_status, "COMPLETED", msg, metrics=metrics_dict)

    except Exception as e:
        write_log("FAILED", "ERROR", str(e))


# --- THE MCP TOOLS ---

@mcp.tool()
def start_model_pipeline(target_ticker: str, basket_tickers: str) -> str:
    """
    Starts the asynchronous ML training pipeline. Use after confirming basket with user.
    """
    basket = [t.strip().upper() for t in basket_tickers.split(",")]
    job_id = f"JOB_{target_ticker}_{uuid.uuid4().hex[:6]}"
    
    # Initialize the document in Firestore
    fs_client = firestore.Client(project=PROJECT_ID)
    doc_ref = fs_client.collection("ml_pipeline_logs").document(target_ticker)
    doc_ref.set({
        "job_id": job_id,
        "status": "PENDING",
        "step": "INITIALIZING",
        "message": "Starting background thread...",
        "updated_at": firestore.SERVER_TIMESTAMP
    })
    
    # Spawn background thread
    thread = threading.Thread(target=_async_pipeline_worker, args=(job_id, target_ticker, basket))
    thread.start()
    
    return (f"✅ ML Pipeline Started. Job ID: {job_id}.\n"
            f"INSTRUCTION: Tell the user the model is currently training in the background. "
            f"Check status later using the `check_pipeline_logs` tool.")

@mcp.tool()
def check_pipeline_logs(target_ticker: str) -> str:
    """
    Checks the status and results of a previously started ML pipeline via Firestore.
    """
    fs_client = firestore.Client(project=PROJECT_ID)
    doc_ref = fs_client.collection("ml_pipeline_logs").document(target_ticker)
    doc = doc_ref.get()
    
    if not doc.exists:
        return f"No logs found for {target_ticker}. Are you sure a pipeline was started?"
        
    data = doc.to_dict()
    status = data.get("status")
    step = data.get("step")
    msg = data.get("message")
    
    if status in ["PENDING", "RUNNING"]:
        return f"⏳ Pipeline Status: {status}\nCurrent Step: {step}\nDetails: {msg}\nInstruction: Inform the user it is still processing."
    
    elif status == "SUCCESS_PRIME":
        metrics = data.get("metrics", {})
        return (f"✅ Pipeline Status: {status}\n"
                f"Model successfully saved as PRIME (Accuracy > 50%).\n"
                f"--- Evaluation Metrics ---\n"
                f"Accuracy:  {metrics.get('accuracy', 0):.2%}\n"
                f"Precision: {metrics.get('precision', 0):.2%}\n"
                f"Recall:    {metrics.get('recall', 0):.2%}\n"
                f"F1 Score:  {metrics.get('f1_score', 0):.4f}\n"
                f"ROC AUC:   {metrics.get('roc_auc', 0):.4f}\n"
                f"Features Used: {len(metrics.get('features_used', []))}\n"
                f"Instruction: Present these metrics to the user. Provide a strict quantitative analysis emphasizing Precision (false positive rate) and F1 Score. Advise the user on whether this model is actually safe to trade, or if it generates too much noise despite passing the baseline accuracy filter.")
                
    elif status == "REJECTED":
        metrics = data.get("metrics", {})
        return (f"❌ Pipeline Status: {status}\n"
                f"Model was REJECTED (Failed 50% accuracy threshold).\n"
                f"--- Evaluation Metrics ---\n"
                f"Accuracy:  {metrics.get('accuracy', 0):.2%}\n"
                f"Precision: {metrics.get('precision', 0):.2%}\n"
                f"Recall:    {metrics.get('recall', 0):.2%}\n"
                f"Instruction: Inform the user the model failed the baseline mathematical filter and was safely discarded. Suggest trying a completely different basket of tickers.")
                
    else:
        return f"⚠️ Pipeline Status: {status}\nError Details: {msg}"