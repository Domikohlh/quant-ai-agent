from numba import njit

@njit(cache=True) # Added cache=True to prevent recompiling on every Cloud Run cold start
def fast_crypto_backtest(prices, predictions, probabilities, conf_threshold, sl_pct, tp_pct, max_hold, t_cost):
    n = len(prices)
    position = 0 
    entry_price = 0.0
    entry_idx = 0
    size_factor = 0.0
    
    total_trades = winning_trades = longs = shorts = l_wins = s_wins = 0
    time_exits = sl_exits = tp_exits = 0
    
    equity = 1000000.0
    total_costs = 0.0
    peak_equity = equity
    max_drawdown = 0.0
    
    for i in range(1, n):
        current_price = prices[i]
        
        # ACTIVE POSITION EXIT LOGIC
        if position != 0:
            hold_time = i - entry_idx
            un_ret = (current_price - entry_price) / entry_price if position == 1 else (entry_price - current_price) / entry_price
            
            exit_reason = 0 
            if un_ret <= -sl_pct: exit_reason = 2
            elif un_ret >= tp_pct: exit_reason = 3
            elif hold_time >= max_hold: exit_reason = 1
                
            if exit_reason != 0:
                trade_return = un_ret - t_cost
                profit = equity * size_factor * trade_return
                equity += profit
                total_costs += (equity * size_factor * t_cost)
                
                total_trades += 1
                if trade_return > 0: winning_trades += 1
                if exit_reason == 1: time_exits += 1
                elif exit_reason == 2: sl_exits += 1
                elif exit_reason == 3: tp_exits += 1
                
                if position == 1:
                    longs += 1
                    if trade_return > 0: l_wins += 1
                else:
                    shorts += 1
                    if trade_return > 0: s_wins += 1
                position = 0 
                
        # ENTRY LOGIC
        if position == 0:
            prob = probabilities[i]
            if prob >= conf_threshold:
                position = 1 if predictions[i] > 0 else -1
                entry_price = current_price
                entry_idx = i
                size_factor = min(1.0, 0.25 + ((prob - 0.5) * 1.5))
                fee = equity * size_factor * t_cost
                equity -= fee
                total_costs += fee

        if equity > peak_equity: peak_equity = equity
        dd = (peak_equity - equity) / peak_equity
        if dd > max_drawdown: max_drawdown = dd

    return equity, max_drawdown, total_trades, winning_trades, longs, shorts, l_wins, s_wins, time_exits, sl_exits, tp_exits, total_costs