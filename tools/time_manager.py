# tools/time_manager.py
import pandas_market_calendars as mcal
from datetime import datetime
import pytz

# Define New York Timezone
NY_TZ = pytz.timezone('America/New_York')

# Global variable to hold manual override state
# In a real app, this might be a database flag or Redis key
MANUAL_OVERRIDE = None

def set_manual_mode(mode: str):
    """Sets a manual override: 'high', 'low', or None (auto)."""
    global MANUAL_OVERRIDE
    MANUAL_OVERRIDE = mode
    if mode:
        print(f"🔧 SYSTEM OVERRIDE: Switched to {mode.upper()} MODE.")
    else:
        print(f"🔧 SYSTEM OVERRIDE: Switched to AUTO MODE.")

def get_market_status():
    """
    Determines System Mode.
    Supports Manual Override for Backtesting/Testing.
    
    Returns:
        status (str): 'OPEN', 'EXTENDED', 'CLOSED'
        mode (str): 'HIGH_MODE' (Active Trading), 'LOW_MODE' (Passive Monitoring)
        interval (int): Seconds until next run
    """
    # 1. CHECK MANUAL OVERRIDE
    if MANUAL_OVERRIDE == "high":
        return "TESTING", "HIGH_MODE", 60 # Run fast for testing
    elif MANUAL_OVERRIDE == "low":
        return "TESTING", "LOW_MODE", 60

    # 2. STANDARD LOGIC
    now_ny = datetime.now(NY_TZ)
    today_date = now_ny.date()
    
    nyse = mcal.get_calendar('NYSE')
    schedule = nyse.schedule(start_date=today_date, end_date=today_date)
    
    # CASE A: WEEKEND / HOLIDAY
    if schedule.empty:
        # User Requirement: Monitor night market (news/sentiment) even on holidays
        # Frequency: Every 4 hours
        return "CLOSED", "LOW_MODE", 3600 * 4
        
    market_open = schedule.iloc[0]['market_open'].to_pydatetime()
    market_close = schedule.iloc[0]['market_close'].to_pydatetime()
    
    # Timezone fix
    if market_open.tzinfo is None: market_open = NY_TZ.localize(market_open)
    if market_close.tzinfo is None: market_close = NY_TZ.localize(market_close)

    current_time = now_ny
    
    # CASE B: MARKET OPEN (High Frequency)
    if market_open <= current_time <= market_close:
        return "OPEN", "HIGH_MODE", 900 # 15 mins
    
    # CASE C: PRE/POST MARKET (Extended Hours)
    # 4:00 AM - 9:30 AM AND 4:00 PM - 8:00 PM
    pre_start = market_open.replace(hour=4, minute=0)
    post_end = market_close.replace(hour=20, minute=0)
    
    if (pre_start <= current_time < market_open) or (market_close < current_time <= post_end):
        return "EXTENDED", "LOW_MODE", 3600 # 1 Hour

    # CASE D: DEEP NIGHT
    # Instead of shutting down, we run in Low Mode to check for macro shocks
    return "CLOSED", "LOW_MODE", 3600 * 2 # 2 Hours
