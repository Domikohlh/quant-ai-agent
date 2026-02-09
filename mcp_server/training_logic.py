# worker.py
import argparse
import logging
import sys
import os
import json

# Add project root to path to allow importing data_server
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from data_server import train_basket_model_core, run_feature_analysis_core

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TrainingWorker")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    # Task Selector
    parser.add_argument("--task", type=str, choices=["train", "analyze"], default="train", help="Which task to run")
    
    # Shared Args
    parser.add_argument("--ticker", type=str, required=True)
    
    # Train Args
    parser.add_argument("--bucket", type=str, help="GCS Bucket (Train only)")
    
    # Analysis Args
    parser.add_argument("--basket", type=str, default=None)
    parser.add_argument("--barrier_width", type=float, default=1.0)
    parser.add_argument("--time_horizon", type=int, default=5)
    parser.add_argument("--top_n", type=int, default=15)

    args = parser.parse_args()

    try:
        if args.task == "train":
            if not args.bucket:
                raise ValueError("--bucket is required for training task")
                
            logger.info(f"🚀 Starting TRAINING for {args.ticker}...")
            result = train_basket_model_core(args.ticker, args.bucket)
            logger.info(f"✅ Train Complete: {result}")

        elif args.task == "analyze":
            logger.info(f"🔬 Starting ANALYSIS for {args.ticker} (Basket: {args.basket})...")
            result = run_feature_analysis_core(
                ticker=args.ticker,
                basket=args.basket,
                barrier_width=args.barrier_width,
                time_horizon=args.time_horizon,
                top_n=args.top_n
            )
            # Worker logs are captured by Cloud Logging, so printing JSON helps debugging
            logger.info(f"✅ Analysis Complete: {json.dumps(result, default=str)}")
        
    except Exception as e:
        logger.error(f"❌ Training Failed: {e}")
        sys.exit(1)