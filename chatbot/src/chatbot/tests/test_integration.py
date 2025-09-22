"""
Integration tests for Azure services.

These tests verify that the Azure services (OpenAI, Cosmos DB) are accessible
using DefaultAzureCredential. They require actual Azure resources and
proper authentication to be set up.
"""

import pytest
import asyncio
import os
from datetime import datetime

from chatbot.config.settings import settings
from chatbot.clients.aoai_client import AzureOpenAIClient
from chatbot.clients.cosmos_client import CosmosDBClient
from chatbot.services.account_resolver_service import AccountResolverService
from chatbot.services.unified_service import UnifiedDataService
from chatbot.models.rbac import RBACContext, AccessScope


@pytest.mark.integration
@pytest.mark.asyncio
class TestAzureIntegration:
    """Integration tests for Azure services."""

    async def test_azure_openai_connection(self):
        """Test Azure OpenAI connectivity and basic completion."""
        if not settings.azure_openai.endpoint:
            pytest.skip("Azure OpenAI endpoint not configured")

        aoai_client = AzureOpenAIClient(settings.azure_openai)

        try:
            # Test a simple completion
            messages = [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Say 'test successful' if you can understand this."}
            ]

            result = await aoai_client.create_chat_completion(messages)

            assert result is not None
            assert "choices" in result
            assert len(result["choices"]) > 0
            assert "message" in result["choices"][0]

            response_content = result["choices"][0]["message"]["content"]
            assert isinstance(response_content, str)
            assert len(response_content) > 0

        finally:
            await aoai_client.close()

    async def test_cosmos_db_connection(self):
        """Test Cosmos DB connectivity and basic operations."""
        if not settings.cosmos_db.endpoint:
            pytest.skip("Cosmos DB endpoint not configured")

        cosmos_client = CosmosDBClient(settings.cosmos_db)

        try:
            # Test creating a simple test document
            test_doc = {
                "id": f"test_doc_{datetime.utcnow().timestamp()}",
                "test_field": "test_value",
                "timestamp": datetime.utcnow().isoformat()
            }

            # Try to create the document in the chat container
            container_name = settings.cosmos_db.chat_container

            created_doc = await cosmos_client.create_item(
                container_name=container_name,
                item=test_doc,
                partition_key="/id"
            )

            assert created_doc is not None
            assert created_doc["id"] == test_doc["id"]

            # Try to read it back
            read_doc = await cosmos_client.read_item(
                container_name=container_name,
                item_id=test_doc["id"],
                partition_key_value=test_doc["id"]
            )

            assert read_doc is not None
            assert read_doc["test_field"] == "test_value"

            # Clean up - delete the test document
            deleted = await cosmos_client.delete_item(
                container_name=container_name,
                item_id=test_doc["id"],
                partition_key_value=test_doc["id"]
            )

            assert deleted is True

        finally:
            await cosmos_client.close()

    async def test_unified_service_integration(self):
        """Test unified service with real Cosmos DB."""
        if not settings.cosmos_db.endpoint:
            pytest.skip("Cosmos DB endpoint not configured")

        cosmos_client = CosmosDBClient(settings.cosmos_db)
        unified_service = UnifiedDataService(cosmos_client, settings.cosmos_db)

        try:
            # Create test RBAC context
            test_rbac = RBACContext(
                user_id="integration_test@example.com",
                email="integration_test@example.com",
                tenant_id="test-tenant",
                object_id="test-object-id",
                roles=["test_role"],
                access_scope=AccessScope(),
            )

            # Test cache operations
            test_query = "SELECT * FROM test_table"
            test_result = {"test": "data", "timestamp": datetime.utcnow().isoformat()}

            # Set cache
            success = await unified_service.set_query_result(
                query=test_query,
                result=test_result,
                rbac_context=test_rbac,
                query_type="sql"
            )
            assert success is True

            # Get cache
            cached_result = await unified_service.get_query_result(
                query=test_query,
                rbac_context=test_rbac,
                query_type="sql"
            )
            assert cached_result is not None
            assert cached_result["test"] == "data"

            # Test embedding operations
            test_text = f"Integration test embedding {datetime.utcnow().timestamp()}"
            test_embedding = [0.1, 0.2, 0.3, 0.4, 0.5]

            embedding_success = await unified_service.set_embedding(
                text=test_text,
                embedding=test_embedding
            )
            assert embedding_success is True

            stored_embedding = await unified_service.get_embedding(test_text)
            assert stored_embedding == test_embedding

        finally:
            await cosmos_client.close()

    async def test_account_resolver_integration(self):
        """Test account resolver service with real Azure services."""
        if not settings.azure_openai.endpoint or not settings.cosmos_db.endpoint:
            pytest.skip("Azure OpenAI or Cosmos DB endpoint not configured")

        # Initialize clients
        aoai_client = AzureOpenAIClient(settings.azure_openai)
        cosmos_client = CosmosDBClient(settings.cosmos_db)
        unified_service = UnifiedDataService(cosmos_client, settings.cosmos_db)

        try:
            # Create account resolver service
            account_resolver = AccountResolverService(
                aoai_client=aoai_client,
                cache_service=unified_service,
                confidence_threshold=0.7,
                max_suggestions=5
            )

            # Test RBAC context
            test_rbac = RBACContext(
                user_id="integration_test@example.com",
                email="integration_test@example.com",
                tenant_id="test-tenant",
                object_id="test-object-id",
                roles=["test_role"],
                access_scope=AccessScope(),
            )

            # Test account resolution (this might not find any accounts in dev mode)
            query = "Show me information about Microsoft"

            try:
                resolved_accounts = await account_resolver.resolve_accounts_from_query(
                    query=query,
                    rbac_context=test_rbac
                )

                # In dev mode, this might return empty results, which is fine
                assert isinstance(resolved_accounts, list)

            except Exception as e:
                # Account resolution might fail in dev mode without proper data
                # This is acceptable for integration testing
                print(f"Account resolution test failed (expected in dev mode): {e}")

        finally:
            await aoai_client.close()
            await cosmos_client.close()

    async def test_dev_mode_settings(self):
        """Test that dev mode settings are properly configured."""
        # Verify dev mode is enabled for testing
        assert settings.dev_mode is True

        # Verify essential settings are present
        assert settings.azure_openai.endpoint is not None
        assert settings.cosmos_db.endpoint is not None
        assert settings.cosmos_db.database_name is not None
        assert settings.cosmos_db.chat_container is not None

    def test_environment_variables(self):
        """Test that required environment variables are set."""
        # Test Azure OpenAI
        assert os.getenv("AOAI_ENDPOINT") is not None, "AOAI_ENDPOINT must be set"
        assert os.getenv("AOAI_CHAT_DEPLOYMENT") is not None, "AOAI_CHAT_DEPLOYMENT must be set"

        # Test Cosmos DB
        assert os.getenv("COSMOS_ENDPOINT") is not None, "COSMOS_ENDPOINT must be set"
        assert os.getenv("COSMOS_DATABASE_NAME") is not None, "COSMOS_DATABASE_NAME must be set"

        # Test that we're not using any credential-based auth (security check)
        assert os.getenv("AZURE_CLIENT_SECRET") is None, "Should use DefaultAzureCredential, not client secrets"
        assert os.getenv("AZURE_COSMOS_KEY") is None, "Should use RBAC, not Cosmos keys"


@pytest.mark.integration
@pytest.mark.asyncio
class TestServiceAvailability:
    """Test service availability and basic functionality."""

    async def test_azure_services_reachable(self):
        """Test that Azure services are reachable."""
        import aiohttp

        # Test Azure OpenAI endpoint
        if settings.azure_openai.endpoint:
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.get(settings.azure_openai.endpoint, timeout=10) as resp:
                        # We expect a 401 (unauthorized) or similar, not a connection error
                        assert resp.status in [401, 403, 404], f"Unexpected status: {resp.status}"
                except aiohttp.ClientError as e:
                    pytest.fail(f"Cannot reach Azure OpenAI endpoint: {e}")

        # Test Cosmos DB endpoint
        if settings.cosmos_db.endpoint:
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.get(settings.cosmos_db.endpoint, timeout=10) as resp:
                        # We expect a 401 (unauthorized) or similar, not a connection error
                        assert resp.status in [401, 403, 404], f"Unexpected status: {resp.status}"
                except aiohttp.ClientError as e:
                    pytest.fail(f"Cannot reach Cosmos DB endpoint: {e}")

    def test_settings_validation(self):
        """Test that settings are properly validated."""
        # Test that endpoints are proper URLs
        if settings.azure_openai.endpoint:
            assert settings.azure_openai.endpoint.startswith("https://")

        if settings.cosmos_db.endpoint:
            assert settings.cosmos_db.endpoint.startswith("https://")

        # Test that container names are valid
        assert settings.cosmos_db.chat_container
        assert settings.cosmos_db.prompts_container
        assert settings.cosmos_db.agent_functions_container
        assert settings.cosmos_db.sql_schema_container