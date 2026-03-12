# worker.py
import argparse
import os
import sys
import logging
from pathlib import Path

# Add project root to sys.path so we can import helpers
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
sys.path.append(str(project_root))

from helpers.ml_helper import run_feature_analysis_core, train_basket_model_core

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TrainingJob")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Quant Training Job Entry Point")
    
    # --- 1. The Critical Missing Argument ---
    parser.add_argument("--task", type=str, required=True, choices=["analyze", "train"], help="Which task to run")

    # --- 2. Shared Arguments ---
    parser.add_argument("--ticker", type=str, required=True, help="Target stock ticker (e.g. NVDA)")
    parser.add_argument("--training_end_date", type=str, default="2024-12-31", help="Hard cutoff date for train/test split")
    parser.add_argument("--custom_params", type=str, default=None, help="JSON string of hyperparameters")

    # --- 3. Analysis Specific Arguments ---
    parser.add_argument("--basket", type=str, default=None, help="Comma-separated basket tickers")
    parser.add_argument("--barrier_width", type=float, default=1.0)
    parser.add_argument("--time_horizon", type=int, default=5)
    parser.add_argument("--top_n", type=int, default=15)

    # --- 4. Training Specific Arguments ---
    parser.add_argument("--bucket", type=str, default=None, help="GCS Bucket for model saving")

    args = parser.parse_args()
    
    logger.info(f"🚀 Starting Job: {args.task} for {args.ticker} (Cutoff: {args.training_end_date})")

    try:
        if args.task == "analyze":
            # Run Feature Engineering
            result = run_feature_analysis_core(
                ticker=args.ticker,
                basket=args.basket,
                barrier_width=args.barrier_width,
                time_horizon=args.time_horizon,
                top_n=args.top_n,
                training_end_date=args.training_end_date
            )
            print(result) # Print JSON to stdout so Cloud Logging captures it

        elif args.task == "train":
            # Run Model Training
            # Ensure bucket is set
            bucket = args.bucket or os.getenv("GCS_MODEL_BUCKET")
            if not bucket:
                raise ValueError("Bucket name is required for training (env var GCS_MODEL_BUCKET or --bucket arg)")
            # Parse the JSON string back into a dictionary
            parsed_params = None
            if args.custom_params:
                try:
                    parsed_params = json.loads(args.custom_params)
                    logging.info(f"Loaded custom parameters for training: {parsed_params}")
                except json.JSONDecodeError as e:
                    logging.error(f"Failed to parse custom_params JSON: {e}")
                    
            result = train_basket_model_core(
                target_ticker=args.ticker,
                save_bucket=bucket,
                training_end_date=args.training_end_date,
                custom_params=parsed_params
            )
            print(result)

    except Exception as e:
        logger.error(f"Job Failed: {e}")
        sys.exit(1) # Exit with error code so Cloud Run marks job as failed