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
    def __init__(self, db_manager: DatabaseManager, dataset_id="market_data", table_name="historical_data"): 
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

    def calculate_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculates TAs, Permutation Windows, and Triple Barrier Labels."""
        if len(df) < 300: # Need enough rows for SMA_200 + Perm_72
            logger.warning("Insufficient data length for feature expansion.")
            return None
            
        # 1. Base Technical Indicators
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

        df.ta.zscore(close=df['Close'], length=30, append=True)
        df.ta.ppo(fast=12, slow=26, signal=9, append=True)
        df['pct_rank_20'] = df['Close'].rolling(20).rank(pct=True)
        df.ta.trix(length=30, append=True)
        df.ta.roc(length=10, append=True)
        df.ta.apo(fast=12, slow=26, append=True)

        # 2. Permutation Windows (Feature Expansion)
        raw_cols = {'timestamp', 'Date', 'Datetime', 'Open', 'High', 'Low', 'Close', 'Volume', 'ticker', 'source', 'pct_rank_20'}
        tech_indicators = [c for c in df.columns if c not in raw_cols]
        perm_windows = [1, 3, 6, 12, 24, 36, 48, 72]

        for col in tech_indicators:
            for w in perm_windows:
                # Momentum (Acceleration)
                df[f'{col}_diff_{w}'] = df[col].diff(w)
                # Volatility (Noise/Stability)
                df[f'{col}_vol_{w}'] = df[col].rolling(w).std()

        # 3. CRITICAL: Drop historical NaNs caused by the lookbacks (200 + 72)
        # We must do this BEFORE Triple Barrier so we don't accidentally drop today's data!
        if df.isna().all().any():
            df.dropna(axis=1, how='all', inplace=True)
        df.dropna(inplace=True)

        # 4. Triple Barrier Labeling (Vectorized)
        df['daily_ret'] = df['Close'].pct_change()
        df['volatility_20'] = df['daily_ret'].rolling(window=20).std()
        
        def apply_triple_barrier(data, horizon, pt=1.5, sl=1.5):
            target_col = f'target_{horizon}d'
            upper = data['Close'] * (1 + data['volatility_20'] * pt)
            lower = data['Close'] * (1 - data['volatility_20'] * sl)
            
            future_high = data['High'].rolling(window=horizon, min_periods=1).max().shift(-horizon)
            future_low = data['Low'].rolling(window=horizon, min_periods=1).min().shift(-horizon)
            future_close = data['Close'].shift(-horizon)
            
            hit_upper = future_high >= upper
            hit_lower = future_low <= lower
            
            data[target_col] = 0
            data.loc[hit_upper & ~hit_lower, target_col] = 1
            data.loc[hit_lower & ~hit_upper, target_col] = -1
            
            both = hit_upper & hit_lower
            data.loc[both & (future_close > data['Close']), target_col] = 1
            data.loc[both & (future_close < data['Close']), target_col] = -1
            return data

        df = apply_triple_barrier(df, horizon=5)
        df = apply_triple_barrier(df, horizon=10)
        df.drop(columns=['daily_ret', 'volatility_20'], inplace=True)

        # 5. Downcast to save memory in BigQuery
        float_cols = df.select_dtypes(include=['float64']).columns
        df[float_cols] = df[float_cols].astype('float32')

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

            df = self.calculate_features(df)
            
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
            WHEN MATCHED THEN
              UPDATE SET 
                target_5d = S.target_5d,
                target_10d = S.target_10d
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