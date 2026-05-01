# mcp_server/server.py
import os
from mcp.server.fastmcp import FastMCP
from ml_tools import train_bqml_model, predict_bqml
from backtest_tools import run_vectorized_backtest

# Initialize the unified server
mcp = FastMCP("Quant_Unified_MCP")

# Register the tools from your imported modules
mcp.tool()(train_bqml_model)
mcp.tool()(predict_bqml)
mcp.tool()(run_vectorized_backtest)

if __name__ == "__main__":
    # Cloud Run injects the PORT environment variable (default 8080)
    port = int(os.environ.get("PORT", 8080))
    
    # You MUST use SSE transport for Cloud Run, not stdio
    print(f"Starting unified MCP Server on port {port} via SSE...")
    mcp.run(transport="sse", host="0.0.0.0", port=port)