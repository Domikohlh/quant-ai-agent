import pandas as pd

def fast_traditional_backtest(df: pd.DataFrame, top_k: int = 2, t_cost: float = 0.00025):
    """Evaluates the entire basket daily, longs top K, shorts bottom K."""
    dates = df['timestamp'].unique()
    equity = 1000000.0
    total_costs = 0.0
    peak_equity = equity
    max_drawdown = 0.0
    total_trades = winning_trades = 0
    
    for date in dates:
        daily_data = df[df['timestamp'] == date]
        if len(daily_data) < top_k * 2: continue
        
        # Rank by model probability
        ranked = daily_data.sort_values('probability', ascending=False)
        longs = ranked.head(top_k)
        shorts = ranked.tail(top_k)
        
        long_ret = longs['actual_return_1d'].mean() - t_cost
        short_ret = (shorts['actual_return_1d'].mean() * -1) - t_cost
        port_ret = (long_ret + short_ret) / 2
        
        profit = equity * port_ret
        equity += profit
        total_costs += (equity * t_cost * 2) 
        total_trades += (top_k * 2)
        if port_ret > 0: winning_trades += 1
        
        if equity > peak_equity: peak_equity = equity
        dd = (peak_equity - equity) / peak_equity
        if dd > max_drawdown: max_drawdown = dd
        
    return equity, max_drawdown, total_trades, winning_trades, total_costs