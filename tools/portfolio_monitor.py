# tools/portfolio_monitor.py
import pandas as pd
import numpy as np
import yfinance as yf
from tools.portfolio import get_current_portfolio

def calculate_portfolio_metrics(market_data=None):
    """
    Evaluates Portfolio Health with STRICT TYPE SAFETY.
    Converts all numpy types to python native types to prevent Checkpoint crashes.
    """
    print("📊 CALCULATING PORTFOLIO HEALTH METRICS...")
    
    # 1. Get Live Holdings
    portfolio = get_current_portfolio()
    holdings = portfolio.get('holdings', [])
    
    # Force native float conversion for equity
    total_equity = float(portfolio.get('total_equity', 0))
    
    if not holdings or total_equity == 0:
        return {
            "status": "CASH_ONLY",
            "risk_score": 0,
            "sectors": {},
            "recommendation": "BUILD_PORTFOLIO"
        }

    df = pd.DataFrame(holdings)
    
    # 2. Calculate Weights (Ensure native types)
    # Force 'Value' to be numeric (float)
    df['Value'] = pd.to_numeric(df['Value'], errors='coerce').fillna(0.0)
    df['weight'] = df['Value'] / total_equity
    
    # 3. Concentration Risk (HHI Index)
    # .sum() returns numpy.float64, so we wrap in float()
    raw_hhi = (df['weight'] ** 2).sum() * 10000
    hhi = float(raw_hhi)
    
    concentration_status = "SAFE"
    if hhi > 2500: concentration_status = "HIGH_CONCENTRATION"
    elif hhi > 1500: concentration_status = "MODERATE_CONCENTRATION"

    # 4. Sector Allocation
    sector_exposure = {}
    portfolio_beta = 0.0
    
    for symbol in df['Symbol']:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            sector = info.get('sector', 'Unknown')
            # Ensure beta is native float
            raw_beta = info.get('beta', 1.0)
            beta = float(raw_beta) if raw_beta is not None else 1.0
            
            # Aggregate Weights
            weight = float(df.loc[df['Symbol'] == symbol, 'weight'].values[0])
            
            # Update Sector
            current_sect_val = sector_exposure.get(sector, 0.0)
            sector_exposure[sector] = float(current_sect_val + weight)
            
            # Weighted Beta
            portfolio_beta += (beta * weight)
        except:
            continue
            
    # Force final beta to native float
    portfolio_beta = float(portfolio_beta)

    # 5. Drift Analysis
    target_weight = 1.0 / len(df)
    df['drift'] = df['weight'] - target_weight
    
    # Filter for alerts (Convert to list of strings, which is safe)
    drift_alert = df[df['drift'].abs() > 0.10]['Symbol'].tolist()

    # 6. Safe Serialization for Summary
    # df.to_dict('records') usually handles conversion, but we can be explicit if needed.
    # We round inside the dict comprehension to ensure native floats.
    
    # --- FINAL RETURN DICTIONARY (ALL NATIVE TYPES) ---
    return {
        "status": "ACTIVE",
        "total_equity": total_equity,
        "hhi_score": round(hhi, 2), # round() on native float is safe
        "concentration_risk": concentration_status,
        "portfolio_beta": round(portfolio_beta, 2),
        
        # Dictionary comprehension ensuring values are floats
        "sector_allocation": {k: round(float(v)*100, 1) for k, v in sector_exposure.items()},
        
        "drift_alerts": drift_alert,
        "holdings_summary": df[['Symbol', 'weight', 'drift']].astype(float, errors='ignore').to_dict(orient='records')
    }
