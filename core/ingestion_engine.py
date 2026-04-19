import logging
import pandas as pd
import yfinance as yf
import pandas_ta as ta
from datetime import timedelta
from google.cloud import bigquery
from core.database import DatabaseManager
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("IngestionEngine")

class DataIngestionEngine:
    def __init__(self, db_manager: DatabaseManager, dataset_id="market_data", table_name="historical_data"): # <-- Name changed here
        self.db = db_manager
        self.dataset_id = dataset_id
        self.table_name = table_name 
        self.full_table_id = f"{self.db.project_id}.{self.dataset_id}.{self.table_name}"
        
        dataset_ref = bigquery.Dataset(f"{self.db.project_id}.{self.dataset_id}")
        dataset_ref.location = self.db.region
        try:
            self.db.bq_client.get_dataset(dataset_ref)
        except Exception:
            self.db.bq_client.create_dataset(dataset_ref, exists_ok=True)

    def get_latest_timestamp(self, ticker: str):
        query = f"""
            SELECT MAX(timestamp) as max_date 
            FROM `{self.full_table_id}` 
            WHERE ticker = @ticker
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("ticker", "STRING", ticker)]
        )
        try:
            result = list(self.db.bq_client.query(query, job_config=job_config).result())
            if result and result[0].max_date:
                return pd.Timestamp(result[0].max_date).tz_convert('UTC')
        except Exception:
            pass 
        return None

    def calculate_ta(self, df: pd.DataFrame) -> pd.DataFrame:
        if len(df) < 200:
            return df
            
        df.ta.rsi(append=True)
        df.ta.macd(fast=12, slow=26, signal=9, append=True)
        df.ta.macd(fast=10, slow=24, signal=7, append=True)
        df.ta.macd(fast=5, slow=13, signal=4, append=True)
        df.ta.sma(length=50, append=True)
        df.ta.sma(length=200, append=True)
        df.ta.bbands(append=True)
        df.ta.atr(length=14, append=True)
        if 'Volume' in df.columns:
            df.ta.vwap(append=True)

        # New technical indicators
        df.ta.zscore(length=30, append=True)
        df.ta.ppo(fast=12, slow=26, signal=9, append=True)
        df['pct_rank_20'] = df['Close'].rolling(20).rank(pct=True)
        df.ta.trix(length=30, append=True)
        df.ta.roc(length=10, append=True)
        df.ta.apo(fast=12, slow=26, append=True)
            
        float_cols = df.select_dtypes(include=['float64']).columns
        df[float_cols] = df[float_cols].astype('float32')
        df.dropna(inplace=True)
        return df

    def update_ticker(self, ticker: str, period: str = "5y", interval: str = "1d") -> pd.DataFrame:
        """Downloads and processes data, returning the DataFrame instead of uploading."""
        logger.info(f"Processing {ticker}...")
        last_date = self.get_latest_timestamp(ticker)
        
        try:
            if last_date:
                buffer_start = last_date - timedelta(days=60)
                df = yf.download(ticker, start=buffer_start, interval=interval, auto_adjust=True, progress=False)
            else:
                df = yf.download(ticker, period=period, interval=interval, auto_adjust=True, progress=False)
                
            if df.empty:
                logger.warning(f"No data for {ticker}.")
                return None
                
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df = self.calculate_ta(df)
            
            df.reset_index(inplace=True)
            time_col = "Datetime" if "Datetime" in df.columns else "Date"
            df.rename(columns={time_col: "timestamp"}, inplace=True)
            
            # The column name fix is here
            df.columns = [c.lower().replace(" ", "_").replace("-", "_").replace(".", "_").replace("%", "pct") for c in df.columns]
            df["ticker"] = ticker.upper()

            if last_date:
                if df['timestamp'].dt.tz is None:
                    df['timestamp'] = df['timestamp'].dt.tz_localize('UTC')
                df = df[df['timestamp'] > last_date]

            if df.empty:
                logger.info(f"No new data for {ticker}.")
                return None

            return df # RETURN IT, DO NOT UPLOAD IT

        except Exception as e:
            logger.error(f"❌ Failed to update {ticker}: {str(e)}")
            return None

    def upload_batch(self, df_batch: pd.DataFrame):
        """Uploads via a Staging Table and MERGE to guarantee ZERO duplicates."""
        if df_batch.empty:
            logger.info("Batch is empty. Nothing to upload.")
            return

        logger.info(f"Uploading batch of {len(df_batch)} rows via Staging to guarantee no duplicates...")
        
        # 1. Define the Staging Table
        staging_table_id = f"{self.db.project_id}.{self.dataset_id}.staging_panel"
        
        # 2. Upload to Staging (Overwriting it completely)
        staging_config = bigquery.LoadJobConfig(
            write_disposition="WRITE_TRUNCATE" # Always overwrite staging
        )
        job = self.db.bq_client.load_table_from_dataframe(df_batch, staging_table_id, job_config=staging_config)
        job.result()
        logger.info("Staging upload complete. Executing MERGE into main table...")

        # 3. Execute the MERGE Statement
        # This guarantees that if a Ticker + Timestamp combination already exists, it will NOT be duplicated.
        merge_query = f"""
            MERGE `{self.full_table_id}` T
            USING `{staging_table_id}` S
            ON T.ticker = S.ticker AND T.timestamp = S.timestamp
            WHEN NOT MATCHED THEN
              INSERT ROW
        """
        
        try:
            merge_job = self.db.bq_client.query(merge_query)
            merge_job.result() # Wait for the query to finish
            logger.info(f"✅ MERGE complete! Inserted net-new rows into {self.table_name}.")
        except Exception as e:
            # If the main table doesn't exist yet (first run), the MERGE will fail.
            logger.warning(f"MERGE failed (likely first run). Creating main table directly from staging...")
            
            # Pure BigQuery SQL is much faster and safer than re-uploading the dataframe
            init_query = f"""
                CREATE TABLE `{self.full_table_id}`
                PARTITION BY DATE(timestamp)
                CLUSTER BY ticker
                AS SELECT * FROM `{staging_table_id}`
            """
            try:
                init_job = self.db.bq_client.query(init_query)
                init_job.result()
                logger.info(f"✅ Main table ({self.table_name}) initialized successfully from staging!")
            except Exception as init_e:
                logger.error(f"❌ Failed to initialize table: {str(init_e)}")