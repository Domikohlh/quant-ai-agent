# tests/test_workflow.py
import unittest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace
from langchain_core.messages import AIMessage

# Import nodes
from agents.risk_manager import risk_manager_node
from agents.executor import executor_node
from agents.supervisor import supervisor_node

class TestQuantAgent(unittest.TestCase):

    def setUp(self):
        # Mock Google Auth to prevent credential errors
        self.auth_patcher = patch("google.auth.default")
        self.mock_auth = self.auth_patcher.start()
        self.mock_auth.return_value = (MagicMock(), "test-project")

    def tearDown(self):
        self.auth_patcher.stop()

    # =================================================================
    # TEST 1: RISK MANAGER
    # =================================================================
    @patch("agents.risk_manager.ChatGoogleGenerativeAI")
    @patch("agents.risk_manager.get_current_portfolio")
    def test_risk_manager_sizing(self, mock_portfolio, mock_llm_class):
        print("\n🧪 TESTING: Risk Manager Position Sizing...")

        # 1. Mock Portfolio Data
        mock_portfolio.return_value = {"total_equity": 10000, "cash": 10000, "holdings": {}}

        # 2. Mock the Decision Object
        mock_decision = SimpleNamespace()
        mock_decision.portfolio_status = "Safe"
        mock_decision.approved_orders = [
            SimpleNamespace(symbol="AAPL", qty=6, side="BUY", limit_price=0.0, dict=lambda: {"symbol": "AAPL", "qty": 6, "side": "BUY"})
        ]
        mock_decision.rejected_orders = []

        # 3. Mock the Chain Execution
        mock_chain = MagicMock()
        mock_chain.invoke.return_value = mock_decision
        
        # Connect chain to LLM
        mock_llm_instance = mock_llm_class.return_value
        mock_llm_instance.with_structured_output.return_value = mock_chain

        # 4. Run Logic
        state = {
            "trade_proposal": [{"symbol": "AAPL", "action": "BUY", "quantity_weight": 0.1}],
            "market_data": {"stocks": {"AAPL": [{"close": 150}]}},
            "messages": []
        }

        result = risk_manager_node(state)
        
        # 5. Assertions
        approved = result["approved_orders"]
        self.assertEqual(len(approved), 1)
        self.assertEqual(approved[0]["qty"], 6)
        print("✅ Risk Manager correctly approved 6 AAPL shares.")

    # =================================================================
    # TEST 2: SUPERVISOR (Robust Fix)
    # =================================================================
    @patch("agents.supervisor.ChatPromptTemplate") # <--- NEW PATCH
    @patch("agents.supervisor.ChatGoogleGenerativeAI")
    def test_supervisor_routing(self, mock_llm_class, mock_prompt_class):
        print("\n🧪 TESTING: Supervisor Routing Logic...")

        # 1. Define the Expected Output
        decision_output = SimpleNamespace(next="data_engineer", reasoning="Need data")

        # 2. Create a Mock Chain
        # This represents the final object (prompt | llm)
        mock_chain = MagicMock()
        mock_chain.invoke.return_value = decision_output

        # 3. Configure the Pipe Logic
        # We tell the Prompt Mock: "If anything is piped into you (__or__), return our mock_chain"
        mock_prompt_instance = mock_prompt_class.from_messages.return_value
        mock_prompt_instance.__or__.return_value = mock_chain

        # 4. Run Logic
        state = {"messages": [], "market_data": None}
        result = supervisor_node(state)

        # 5. Assertions
        self.assertEqual(result["next_step"], "data_engineer")
        print("✅ Supervisor correctly routed to Data Engineer.")

    # =================================================================
    # TEST 3: EXECUTOR
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
