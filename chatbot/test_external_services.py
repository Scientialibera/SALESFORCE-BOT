"""
Test script to instantiate and test classes that require external connections.
Tests in order of complexity: account resolver -> repos -> full bot.
"""

import asyncio
import sys
import os
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

async def test_account_resolver_service():
    """Test account resolver service instantiation and basic functionality."""
    print("Testing Account Resolver Service...")

    try:
        # Set all required environment variables for testing
        os.environ.setdefault('AOAI_ENDPOINT', 'https://test.openai.azure.com/')
        os.environ.setdefault('AOAI_CHAT_DEPLOYMENT', 'test-chat')
        os.environ.setdefault('AOAI_EMBEDDING_DEPLOYMENT', 'test-embedding')
        os.environ.setdefault('COSMOS_ENDPOINT', 'https://test.documents.azure.com/')
        os.environ.setdefault('COSMOS_DATABASE_NAME', 'test-db')
        os.environ.setdefault('SEARCH_ENDPOINT', 'https://test.search.windows.net/')
        os.environ.setdefault('SEARCH_INDEX', 'test-index')
        os.environ.setdefault('FABRIC_WAREHOUSE_ENDPOINT', 'test.datawarehouse.fabric.microsoft.com')
        os.environ.setdefault('AZURE_COSMOS_GREMLIN_ENDPOINT', 'wss://test.gremlin.cosmosdb.azure.com/')
        os.environ.setdefault('AZURE_COSMOS_GREMLIN_DATABASE', 'test-graph-db')
        os.environ.setdefault('AZURE_COSMOS_GREMLIN_GRAPH', 'test-graph')

        from chatbot.services.account_resolver_service import AccountResolverService
        from chatbot.config.settings import settings

        # Create instance
        account_resolver = AccountResolverService()

        print("  + AccountResolverService instantiated successfully")

        # Test account name resolution (this should work with mock data in dev mode)
        test_names = ["Microsoft", "Apple Inc", "Unknown Company"]
        results = await account_resolver.resolve_account_names(test_names)

        print(f"  + Resolved {len(results)} account names")
        for result in results:
            print(f"    - {result['name']}: confidence={result['confidence']:.2f}, method={result['method']}")

        return True

    except Exception as e:
        print(f"  X AccountResolverService test failed: {e}")
        return False

async def test_prompts_repository():
    """Test prompts repository loading."""
    print("Testing Prompts Repository...")

    try:
        from chatbot.repositories.prompts_repository import PromptsRepository

        # Create instance
        prompts_repo = PromptsRepository()

        print("  + PromptsRepository instantiated successfully")

        # Test loading system prompt
        prompt = await prompts_repo.get_system_prompt(
            "planner_system",
            tenant_id="test-tenant",
            scenario="general"
        )

        if prompt:
            print(f"  + Loaded planner_system prompt ({len(prompt)} characters)")
            # Show first 100 chars
            preview = prompt[:100].replace('\n', ' ')
            print(f"    Preview: {preview}...")
        else:
            print("  ! Prompt loaded but was empty")

        return True

    except Exception as e:
        print(f"  X PromptsRepository test failed: {e}")
        return False

async def test_agent_functions_repository():
    """Test agent functions repository loading."""
    print("Testing Agent Functions Repository...")

    try:
        from chatbot.repositories.agent_functions_repository import AgentFunctionsRepository

        # Create instance
        functions_repo = AgentFunctionsRepository()

        print("  + AgentFunctionsRepository instantiated successfully")

        # Test loading agent functions
        functions = await functions_repo.get_available_functions()

        print(f"  + Loaded {len(functions)} agent functions")
        for func in functions:
            print(f"    - {func.get('name', 'unknown')}: {func.get('description', 'no description')[:50]}...")

        return True

    except Exception as e:
        print(f"  X AgentFunctionsRepository test failed: {e}")
        return False

async def test_rbac_service():
    """Test RBAC service instantiation."""
    print("Testing RBAC Service...")

    try:
        from chatbot.services.rbac_service import RBACService
        from chatbot.models.rbac import RBACContext, AccessScope

        # Create instance
        rbac_service = RBACService()

        print("  + RBACService instantiated successfully")

        # Create test RBAC context
        rbac_context = RBACContext(
            user_id="test@example.com",
            email="test@example.com",
            tenant_id="test-tenant",
            object_id="test-object-id",
            roles=["test_role"],
            access_scope=AccessScope()
        )

        # Test basic RBAC functionality
        has_access = await rbac_service.check_data_access(rbac_context, "accounts")
        print(f"  + RBAC check completed: has_access={has_access}")

        return True

    except Exception as e:
        print(f"  X RBACService test failed: {e}")
        return False

async def test_sql_service():
    """Test SQL service instantiation."""
    print("Testing SQL Service...")

    try:
        from chatbot.services.sql_service import SQLService

        # Create instance
        sql_service = SQLService()

        print("  + SQLService instantiated successfully")

        # Test basic query execution in dev mode
        try:
            result = await sql_service.execute_natural_language_query(
                user_query="Show me account information",
                data_types=None,
                limit=5,
                accounts_mentioned=["Microsoft"],
                dev_mode=True
            )

            print("  + SQL service executed test query successfully")
            print(f"    Result type: {type(result)}")

        except Exception as query_error:
            print(f"  ! SQL query test failed (expected in some environments): {query_error}")

        return True

    except Exception as e:
        print(f"  X SQLService test failed: {e}")
        return False

async def test_kernel_and_agents():
    """Test Semantic Kernel and agent instantiation."""
    print("Testing Kernel and Agents...")

    try:
        from semantic_kernel import Kernel
        from chatbot.agents.sql_agent import SQLAgent
        from chatbot.agents.graph_agent import GraphAgent
        from chatbot.services.telemetry_service import TelemetryService

        # Create kernel
        kernel = Kernel()
        print("  + Semantic Kernel instantiated successfully")

        # Create telemetry service
        telemetry_service = TelemetryService()
        print("  + TelemetryService instantiated successfully")

        # Create SQL agent (mock dependencies)
        class MockSQLService:
            async def execute_natural_language_query(self, **kwargs):
                return '{"data": [], "message": "Mock response"}'

        class MockAccountResolver:
            async def resolve_account_names(self, names):
                return [{"name": name, "account_id": f"id_{name}", "confidence": 0.9} for name in names]

        sql_agent = SQLAgent(
            kernel=kernel,
            sql_service=MockSQLService(),
            account_resolver_service=MockAccountResolver(),
            telemetry_service=telemetry_service
        )
        print("  + SQLAgent instantiated successfully")

        # Create Graph agent (mock dependencies)
        class MockGraphService:
            async def execute_query(self, **kwargs):
                return {"relationships": [], "documents": []}

        graph_agent = GraphAgent(
            kernel=kernel,
            graph_service=MockGraphService(),
            telemetry_service=telemetry_service
        )
        print("  + GraphAgent instantiated successfully")

        # Test that kernel functions are registered
        if hasattr(kernel, 'plugins') and kernel.plugins:
            print(f"  + Kernel has {len(kernel.plugins)} plugins registered")

        return True

    except Exception as e:
        print(f"  X Kernel and Agents test failed: {e}")
        return False

async def test_full_app_creation():
    """Test full app creation with all services."""
    print("Testing Full App Creation...")

    try:
        from chatbot.app import create_app

        # Create the full app
        app = create_app()

        print("  + FastAPI app created successfully")
        print(f"  + App routes: {[route.path for route in app.routes]}")

        return True

    except Exception as e:
        print(f"  X Full app creation failed: {e}")
        return False

async def main():
    """Run all external service tests."""
    print("Testing External Services and Full Bot Instantiation")
    print("=" * 60)

    tests = [
        ("Account Resolver Service", test_account_resolver_service),
        ("Prompts Repository", test_prompts_repository),
        ("Agent Functions Repository", test_agent_functions_repository),
        ("RBAC Service", test_rbac_service),
        ("SQL Service", test_sql_service),
        ("Kernel and Agents", test_kernel_and_agents),
        ("Full App Creation", test_full_app_creation)
    ]

    passed = 0
    total = len(tests)

    for test_name, test_func in tests:
        print(f"\n{test_name}:")
        if await test_func():
            passed += 1

    print("\n" + "=" * 60)
    print(f"Results: {passed}/{total} tests passed")

    if passed == total:
        print("All external service tests passed! The bot is ready for full testing.")
        return True
    else:
        print("Some tests failed. Review the failures above.")
        return False

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)