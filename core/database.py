# core/database.py
import os
import io
import logging
import sys

from google.cloud import bigquery, firestore, storage
from google.cloud.sql.connector import Connector
import sqlalchemy
from sqlalchemy import text
import joblib

# Need to remove the Cloud SQL running, instead, use firestore and bigquery 

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, project_id: str, region: str, sql_instance_name: str, sql_db_name: str):
        self.project_id = project_id
        self.region = region
        
        # 1. BigQuery Client (Market Data)
        self.bq_client = bigquery.Client(project=project_id)
        
        # 2. Firestore Client (Agent Thoughts)
        self.firestore_client = firestore.Client(project=project_id)
        self.storage_client = storage.Client(project=project_id)
        
        # 3. Cloud SQL Connection (Transactions)
        #self.sql_instance = sql_instance_name # Format: "project:region:instance"
        #self.sql_db = sql_db_name
        #self.sql_connector = Connector()
        #self.pool = self._init_sql_pool()

    #def _init_sql_pool(self):
    #    """Creates a SQLAlchemy pool using the Cloud SQL Connector."""
    #    def getconn():
    #        conn = self.sql_connector.connect(
    #            self.sql_instance,
    #            "pg8000",
    #            user=os.environ.get("DB_USER"),
    #            password=os.environ.get("DB_PASS"),
    #            db=self.sql_db
            #)
     #       return conn

      #  return sqlalchemy.create_engine(
       #     "postgresql+pg8000://",
        #    creator=getconn,
        #)

    # --- Helper: Save Market Data ---
    def save_market_data(self, df, table_id="market_data.history"):
        """Saves a Pandas DataFrame to BigQuery."""
        dataset_id = table_id.split('.')[0]  # Extracts "market_data"
        full_dataset_id = f"{self.project_id}.{dataset_id}"
        
        # We explicitly enforce 'us-central1' for storage, regardless of where the Agent runs.
        # You can also load this from os.getenv("BQ_LOCATION", "us-central1")
        STORAGE_LOCATION = "us-central1" 
        
        dataset_ref = bigquery.Dataset(full_dataset_id)
        dataset_ref.location = STORAGE_LOCATION
        
        try:
            # exists_ok=True ensures this never crashes. 
            # If the folder was deleted 5 seconds ago, this line instantly recreates it.
            self.bq_client.create_dataset(dataset_ref, exists_ok=True)
        except Exception as e:
            # Log warning but try to proceed (sometimes permissions invoke false negatives)
            logger.warning(f"Dataset check/creation note: {e}")

        job_config = bigquery.LoadJobConfig(
            write_disposition="WRITE_APPEND",
            schema_update_options=[
                bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION
            ]
        )
        
        # 2. Upload
        job = self.bq_client.load_table_from_dataframe(
            df, f"{self.project_id}.{table_id}", job_config=job_config
        )
        job.result()  # Wait for completion
        logger.info("Loaded %s rows to BigQuery: %s", len(df), table_id)

    # --- Helper: Save ML Model to GCS ---
    def save_model_to_gcs(self, model, bucket_name: str, filename: str, metadata: dict = None) -> str:
        """
        Saves a model object to GCS using Joblib compression and attaches metadata.
        Returns the gs:// URI.
        """
        try:
            bucket = self.storage_client.bucket(bucket_name)
            blob = bucket.blob(filename)
            
            # --- NEW: Attach custom metadata if provided ---
            if metadata:
                blob.metadata = metadata
            
            buffer = io.BytesIO()
            import joblib
            joblib.dump(model, buffer, compress=3) 
            buffer.seek(0)
            
            blob.upload_from_file(buffer, content_type='application/octet-stream')
            gcs_uri = f"gs://{bucket_name}/{filename}"
            logger.info(f"Saved model to {gcs_uri} with metadata: {metadata}")
            return gcs_uri
        except Exception as e:
            logger.error(f"Failed to save model to GCS: {e}")
            raise e
    
    def get_latest_model_file(self, bucket_name: str, ticker: str) -> str:
        """
        Finds the most recent model file for a ticker in the GCS bucket.
        Returns the filename (str) or None.
        """
        try:
            blobs = list(self.storage_client.list_blobs(bucket_name, prefix=f"models/{ticker}_basket_"))
            if not blobs:
                return None
            
            # Sort by time (newest first)
            blobs.sort(key=lambda x: x.time_created, reverse=True)
            latest_blob = blobs[0]
            logger.info(f"Found latest model: {latest_blob.name}")
            return latest_blob.name
        except Exception as e:
            logger.warning(f"Could not list models: {e}")
            return None

    def load_model_from_gcs(self, bucket_name: str, filename: str):
        """
        Downloads and deserializes a model from GCS.
        """
        try:
            bucket = self.storage_client.bucket(bucket_name)
            blob = bucket.blob(filename)
            
            buffer = io.BytesIO()
            blob.download_to_file(buffer)
            buffer.seek(0)
            
            model = joblib.load(buffer)
            logger.info(f"Loaded model from gs://{bucket_name}/{filename}")
            return model
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            return None
            
    # --- Helper: Save Agent Log ---
    def log_agent_thought(self, thought_data: dict):
        """Saves a dictionary (from AgentThought model) to Firestore."""
        doc_ref = self.firestore_client.collection("agent_logs").document()
        doc_ref.set(thought_data)
        logger.info("Logged agent thought: %s", doc_ref.id)

    # --- Helper: Save Transaction (Updated for Firestore) ---
    def save_transaction(self, transaction_data: dict):
        """Saves a trade to Firestore instead of PostgreSQL."""
        try:
            # If the trade has an order_id, we use it as the Firestore Document ID
            order_id = transaction_data.get("order_id")
            
            if order_id:
                doc_ref = self.firestore_client.collection("transactions").document(str(order_id))
            else:
                # Let Firestore auto-generate an ID if one isn't provided
                doc_ref = self.firestore_client.collection("transactions").document()
            
            # Firestore requires datetime objects, ensure timestamp is compatible
            # (Assuming transaction_data['timestamp'] is already a datetime object or string)
            
            doc_ref.set(transaction_data)
            logger.info("Saved transaction to Firestore: %s", doc_ref.id)
            
        except Exception as e:
            logger.error(f"Failed to save transaction to Firestore: {e}")
            raise e

    def create_tables(self):
        """Creates the necessary tables if they don't exist."""
        # Define the SQL schema
        create_transactions_table = text("""
            CREATE TABLE IF NOT EXISTS transactions (
                order_id VARCHAR(50) PRIMARY KEY,
                agent_id VARCHAR(50),
                symbol VARCHAR(10),
                side VARCHAR(10),
                quantity DECIMAL,
                price DECIMAL,
                status VARCHAR(20),
                timestamp TIMESTAMP,
                fees DECIMAL DEFAULT 0.0
            );
        """)
        
        # Execute it
        with self.pool.connect() as db_conn:
            db_conn.execute(create_transactions_table)
            db_conn.commit()
        logger.info("Tables verified/created successfully.")

    def get_latest_record_info(self, table_id: str, ticker: str):
        """
        Inspects the BigQuery table to find the date column name and the 
        latest timestamp for the given ticker.
        
        Returns:
            tuple: (latest_date, date_column_name)
            - latest_date: datetime object or None if no data exists.
            - date_column_name: str (e.g., 'Date', 'timestamp', 'datetime')
        """
        try:
            full_table_id = f"{self.project_id}.{table_id}"
            table = self.bq_client.get_table(full_table_id)
            
            # 1. Dynamically find the date/timestamp column
            # We look for standard names or a specific type if needed.
            schema_field_names = [field.name for field in table.schema]
            
            # Priority check for common time column names
            date_col = None
            for candidate in ["timestamp", "Date", "datetime", "t"]:
                if candidate in schema_field_names:
                    date_col = candidate
                    break
            
            if not date_col:
                # Fallback: Assume the schema mismatch error implies 'Date' is likely there 
                # if 'timestamp' failed. Or just pick the first TIMESTAMP field.
                for field in table.schema:
                    if field.field_type in ["TIMESTAMP", "DATE", "DATETIME"]:
                        date_col = field.name
                        break
            
            # If still None, we can't do incremental load safely.
            if not date_col:
                logger.warning(f"Could not identify a date column in {table_id}. Schema: {schema_field_names}")
                return None, "timestamp" # Default fallback

            # 2. Query for the latest date
            query = f"""
                SELECT MAX({date_col}) as max_date 
                FROM `{full_table_id}` 
                WHERE ticker = @ticker
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[bigquery.ScalarQueryParameter("ticker", "STRING", ticker)]
            )
            
            result = self.bq_client.query(query, job_config=job_config).result()
            row = next(result)
            return row.max_date, date_col

        except Exception as e:
            # If table doesn't exist or other error, return None to trigger full load
            logger.warning(f"Could not fetch latest record: {e}")
            return None, "timestamp"