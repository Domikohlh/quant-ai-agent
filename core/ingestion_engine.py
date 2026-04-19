import logging
import pandas as pd
import yfinance as yf
import pandas_ta as ta
from datetime import timedelta
from google.cloud import bigquery
from core.database import DatabaseManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("IngestionEngine")

class DataIngestionEngine:
    def __init__(self, db_manager: DatabaseManager, dataset_id="market_data", table_name="historical_panel"):
        self.db = db_manager
        self.full_table_id = f"{self.db.project_id}.{dataset_id}.{table_name}"
        
        # Ensure the dataset exists
        dataset_ref = bigquery.Dataset(f"{self.db.project_id}.{dataset_id}")
        dataset_ref.location = self.db.region
        try:
            self.db.bq_client.get_dataset(dataset_ref)
        except Exception:
            self.db.bq_client.create_dataset(dataset_ref, exists_ok=True)
            logger.info(f"Created BigQuery dataset: {dataset_id}")

    def get_latest_timestamp(self, ticker: str):
        """Finds the last recorded timestamp for a ticker."""
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
            pass # Table might not exist yet
        return None

    def calculate_ta(self, df: pd.DataFrame) -> pd.DataFrame:
        """Applies core technical indicators."""
        if len(df) < 200:
            logger.warning("Insufficient data for 200 SMA. Returning without TA.")
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
        df.ta.zscore(close=df['Close'], length=30, append=True)
        df.ta.ppo(fast=12, slow=26, signal=9, append=True)
        df['pct_rank_20'] = df['Close'].rolling(20).rank(pct=True)
        df.ta.trix(length=30, append=True)
        df.ta.roc(length=10, append=True)
        df.ta.apo(fast=12, slow=26, append=True)
            
        float_cols = df.select_dtypes(include=['float64']).columns
        df[float_cols] = df[float_cols].astype('float32')
        df.dropna(inplace=True)
        return df

    def update_ticker(self, ticker: str, period: str = "5y", interval: str = "1d"):
        """Downloads, processes, and uploads data for a single ticker."""
        logger.info(f"Processing {ticker}...")
        last_date = self.get_latest_timestamp(ticker)
        
        try:
            if last_date:
                # Buffer: Fetch 60 days prior to warm up TA indicators
                buffer_start = last_date - timedelta(days=60)
                df = yf.download(ticker, start=buffer_start, interval=interval, auto_adjust=True, progress=False)
            else:
                df = yf.download(ticker, period=period, interval=interval, auto_adjust=True, progress=False)
                
            if df.empty:
                logger.warning(f"No data returned for {ticker}.")
                return
                
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df = self.calculate_ta(df)
            
            df.reset_index(inplace=True)
            time_col = "Datetime" if "Datetime" in df.columns else "Date"
            df.rename(columns={time_col: "timestamp"}, inplace=True)
            
            df.columns = [c.lower().replace(" ", "_").replace("-", "_") for c in df.columns]
            df["ticker"] = ticker.upper()

            if last_date:
                if df['timestamp'].dt.tz is None:
                    df['timestamp'] = df['timestamp'].dt.tz_localize('UTC')
                df = df[df['timestamp'] > last_date]

            if df.empty:
                logger.info(f"No new data for {ticker}.")
                return

            # Cost-efficient BQ load config
            job_config = bigquery.LoadJobConfig(
                write_disposition="WRITE_APPEND",
                schema_update_options=[bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION],
                time_partitioning=bigquery.TimePartitioning(
                    type_=bigquery.TimePartitioningType.DAY,
                    field="timestamp"
                ),
                clustering_fields=["ticker"]
            )

            job = self.db.bq_client.load_table_from_dataframe(df, self.full_table_id, job_config=job_config)
            job.result()
            
            logger.info(f"✅ Appended {len(df)} rows for {ticker}.")

        except Exception as e:
            logger.error(f"❌ Failed to update {ticker}: {str(e)}")