# server.py
from fastmcp import FastMCP
import yfinance as yf

# Initialize the Server
mcp = FastMCP("MyCustomFinance", log_level = "ERROR")

# TOOL 1: Get the Price
@mcp.tool()
def get_stock_price(ticker: str) -> str:
    """Get the current stock price and daily change percentage."""
    try:
        stock = yf.Ticker(ticker)
        # fast_info is faster than .info for prices
        price = stock.fast_info.last_price
        prev_close = stock.fast_info.previous_close
        change_pct = ((price - prev_close) / prev_close) * 100
        
        return f"{ticker.upper()}: ${price:.2f} ({change_pct:+.2f}%)"
    except Exception as e:
        return f"Error getting price for {ticker}: {e}"

# TOOL 2: Get Fundamental Data (For Analysis)
@mcp.tool()
def get_company_fundamentals(ticker: str) -> str:
    """Get the P/E ratio, Market Cap, and Sector for analysis."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        return (
            f"Fundamentals for {ticker.upper()}:\n"
            f"- Sector: {info.get('sector', 'N/A')}\n"
            f"- P/E Ratio: {info.get('trailingPE', 'N/A')}\n"
            f"- Market Cap: ${info.get('marketCap', 0):,}\n"
            f"- Summary: {info.get('longBusinessSummary', '')[:200]}..."
        )
    except Exception:
        return f"Could not fetch fundamentals for {ticker}"

# TOOL 3: Get News
@mcp.tool()
def get_latest_news(ticker: str) -> str:
    """Get the top 3 news headlines for a stock."""
    try:
        stock = yf.Ticker(ticker)
        news = stock.news[:3] # Limit to 3 to save space
        
        output = [f"News for {ticker.upper()}:"]
        for n in news:
            output.append(f"- {n['title']} ({n['publisher']})")
        return "\n".join(output)
    except Exception:
        return "No news found."

if __name__ == "__main__":
    mcp.run()
