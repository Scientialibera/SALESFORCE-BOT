"""
Test script to verify the cleaned up agentic implementation.
Tests imports and basic functionality without external dependencies.
"""

import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def test_imports():
    """Test that all modules can be imported without old planner dependencies."""
    print("Testing imports...")

    try:
        # Test planner service import
        from chatbot.services.planner_service import PlannerService
        print("✓ PlannerService import successful")

        # Test agent imports
        from chatbot.agents.sql_agent import SQLAgent
        from chatbot.agents.graph_agent import GraphAgent
        print("✓ Agent imports successful")

        # Test chat route import
        from chatbot.routes.chat import router
        print("✓ Chat route import successful")

        return True

    except Exception as e:
        print(f"✗ Import failed: {e}")
        return False

def test_planner_service_methods():
    """Test that planner service has the right methods."""
    print("Testing planner service methods...")

    try:
        from chatbot.services.planner_service import PlannerService

        # Check that the old methods are gone
        assert not hasattr(PlannerService, '_create_function_call_plan'), "Old _create_function_call_plan method still exists"
        assert not hasattr(PlannerService, '_create_basic_plan'), "Old _create_basic_plan method still exists"

        # Check that the new method exists
        assert hasattr(PlannerService, 'plan_with_auto_function_calling'), "Missing plan_with_auto_function_calling method"

        print("✓ PlannerService has correct methods")
        return True

    except Exception as e:
        print(f"✗ PlannerService method test failed: {e}")
        return False

def test_agent_kernel_functions():
    """Test that agents have kernel function decorators."""
    print("Testing agent kernel function decorators...")

    try:
        from chatbot.agents.sql_agent import SQLAgent
        from chatbot.agents.graph_agent import GraphAgent

        # Check that agents have kernel_function decorators
        sql_func = getattr(SQLAgent, 'sql_agent')
        assert hasattr(sql_func, '__kernel_function__'), "SQL agent missing @kernel_function decorator"

        graph_func = getattr(GraphAgent, 'graph_agent')
        assert hasattr(graph_func, '__kernel_function__'), "Graph agent missing @kernel_function decorator"

        print("✓ Agents have kernel function decorators")
        return True

    except Exception as e:
        print(f"✗ Agent kernel function test failed: {e}")
        return False

def test_no_old_planner_imports():
    """Test that old planner imports are not present."""
    print("Testing for removal of old planner imports...")

    try:
        # Read the planner service file
        planner_file = os.path.join(os.path.dirname(__file__), 'src', 'chatbot', 'services', 'planner_service.py')
        with open(planner_file, 'r') as f:
            content = f.read()

        # Check that old imports are not present
        assert 'SequentialPlanner' not in content, "SequentialPlanner import still present"
        assert 'StepwisePlanner' not in content, "StepwisePlanner import still present"
        assert 'from semantic_kernel.planners import' not in content, "Old planner imports still present"

        print("✓ Old planner imports have been removed")
        return True

    except Exception as e:
        print(f"✗ Old planner import check failed: {e}")
        return False

def main():
    """Run all tests."""
    print("Testing Cleaned Up Agentic Implementation")
    print("=" * 50)

    tests = [
        test_imports,
        test_planner_service_methods,
        test_agent_kernel_functions,
        test_no_old_planner_imports
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
        print("All cleanup tests passed! The agentic implementation is clean and ready.")
        return True
    else:
        print("Some cleanup tests failed. Please review the implementation.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)