# tests/test_workflow.py
import unittest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace # <--- Import this
from agents.risk_manager import risk_manager_node
from agents.executor import executor_node
from agents.supervisor import supervisor_node

class TestQuantAgent(unittest.TestCase):

    def setUp(self):
        self.auth_patcher = patch("google.auth.default")
        self.mock_auth = self.auth_patcher.start()
        self.mock_auth.return_value = (MagicMock(), "test-project")

    def tearDown(self):
        self.auth_patcher.stop()

    # =================================================================
    # TEST 1: RISK MANAGER (Updated Mocking Strategy)
    # =================================================================
    @patch("agents.risk_manager.ChatGoogleGenerativeAI")
    @patch("agents.risk_manager.get_current_portfolio")
    def test_risk_manager_sizing(self, mock_portfolio, mock_llm_class):
        print("\n🧪 TESTING: Risk Manager Position Sizing...")

        mock_portfolio.return_value = {"total_equity": 10000, "cash": 10000, "holdings": {}}

        # Use SimpleNamespace to act like a real object, not a Mock
        # This avoids the confusing Mock behavior
        mock_decision = SimpleNamespace()
        mock_decision.portfolio_status = "Safe"
        mock_decision.approved_orders = [
            SimpleNamespace(symbol="AAPL", qty=6, side="BUY", limit_price=0.0, dict=lambda: {"symbol": "AAPL", "qty": 6, "side": "BUY"})
        ]
        mock_decision.rejected_orders = []

        # Mock the chain
        mock_chain = MagicMock()
        mock_chain.invoke.return_value = mock_decision
        
        mock_llm_instance = mock_llm_class.return_value
        mock_llm_instance.with_structured_output.return_value = mock_chain

        state = {
            "trade_proposal": [{"symbol": "AAPL", "action": "BUY", "quantity_weight": 0.1}],
            "market_data": {"stocks": {"AAPL": [{"close": 150}]}},
            "messages": []
        }

        result = risk_manager_node(state)
        
        # Check for error first
        if "error" in result:
            self.fail(f"Risk Manager failed with: {result['error']}")

        approved = result["approved_orders"]
        self.assertEqual(len(approved), 1)
        self.assertEqual(approved[0]["qty"], 6)
        print("✅ Risk Manager correctly approved 6 AAPL shares.")

    # =================================================================
    # TEST 2: SUPERVISOR (Updated Mocking Strategy)
    # =================================================================
    @patch("agents.supervisor.ChatGoogleGenerativeAI")
    def test_supervisor_routing(self, mock_llm_class):
        print("\n🧪 TESTING: Supervisor Routing Logic...")

        # Use SimpleNamespace to avoid the '.next' method conflict
        mock_decision = SimpleNamespace()
        mock_decision.next = "data_engineer"
        mock_decision.reasoning = "Need data."

        mock_chain = MagicMock()
        mock_chain.invoke.return_value = mock_decision
        
        mock_llm_instance = mock_llm_class.return_value
        mock_llm_instance.with_structured_output.return_value = mock_chain

        state = {"messages": [], "market_data": None}
        result = supervisor_node(state)

        self.assertEqual(result["next_step"], "data_engineer")
        print("✅ Supervisor correctly routed to Data Engineer.")

    # =================================================================
    # TEST 3: EXECUTOR (Kept same, it was working)
    # =================================================================
    @patch("agents.executor.ChatGoogleGenerativeAI")
    @patch("agents.executor.execute_order")
    def test_executor_slicing(self, mock_execute_tool, mock_llm_class):
        print("\n🧪 TESTING: Executor TWAP Slicing...")
        
        state = {
            "approved_orders": [{"symbol": "TSLA", "side": "BUY", "qty": 2000}],
            "messages": []
        }

        executor_node(state)

        self.assertEqual(mock_execute_tool.call_count, 2)
        print("✅ Executor correctly sliced 2000 shares.")

if __name__ == "__main__":
    unittest.main()
