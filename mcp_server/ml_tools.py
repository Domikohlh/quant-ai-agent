import os
import uuid
from datetime import datetime
from google.cloud import bigquery, firestore
from fastmcp import FastMCP

# Initialize the MCP server
mcp = FastMCP("QuantMLServer")

PROJECT_ID = os.getenv("GCP_PROJECT_ID", "quant-ai-agent-482111")
DATASET_ID = "market_data"
TABLE_ID = "historical_data"

# Predefined rigorous hyperparameter profiles to prevent hallucination
TUNING_PROFILES = {
    "CONSERVATIVE": {"max_tree_depth": 3, "l2_reg": 1.0, "learn_rate": 0.05},
    "BALANCED":     {"max_tree_depth": 5, "l2_reg": 0.1, "learn_rate": 0.10},
    "AGGRESSIVE":   {"max_tree_depth": 7, "l2_reg": 0.0, "learn_rate": 0.20}
}

@mcp.tool()
def start_model_pipeline(target_ticker: str, basket_tickers: str, market_mode: str, tuning_profile: str = "BALANCED") -> str:
    """
    Starts the asynchronous BQML training pipeline.
    
    Args:
        target_ticker: The primary asset to predict (e.g. NVDA).
        basket_tickers: Comma-separated list of tickers to train on.
        market_mode: MUST be either 'TRADITIONAL' or 'CRYPTO'. Controls chronological data splits.
        tuning_profile: MUST be 'CONSERVATIVE', 'BALANCED', or 'AGGRESSIVE'.
    """
    market_mode = market_mode.strip().upper()
    if market_mode not in ["TRADITIONAL", "CRYPTO"]:
        return "❌ Error: market_mode must be 'TRADITIONAL' or 'CRYPTO'."
        
    profile = TUNING_PROFILES.get(tuning_profile.upper(), TUNING_PROFILES["BALANCED"])
    
    # Format inputs for SQL
    basket_list = [t.strip().upper() for t in basket_tickers.split(",")]
    basket_str = "'" + "','".join(basket_list) + "'"
    
    job_id_short = uuid.uuid4().hex[:6]
    date_str = datetime.now().strftime("%Y%m%d")
    model_name = f"{target_ticker}_basket_train_{date_str}_{job_id_short}"
    temp_rf_name = f"temp_rf_{job_id_short}"
    
    # Define Chronological Splits based on Market Mode
    if market_mode == "TRADITIONAL":
        eval_interval = "INTERVAL 2 YEAR"
        oos_interval = "INTERVAL 1 YEAR"
    else: # CRYPTO
        eval_interval = "INTERVAL 12 MONTH"
        oos_interval = "INTERVAL 6 MONTH"

    # BigQuery Multi-Statement Script: 
    # 1. Calculates max date. 2. Trains Temp RF. 3. Extracts top 30 features. 4. Trains final XGBoost.
    bq_script = f"""
        DECLARE max_date DATE;
        DECLARE eval_start DATE;
        DECLARE oos_start DATE;
        DECLARE top_features STRING;
        
        -- 1. Establish Chronological Boundaries
        SET max_date = (SELECT MAX(DATE(timestamp)) FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}` WHERE ticker IN ({basket_str}));
        SET eval_start = DATE_SUB(max_date, {eval_interval});
        SET oos_start = DATE_SUB(max_date, {oos_interval});
        
        -- 2. Dimensionality Reduction via Random Forest (Triple Barrier filter)
        CREATE OR REPLACE MODEL `{PROJECT_ID}.{DATASET_ID}.{temp_rf_name}`
        OPTIONS(
            model_type='RANDOM_FOREST_CLASSIFIER',
            input_label_cols=['target_5d'],
            data_split_method='CUSTOM',
            data_split_col='is_train'
        ) AS
        SELECT *, IF(DATE(timestamp) < eval_start, TRUE, FALSE) AS is_train 
        FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`
        WHERE ticker IN ({basket_str}) 
          AND target_5d IS NOT NULL
          AND DATE(timestamp) < oos_start; -- Strictly exclude OOS data
          
        -- 3. Extract Top 30 Features
        SET top_features = (
            SELECT STRING_AGG(feature, ', ') 
            FROM (
                SELECT feature FROM ML.FEATURE_IMPORTANCE(MODEL `{PROJECT_ID}.{DATASET_ID}.{temp_rf_name}`) 
                ORDER BY importance DESC LIMIT 30
            )
        );
        
        -- 4. Train Dynamic XGBoost Pipeline
        EXECUTE IMMEDIATE FORMAT(\"\"\"
            CREATE OR REPLACE MODEL `{PROJECT_ID}.{DATASET_ID}.%s`
            OPTIONS(
                model_type='BOOSTED_TREE_CLASSIFIER',
                input_label_cols=['target_5d'],
                data_split_method='CUSTOM',
                data_split_col='is_train',
                max_tree_depth=%d,
                l2_reg=%f,
                learn_rate=%f
            ) AS
            SELECT %s, target_5d, IF(DATE(timestamp) < '%t', TRUE, FALSE) AS is_train 
            FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`
            WHERE ticker IN (%s) 
              AND target_5d IS NOT NULL
              AND DATE(timestamp) < '%t'
        \"\"\", 
        '{model_name}', {profile['max_tree_depth']}, {profile['l2_reg']}, {profile['learn_rate']}, 
        top_features, eval_start, '{basket_str}', oos_start);
        
        -- 5. Cleanup
        DROP MODEL IF EXISTS `{PROJECT_ID}.{DATASET_ID}.{temp_rf_name}`;
    """

    # Submit job to BigQuery asynchronously
    bq_client = bigquery.Client(project=PROJECT_ID)
    job = bq_client.query(bq_script)
    
    # Save state to Firestore using the actual BQ Job ID
    fs_client = firestore.Client(project=PROJECT_ID)
    doc_ref = fs_client.collection("ml_pipeline_logs").document(job.job_id)
    doc_ref.set({
        "target_ticker": target_ticker,
        "market_mode": market_mode,
        "model_name": model_name,
        "tuning_profile": tuning_profile,
        "status": "RUNNING",
        "created_at": firestore.SERVER_TIMESTAMP
    })
    
    return (f"✅ ML Pipeline Started for {target_ticker} in {market_mode} mode. Job ID: {job.job_id}.\n"
            f"INSTRUCTION: Tell the user the model is compiling in BigQuery. "
            f"Poll status using `check_pipeline_logs` with this exact Job ID.")

@mcp.tool()
def check_pipeline_logs(job_id: str) -> str:
    """Checks the status of the BQML pipeline and processes final evaluation metrics."""
    bq_client = bigquery.Client(project=PROJECT_ID)
    fs_client = firestore.Client(project=PROJECT_ID)
    
    doc_ref = fs_client.collection("ml_pipeline_logs").document(job_id)
    doc = doc_ref.get()
    
    if not doc.exists:
        return f"❌ No pipeline found for Job ID {job_id}."
        
    data = doc.to_dict()
    if data.get("status") in ["SUCCESS_PRIME", "REJECTED"]:
        return f"Pipeline already completed. Status: {data['status']}."
        
    # Check BigQuery Job State
    try:
        job = bq_client.get_job(job_id)
    except Exception as e:
        return f"❌ Failed to fetch job status: {str(e)}"
        
    if job.state != "DONE":
        return f"⏳ Pipeline Status: RUNNING. Instruction: Inform user it is still processing."
        
    if job.error_result:
        doc_ref.update({"status": "FAILED", "error": str(job.error_result)})
        return f"❌ Pipeline Failed: {job.error_result['message']}"

    # Job is DONE. Now evaluate the final model.
    model_id = f"{PROJECT_ID}.{DATASET_ID}.{data['model_name']}"
    
    try:
        eval_sql = f"SELECT * FROM ML.EVALUATE(MODEL `{model_id}`)"
        eval_results = bq_client.query(eval_sql).to_dataframe()
        
        accuracy = eval_results['accuracy'].iloc[0]
        precision = eval_results.get('precision', pd.Series([0])).iloc[0]
        f1_score = eval_results.get('f1_score', pd.Series([0])).iloc[0]
        
        # Calculate OOS Start Date for the Backtest Agent
        oos_sql = f"SELECT DATE_SUB(MAX(DATE(timestamp)), {'INTERVAL 1 YEAR' if data['market_mode'] == 'TRADITIONAL' else 'INTERVAL 6 MONTH'}) as oos_start FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}` WHERE ticker = '{data['target_ticker']}'"
        oos_date = bq_client.query(oos_sql).to_dataframe()['oos_start'].iloc[0].strftime('%Y-%m-%d')
        
        metrics_dict = {"accuracy": float(accuracy), "precision": float(precision), "f1_score": float(f1_score)}
        
        if accuracy > 0.50:
            status = "SUCCESS_PRIME"
            doc_ref.update({
                "status": status,
                "metrics": metrics_dict,
                "out_of_sample_start_date": oos_date
            })
            return (f"✅ Model {data['model_name']} saved as PRIME.\n"
                    f"Accuracy: {accuracy:.2%}, Precision: {precision:.2%}, F1: {f1_score:.4f}\n"
                    f"INSTRUCTION: Model passed. You are cleared to begin backtesting using OOS start date: {oos_date}.")
        else:
            status = "REJECTED"
            bq_client.query(f"DROP MODEL IF EXISTS `{model_id}`").result()
            doc_ref.update({"status": status, "metrics": metrics_dict})
            return f"❌ Model REJECTED (Accuracy {accuracy:.2%} < 50%). Model deleted from BQ."

    except Exception as e:
        return f"❌ Evaluation Failed: {str(e)}"

@mcp.tool()
def delete_ml_model(job_id: str, explicit_user_confirmation: bool = False) -> str:
    """
    Deletes a trained BQML model and updates its Firestore log.
    Strict HITL Requirement: explicit_user_confirmation MUST be True, and you MUST 
    only set it to True if the user has explicitly authorized the deletion in the chat.
    
    Args:
        job_id: The exact BigQuery Job ID associated with the model.
        explicit_user_confirmation: Boolean flag confirming user approval.
    """
    if not explicit_user_confirmation:
        return "❌ HITL LOCK: Deletion aborted. You must ask the user for explicit permission to delete this model. Only call this tool again with explicit_user_confirmation=True once they agree."

    bq_client = bigquery.Client(project=PROJECT_ID)
    fs_client = firestore.Client(project=PROJECT_ID)
    
    doc_ref = fs_client.collection("ml_pipeline_logs").document(job_id)
    doc = doc_ref.get()
    
    if not doc.exists:
        return f"❌ Error: No pipeline record found for Job ID {job_id}."
        
    data = doc.to_dict()
    model_name = data.get("model_name")
    
    if not model_name:
         return "❌ Error: Document exists but contains no model_name to delete."

    model_id = f"{PROJECT_ID}.{DATASET_ID}.{model_name}"
    
    try:
        # Execute deletion in BigQuery
        bq_client.query(f"DROP MODEL IF EXISTS `{model_id}`").result()
        
        # Update Firestore state (We keep the log for auditing, but mark it DELETED)
        doc_ref.update({
            "status": "DELETED_BY_USER",
            "deleted_at": firestore.SERVER_TIMESTAMP
        })
        
        return f"✅ HITL CLEARED: Model `{model_name}` (Job: {job_id}) has been successfully deleted from BigQuery to optimize storage costs."
        
    except Exception as e:
        return f"❌ Failed to delete model: {str(e)}"