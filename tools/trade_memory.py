# tools/trade_memory.py
import sqlite3
import os
from datetime import datetime, timedelta

DB_FILE = "trade_memory.db"

def _get_connection():
    """Creates a connection and ensures the table exists."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Create table if it doesn't exist
    # usage: outcome stores 'EXECUTED', 'REJECTED_RISK', 'REJECTED_HUMAN'
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS decision_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            action TEXT NOT NULL,
            outcome TEXT NOT NULL,
            reasoning TEXT,
            strategy_used TEXT
        )
    ''')
    
    # Create an index on symbol/timestamp for fast lookups by the Quant Analyst
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_symbol_time 
        ON decision_history (symbol, timestamp)
    ''')
    
    conn.commit()
    return conn

def log_decision(symbol: str, action: str, outcome: str, reasoning: str, strategy: str = "N/A"):
    """
    Logs a trading decision into the SQLite database.
    """
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        now_str = datetime.now().isoformat()
        
        cursor.execute('''
            INSERT INTO decision_history (timestamp, symbol, action, outcome, reasoning, strategy_used)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (now_str, symbol, action, outcome, reasoning, strategy))
        
        conn.commit()
        print(f"🧠 MEMORY UPDATED: {symbol} -> {outcome}")
    except sqlite3.Error as e:
        print(f"⚠️ MEMORY ERROR: {e}")
    finally:
        conn.close()

def fetch_recent_memory(symbol: str, lookback_days: int = 7) -> list[str]:
    """
    Retrieves distinct decisions for a symbol from the last N days.
    Used by Quant Analyst to avoid repeating mistakes.
    """
    conn = _get_connection()
    relevant_memories = []
    
    try:
        cursor = conn.cursor()
        
        # Calculate cutoff date
        cutoff_date = (datetime.now() - timedelta(days=lookback_days)).isoformat()
        
        # SQL Query: Get recent logs for this symbol, newest first
        cursor.execute('''
            SELECT timestamp, outcome, reasoning 
            FROM decision_history 
            WHERE symbol = ? AND timestamp > ?
            ORDER BY timestamp DESC
            LIMIT 5
        ''', (symbol, cutoff_date))
        
        rows = cursor.fetchall()
        
        for r in rows:
            # Parse timestamp for readable display
            dt = datetime.fromisoformat(r[0])
            date_str = dt.strftime("%Y-%m-%d")
            outcome = r[1]
            reason = r[2]
            
            relevant_memories.append(f"[{date_str}] {outcome}: {reason}")
            
    except sqlite3.Error as e:
        print(f"⚠️ MEMORY READ ERROR: {e}")
    finally:
        conn.close()
        
    return relevant_memories

def get_portfolio_summary_stats():
    """
    Optional: Helper for the Portfolio Manager to see win/loss stats.
    """
    conn = _get_connection()
    stats = {}
    try:
        cursor = conn.cursor()
        # Count rejections vs executions
        cursor.execute('''
            SELECT outcome, COUNT(*) 
            FROM decision_history 
            GROUP BY outcome
        ''')
        stats = dict(cursor.fetchall())
    finally:
        conn.close()
    return stats
