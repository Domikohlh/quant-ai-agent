import asyncio
from mcp import ClientSession
from mcp.client.sse import sse_client

# ⚠️ REPLACE THIS WITH YOUR ACTUAL CLOUD RUN URL
CLOUD_RUN_URL = "https://quant-mcp-server-590529272898.us-central1.run.app/sse"

async def test_tool_output():
    print(f"Connecting to {CLOUD_RUN_URL}...")
    
    try:
        async with sse_client(CLOUD_RUN_URL) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                print("✅ Connected successfully. Triggering tool...\n")
                
                # We call the tool directly. NO LLM INVOLVED.
                result = await session.call_tool(
                    "update_stock_data", 
                    arguments={"ticker": "AAPL", "period": "1mo"}
                )
                
                output_text = result.content[0].text
                
                print(f"--- TOOL EXECUTION COMPLETE ---")
                print(f"Total Output Length: {len(output_text)} characters")
                print(f"Raw Payload the LLM will see:\n")
                print(output_text)
                
                if len(output_text) > 1000:
                    print("\n❌ DANGER: Output is still too large! DO NOT connect the LLM.")
                else:
                    print("\n✅ SAFE: Output is short and truncated. Ready for the LLM.")

    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_tool_output())