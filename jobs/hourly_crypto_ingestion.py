import os
import sys
import logging
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# Ensure the core modules can be imported from the parent directory
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
sys.path.append(str(project_root))

from core.database import DatabaseManager
from core.crypto_ingestion_engine import CryptoIngestionEngine

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("HourlyCryptoJob")

def main():
    project_id = os.getenv("GCP_PROJECT_ID")
    region = os.getenv("GCP_COMPUTE_REGION", "us-central1")
    
    if not project_id:
        logger.error("GCP_PROJECT_ID environment variable is missing. Exiting.")
        sys.exit(1)
    
    # Initialize the centralized Database Manager
    db = DatabaseManager(
        project_id=project_id, 
        region=region,
        sql_instance_name="dummy", # Not needed for BQ operations
        sql_db_name="dummy"
    )
    
    # Initialize the Crypto Engine
    engine = CryptoIngestionEngine(db_manager=db)
    
    # We strictly target Bitcoin for the hourly execution bot
    target_symbol = 'BTC/USDT'
    
    logger.info(f"🚀 Starting hourly data ingestion for {target_symbol}...")
    
    # 1. Download, process technicals, and calculate forward targets
    df = engine.update_ticker(symbol=target_symbol, timeframe="1h")
    
    # 2. Upload via Staging -> MERGE to guarantee zero duplicates
    if df is not None and not df.empty:
        engine.upload_batch(df)
    else:
        logger.info(f"No new data to upload for {target_symbol}.")
        
    logger.info("✅ Hourly crypto ingestion job complete.")

if __name__ == "__main__":
    main()