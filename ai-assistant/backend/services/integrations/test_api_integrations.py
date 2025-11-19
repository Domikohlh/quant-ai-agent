#!/usr/bin/env python3
"""
Test script for all API integrations.
Run this to verify Alpaca, Google News, and IB connections.
"""
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from backend.services.integrations.alpaca_client import AlpacaClient
from backend.services.integrations.google_news_client import google_news_client
from backend.services.integrations.ib_client import InteractiveBrokersClient
from backend.utils.logging.logger import get_logger

logger = get_logger(__name__)


async def test_alpaca():
    """Test Alpaca API integration."""
    print("\n" + "=" * 60)
    print("Testing Alpaca API")
    print("=" * 60)
    
    try:
        # Test 1: Get account info
        print("\n1. Testing account info...")
        account = await alpaca_client.get_account()
        print(f"   ✅ Account ID: {account['account_number']}")
        print(f"   ✅ Portfolio Value: ${account['portfolio_value']:,.2f}")
        print(f"   ✅ Buying Power: ${account['buying_power']:,.2f}")
        print(f"   ✅ Cash: ${account['cash']:,.2f}")
        
        # Test 2: Get market status
        print("\n2. Testing market status...")
        market_hours = await alpaca_client.get_market_hours()
        print(f"   ✅ Market Open: {market_hours['is_open']}")
        print(f"   ✅ Next Open: {market_hours['next_open']}")
        
        # Test 3: Get latest quote
        print("\n3. Testing latest quote (AAPL)...")
        quote = await alpaca_client.get_latest_quote("AAPL")
        print(f"   ✅ Symbol: {quote['symbol']}")
        print(f"   ✅ Bid: ${quote['bid_price']:.2f}")
        print(f"   ✅ Ask: ${quote['ask_price']:.2f}")
        
        # Test 4: Get historical data
        print("\n4. Testing historical bars (AAPL, last 5 days)...")
        bars = await alpaca_client.get_historical_bars("AAPL", limit=5)
        print(f"   ✅ Retrieved {len(bars)} bars")
        if bars:
            latest = bars[-1]
            print(f"   ✅ Latest close: ${latest['close']:.2f}")
        
        # Test 5: Get positions
        print("\n5. Testing positions...")
        positions = await alpaca_client.get_positions()
        print(f"   ✅ Open positions: {len(positions)}")
        for pos in positions[:3]:  # Show first 3
            print(f"      - {pos['symbol']}: {pos['qty']} shares @ ${pos['current_price']:.2f}")
        
        # Test 6: Get orders
        print("\n6. Testing order history...")
        orders = await alpaca_client.get_orders(status="all", limit=5)
        print(f"   ✅ Retrieved {len(orders)} recent orders")
        
        print("\n✅ Alpaca API tests passed!")
        return True
    
    except Exception as e:
        print(f"\n❌ Alpaca API test failed: {e}")
        return False


async def test_google_news():
    """Test Google News API integration."""
    print("\n" + "=" * 60)
    print("Testing Google News API")
    print("=" * 60)
    
    try:
        # Test 1: General news search
        print("\n1. Testing general news search...")
        articles = await google_news_client.search_news(
            query="stock market",
            num_results=5,
            date_restrict="d1"
        )
        print(f"   ✅ Found {len(articles)} articles")
        if articles:
            print(f"   ✅ Latest: {articles[0]['title'][:60]}...")
        
        # Test 2: Stock-specific news
        print("\n2. Testing stock-specific news (AAPL)...")
        stock_news = await google_news_client.search_stock_news(
            symbol="AAPL",
            company_name="Apple",
            num_results=5,
            days_back=7
        )
        print(f"   ✅ Found {len(stock_news)} relevant articles")
        for article in stock_news[:2]:
            print(f"      - {article['title'][:60]}...")
        
        # Test 3: Market news
        print("\n3. Testing market news...")
        market_news = await google_news_client.search_market_news(num_results=5)
        print(f"   ✅ Found {len(market_news)} market articles")
        
        # Test 4: Critical news
        print("\n4. Testing critical news detection...")
        critical_news = await google_news_client.search_critical_news(
            symbols=["AAPL", "MSFT"],
            keywords=["bankruptcy", "lawsuit"]
        )
        print(f"   ✅ Found {len(critical_news)} critical articles")
        
        print("\n✅ Google News API tests passed!")
        return True
    
    except Exception as e:
        print(f"\n❌ Google News API test failed: {e}")
        return False


async def test_interactive_brokers():
    """Test Interactive Brokers API integration."""
    print("\n" + "=" * 60)
    print("Testing Interactive Brokers API")
    print("=" * 60)
    
    try:
        # Test 1: Connection
        print("\n1. Testing IB connection...")
        connected = await ib_client.connect()
        if connected:
            print("   ✅ Connected to IB")
        else:
            print("   ⚠️  Could not connect to IB")
            print("   Note: TWS or IB Gateway must be running")
            return False
        
        # Test 2: Account summary
        print("\n2. Testing account summary...")
        account = await ib_client.get_account_summary()
        print(f"   ✅ Account: {account['account_id']}")
        print(f"   ✅ Net Liquidation: ${account['net_liquidation']:,.2f}")
        print(f"   ✅ Buying Power: ${account['buying_power']:,.2f}")
        
        # Test 3: Portfolio positions
        print("\n3. Testing portfolio positions...")
        positions = await ib_client.get_portfolio_positions()
        print(f"   ✅ Portfolio positions: {len(positions)}")
        for pos in positions[:3]:
            print(f"      - {pos['symbol']}: {pos['position']} @ ${pos['market_price']:.2f}")
        
        # Test 4: Open orders
        print("\n4. Testing open orders...")
        orders = await ib_client.get_open_orders()
        print(f"   ✅ Open orders: {len(orders)}")
        
        # Test 5: Real-time price
        print("\n5. Testing real-time price (AAPL)...")
        price = await ib_client.get_real_time_price("AAPL")
        if price:
            print(f"   ✅ AAPL price: ${price:.2f}")
        
        # Disconnect
        await ib_client.disconnect()
        print("   ✅ Disconnected from IB")
        
        print("\n✅ Interactive Brokers API tests passed!")
        return True
    
    except ConnectionError:
        print("\n⚠️  Interactive Brokers test skipped")
        print("   TWS or IB Gateway must be running for this test")
        print("   This is expected if you haven't set up IB yet")
        return None  # Skip, not a failure
    
    except Exception as e:
        print(f"\n❌ Interactive Brokers API test failed: {e}")
        return False


async def run_all_tests():
    """Run all API integration tests."""
    print("\n" + "=" * 60)
    print("API INTEGRATIONS TEST SUITE")
    print("=" * 60)
    print("\nTesting all API integrations...")
    print("This will verify Alpaca, Google News, and Interactive Brokers")
    print()
    
    results = {}
    
    # Test Alpaca
    results["alpaca"] = await test_alpaca()
    
    # Test Google News
    results["google_news"] = await test_google_news()
    
    # Test Interactive Brokers
    results["interactive_brokers"] = await test_interactive_brokers()
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    for service, result in results.items():
        if result is True:
            status = "✅ PASSED"
        elif result is False:
            status = "❌ FAILED"
        else:
            status = "⚠️  SKIPPED"
        
        print(f"  {service.replace('_', ' ').title():<25} {status}")
    
    print()
    
    # Overall result
    passed = sum(1 for r in results.values() if r is True)
    failed = sum(1 for r in results.values() if r is False)
    skipped = sum(1 for r in results.values() if r is None)
    
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Skipped: {skipped}")
    print()
    
    if failed > 0:
        print("❌ Some tests failed. Please check the errors above.")
        print("\nCommon fixes:")
        print("  - Verify API keys in .env file")
        print("  - Check internet connection")
        print("  - For IB: Ensure TWS/Gateway is running")
        return False
    elif skipped > 0:
        print("⚠️  Some tests were skipped (this is OK for IB if not set up)")
        return True
    else:
        print("✅ All tests passed!")
        return True


if __name__ == "__main__":
    # Run tests
    success = asyncio.run(run_all_tests())
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)
