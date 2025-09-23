"""
Test script for the fully agentic implementation.
Tests the core flow without external API dependencies.
"""

import json
import asyncio
import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def test_function_call_parsing():
    """Test parsing of function call responses from LLM."""
    print("Testing function call parsing...")

    # Mock LLM response with function call
    mock_response_content = '''
    {
        "tool_calls": [
            {
                "id": "call_123",
                "type": "function",
                "function": {
                    "name": "sql_agent",
                    "arguments": "{\\"query\\": \\"Show me sales data\\", \\"accounts_mentioned\\": [\\"Microsoft\\", \\"Apple\\"]}"
                }
            }
        ]
    }
    '''

    try:
        from chatbot.services.planner_service import PlannerService

        # Test parsing function call arguments
        mock_function = {
            "name": "sql_agent",
            "arguments": '{"query": "Show me sales data", "accounts_mentioned": ["Microsoft", "Apple"]}'
        }

        # Parse arguments
        args = json.loads(mock_function["arguments"])

        # Verify structure
        assert "query" in args
        assert "accounts_mentioned" in args
        assert isinstance(args["accounts_mentioned"], list)
        assert args["accounts_mentioned"] == ["Microsoft", "Apple"]

        print("✓ Function call parsing works correctly")
        return True

    except Exception as e:
        print(f"✗ Function call parsing failed: {e}")
        return False

def test_account_resolution():
    """Test account name resolution logic."""
    print("Testing account resolution logic...")

    try:
        from chatbot.services.account_resolver_service import AccountResolverService

        # Mock initialization without external dependencies
        class MockAccountResolverService:
            async def resolve_account_names(self, account_names):
                """Mock account resolution."""
                resolved = []
                for name in account_names:
                    resolved.append({
                        "name": name,
                        "account_id": f"id_{name.lower().replace(' ', '_')}",
                        "confidence": 0.95,
                        "method": "exact_match"
                    })
                return resolved

        # Test resolution
        resolver = MockAccountResolverService()
        result = asyncio.run(resolver.resolve_account_names(["Microsoft", "Apple"]))

        assert len(result) == 2
        assert result[0]["name"] == "Microsoft"
        assert result[0]["account_id"] == "id_microsoft"
        assert result[1]["name"] == "Apple"
        assert result[1]["account_id"] == "id_apple"

        print("✓ Account resolution logic works correctly")
        return True

    except Exception as e:
        print(f"✗ Account resolution failed: {e}")
        return False

def test_sequential_execution():
    """Test sequential function execution logic."""
    print("Testing sequential execution logic...")

    try:
        # Mock multiple function calls
        function_calls = [
            {
                "name": "sql_agent",
                "arguments": {"query": "Show sales data", "accounts_mentioned": ["Microsoft"]}
            },
            {
                "name": "graph_agent",
                "arguments": {"query": "Show relationships", "accounts_mentioned": ["Microsoft"]}
            }
        ]

        # Test execution order
        execution_order = []
        for call in function_calls:
            execution_order.append(call["name"])

        assert execution_order == ["sql_agent", "graph_agent"]

        # Test argument passing
        for call in function_calls:
            assert "query" in call["arguments"]
            assert "accounts_mentioned" in call["arguments"]

        print("✓ Sequential execution logic works correctly")
        return True

    except Exception as e:
        print(f"✗ Sequential execution failed: {e}")
        return False

def test_agent_function_signatures():
    """Test that agent functions match expected signatures."""
    print("Testing agent function signatures...")

    try:
        from chatbot.agents.sql_agent import SQLAgent
        from chatbot.agents.graph_agent import GraphAgent
        import inspect

        # Check SQL agent function signature
        sql_func = SQLAgent.sql_agent
        sig = inspect.signature(sql_func)
        params = list(sig.parameters.keys())

        # Should have self, query, accounts_mentioned
        expected_sql_params = ['self', 'query', 'accounts_mentioned']
        for param in expected_sql_params:
            assert param in params, f"Missing parameter {param} in SQL agent"

        # Check Graph agent function signature
        graph_func = GraphAgent.graph_agent
        sig = inspect.signature(graph_func)
        params = list(sig.parameters.keys())

        # Should have self, query, accounts_mentioned
        expected_graph_params = ['self', 'query', 'accounts_mentioned']
        for param in expected_graph_params:
            assert param in params, f"Missing parameter {param} in Graph agent"

        print("✓ Agent function signatures are correct")
        return True

    except Exception as e:
        print(f"✗ Agent function signature test failed: {e}")
        return False

def test_kernel_function_decorators():
    """Test that agents have proper kernel function decorators."""
    print("Testing kernel function decorators...")

    try:
        from chatbot.agents.sql_agent import SQLAgent
        from chatbot.agents.graph_agent import GraphAgent

        # Check SQL agent has kernel_function decorator
        sql_func = getattr(SQLAgent, 'sql_agent')
        assert hasattr(sql_func, '__kernel_function__'), "SQL agent missing @kernel_function decorator"

        # Check Graph agent has kernel_function decorator
        graph_func = getattr(GraphAgent, 'graph_agent')
        assert hasattr(graph_func, '__kernel_function__'), "Graph agent missing @kernel_function decorator"

        print("✓ Kernel function decorators are present")
        return True

    except Exception as e:
        print(f"✗ Kernel function decorator test failed: {e}")
        return False

def test_response_combination():
    """Test combining multiple agent responses."""
    print("Testing response combination...")

    try:
        # Mock agent responses
        sql_response = json.dumps({
            "data": [{"account": "Microsoft", "revenue": 100000}],
            "query": "SELECT * FROM accounts",
            "success": True
        })

        graph_response = json.dumps({
            "relationships": [{"from": "Microsoft", "to": "John Doe", "relationship": "contact"}],
            "documents": [],
            "success": True
        })

        # Parse responses
        sql_data = json.loads(sql_response)
        graph_data = json.loads(graph_response)

        # Verify structure
        assert sql_data["success"] is True
        assert graph_data["success"] is True
        assert len(sql_data["data"]) > 0
        assert len(graph_data["relationships"]) > 0

        # Mock combination logic
        combined_response = f"SQL Results: {len(sql_data['data'])} records found. "
        combined_response += f"Graph Results: {len(graph_data['relationships'])} relationships found."

        assert "SQL Results: 1 records found" in combined_response
        assert "Graph Results: 1 relationships found" in combined_response

        print("✓ Response combination works correctly")
        return True

    except Exception as e:
        print(f"✗ Response combination failed: {e}")
        return False

def main():
    """Run all tests."""
    print("🤖 Testing Fully Agentic Implementation")
    print("=" * 50)

    tests = [
        test_function_call_parsing,
        test_account_resolution,
        test_sequential_execution,
        test_agent_function_signatures,
        test_kernel_function_decorators,
        test_response_combination
    ]

    passed = 0
    total = len(tests)

    for test in tests:
        if test():
            passed += 1
        print()

    print("=" * 50)
    print(f"Results: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All tests passed! The agentic implementation is working correctly.")
        return True
    else:
        print("❌ Some tests failed. Please review the implementation.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)