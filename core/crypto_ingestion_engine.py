import logging
import pandas as pd
import pandas_ta as ta
import numpy as np
import ccxt
import time
from datetime import datetime, timedelta
from google.cloud import bigquery
from core.database import DatabaseManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("CryptoIngestionEngine")

class CryptoIngestionEngine:
    def __init__(self, db_manager: DatabaseManager, dataset_id="market_data", table_name="crypto_historical"):
        self.db = db_manager
        self.dataset_id = dataset_id
        self.table_name = table_name 
        self.full_table_id = f"{self.db.project_id}.{self.dataset_id}.{self.table_name}"
        
        # Ensure Dataset Exists
        dataset_ref = bigquery.Dataset(f"{self.db.project_id}.{self.dataset_id}")
        dataset_ref.location = self.db.region
        try:
            self.db.bq_client.get_dataset(dataset_ref)
        except Exception:
            self.db.bq_client.create_dataset(dataset_ref, exists_ok=True)

    def get_latest_timestamp(self, ticker: str):
        """Checks BigQuery for the last downloaded crypto candle."""
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
        """Calculates Base TAs, Permutation Windows, and 24h Forward Targets."""
        if len(df) < 300: # Need enough rows for SMA_200 + Perm_72
            logger.warning("Insufficient data length for crypto feature expansion.")
            return None
            
        # 1. Base Technical Indicators (Mirrors equities ingestion_engine.py)
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

        # Crypto Volatility for Barrier (24h)
        df['return_1h'] = df['Close'].pct_change()
        df['volatility_24h'] = df['return_1h'].rolling(window=24).std()

        # 3. CRITICAL: Drop historical NaNs caused by the lookbacks (200 + 72)
        if df.isna().all().any():
            df.dropna(axis=1, how='all', inplace=True)
        df.dropna(inplace=True)

        # 4. Hourly Triple Barrier Labeling (Forward 24 Hours)
        def apply_triple_barrier_hourly(data, horizon=24, pt=2.0, sl=2.0):
            target_col = f'target_{horizon}h'
            # Volatility-adjusted barriers
            upper = data['Close'] * (1 + data['volatility_24h'] * pt)
            lower = data['Close'] * (1 - data['volatility_24h'] * sl)
            
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

        df = apply_triple_barrier_hourly(df, horizon=24)
        df.drop(columns=['return_1h', 'volatility_24h'], inplace=True)

        # 5. Downcast to save memory in BigQuery
        float_cols = df.select_dtypes(include=['float64']).columns
        df[float_cols] = df[float_cols].astype('float32')

        return df

    def fetch_binance_data(self, symbol: str, timeframe: str = '1h', since_ts: int = None, limit: int = 1000) -> pd.DataFrame:
        """Pulls OHLCV data from CCXT."""
        exchange = ccxt.binanceus({'enableRateLimit': True})
        all_ohlcv = []
        
        while True:
            try:
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since_ts, limit=limit)
                if len(ohlcv) == 0:
                    break
                
                all_ohlcv.extend(ohlcv)
                since_ts = ohlcv[-1][0] + 1 # Advance pagination
                
                if since_ts >= exchange.milliseconds():
                    break
            except Exception as e:
                logger.error(f"API Error: {e}. Retrying...")
                time.sleep(5)
                
        df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize('UTC')
        df['ticker'] = symbol.replace('/', '')
        df = df.drop_duplicates(subset=['timestamp']).reset_index(drop=True)
        return df

    def update_ticker(self, symbol: str = 'BTC/USDT', timeframe: str = '1h') -> pd.DataFrame:
        """Downloads, processes, and returns the dataframe for the batch uploader."""
        db_ticker = symbol.replace('/', '')
        logger.info(f"Processing Crypto {db_ticker}...")
        
        last_date = self.get_latest_timestamp(db_ticker)
        
        try:
            if last_date:
                # Need enough history to calculate the 200 SMA + 72 Permutation safely
                buffer_start = last_date - timedelta(hours=350) 
                since_ts = int(buffer_start.timestamp() * 1000)
                df = self.fetch_binance_data(symbol, timeframe, since_ts=since_ts)
            else:
                # Pull last 3 years
                logger.info(f"First run detected. Pulling 3 years of {symbol} history...")
                since_ts = int((datetime.utcnow() - timedelta(days=1095)).timestamp() * 1000)
                df = self.fetch_binance_data(symbol, timeframe, since_ts=since_ts)
                
            if df.empty:
                logger.warning(f"No data fetched for {symbol}.")
                return None

            df = self.calculate_features(df)
            
            # Format columns for BigQuery
            df.columns = [c.lower().replace(" ", "_").replace("-", "_").replace(".", "_").replace("%", "pct") for c in df.columns]

            if last_date:
                df = df[df['timestamp'] > last_date]

            if df.empty:
                logger.info(f"No new hourly data for {db_ticker}.")
                return None

            return df

        except Exception as e:
            logger.error(f"❌ Failed to update {symbol}: {str(e)}")
            return None

    def upload_batch(self, df_batch: pd.DataFrame):
        """Uses your exact Staging -> MERGE logic to prevent duplicates."""
        if df_batch.empty:
            logger.info("Batch is empty. Nothing to upload.")
            return

        logger.info(f"Uploading Crypto batch of {len(df_batch)} rows via Staging...")
        staging_table_id = f"{self.db.project_id}.{self.dataset_id}.staging_crypto"
        
        staging_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
        self.db.bq_client.load_table_from_dataframe(df_batch, staging_table_id, job_config=staging_config).result()

        merge_query = f"""
            MERGE `{self.full_table_id}` T
            USING `{staging_table_id}` S
            ON T.ticker = S.ticker AND T.timestamp = S.timestamp
            WHEN MATCHED THEN
              UPDATE SET target_24h = S.target_24h
            WHEN NOT MATCHED THEN
              INSERT ROW
        """
        try:
            self.db.bq_client.query(merge_query).result()
            logger.info(f"✅ Crypto MERGE complete! Inserted into {self.table_name}.")
        except Exception:
            logger.warning(f"Creating main crypto table directly from staging...")
            init_query = f"""
                CREATE TABLE `{self.full_table_id}`
                PARTITION BY DATE(timestamp)
                CLUSTER BY ticker
                AS SELECT * FROM `{staging_table_id}`
            """
            self.db.bq_client.query(init_query).result()
            logger.info(f"✅ Main crypto table initialized successfully!")