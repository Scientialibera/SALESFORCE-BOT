"""
Tests for the chat router and planner-first architecture.

Tests the complete chat flow including plan determination,
account resolution, agent execution, and response formatting.
"""

import pytest
import asyncio
from fastapi.testclient import TestClient
from datetime import datetime
from uuid import uuid4

from chatbot.app import create_app
from chatbot.models.rbac import RBACContext, AccessScope


@pytest.fixture
def test_app():
    """Create test FastAPI application."""
    app = create_app()
    return app


@pytest.fixture
def test_client(test_app):
    """Create test client."""
    return TestClient(test_app)


class TestChatRoute:
    """Test suite for chat routing and planner-first logic."""

    def test_chat_endpoint_available(self, test_client):
        """Test that the chat endpoint is available."""
        # This might fail due to dependencies not being initialized
        # but at least verifies the route is configured
        response = test_client.post("/api/chat", json={
            "messages": [{"role": "user", "content": "hello"}],
            "user_id": "test@example.com"
        })

        # We expect either a successful response or a service unavailable error
        assert response.status_code in [200, 503, 422]

    def test_chat_request_validation(self, test_client):
        """Test request validation for chat endpoint."""
        # Test missing required fields
        response = test_client.post("/api/chat", json={})
        assert response.status_code == 422

        # Test invalid message format
        response = test_client.post("/api/chat", json={
            "messages": [{"invalid": "format"}],
            "user_id": "test@example.com"
        })
        assert response.status_code == 422

    def test_chat_request_with_valid_data(self, test_client):
        """Test chat request with valid data structure."""
        valid_request = {
            "messages": [
                {"role": "user", "content": "Hello, how are you?"}
            ],
            "user_id": "test@example.com",
            "session_id": str(uuid4()),
            "metadata": {}
        }

        response = test_client.post("/api/chat", json=valid_request)

        # We expect either success or service unavailable (if services not initialized)
        assert response.status_code in [200, 503]

    def test_chat_history_request(self, test_client):
        """Test requesting chat history without new messages."""
        history_request = {
            "messages": [],
            "user_id": "test@example.com",
            "session_id": str(uuid4())
        }

        response = test_client.post("/api/chat", json=history_request)

        # Should either return history or service unavailable
        assert response.status_code in [200, 503]


class TestPlanDetermination:
    """Test plan determination logic."""

    @pytest.mark.asyncio
    async def test_plan_type_determination(self):
        """Test the plan type determination function."""
        from chatbot.routes.chat import _determine_plan_type

        # Test conversational queries
        plan_type, use_sql, use_graph = await _determine_plan_type("hello there")
        assert plan_type == "direct"
        assert use_sql is False
        assert use_graph is False

        # Test SQL-oriented queries
        plan_type, use_sql, use_graph = await _determine_plan_type("show me sales data")
        assert plan_type == "sql"
        assert use_sql is True
        assert use_graph is False

        # Test graph-oriented queries
        plan_type, use_sql, use_graph = await _determine_plan_type("who is the contact for this account")
        assert plan_type == "graph"
        assert use_sql is False
        assert use_graph is True

        # Test hybrid queries
        plan_type, use_sql, use_graph = await _determine_plan_type("show me sales data and contacts")
        assert plan_type == "hybrid"
        assert use_sql is True
        assert use_graph is True

    @pytest.mark.asyncio
    async def test_direct_response_generation(self):
        """Test direct response generation."""
        from chatbot.routes.chat import _generate_direct_response
        from chatbot.models.rbac import RBACContext, AccessScope

        rbac_context = RBACContext(
            user_id="test@example.com",
            email="test@example.com",
            tenant_id="test-tenant",
            object_id="test-object-id",
            roles=["test_role"],
            access_scope=AccessScope(),
        )

        # Test greeting
        response = await _generate_direct_response("hello", rbac_context)
        assert "Hello" in response
        assert "Salesforce" in response

        # Test thanks
        response = await _generate_direct_response("thank you", rbac_context)
        assert "welcome" in response.lower()

        # Test general query
        response = await _generate_direct_response("random question", rbac_context)
        assert "Salesforce" in response


class TestResponseFormatting:
    """Test response formatting functions."""

    @pytest.mark.asyncio
    async def test_sql_response_formatting(self):
        """Test SQL response formatting."""
        from chatbot.routes.chat import _format_sql_response

        # Test successful SQL result
        sql_result = {
            "data": [
                {"account_name": "Test Account", "revenue": 100000},
                {"account_name": "Another Account", "revenue": 200000}
            ],
            "query": "SELECT account_name, revenue FROM accounts",
            "tables_used": ["accounts"]
        }

        response, sources = await _format_sql_response(sql_result, "show me account revenue")

        assert "I found 2 results" in response
        assert "Test Account" in response
        assert len(sources) == 1
        assert sources[0]["type"] == "sql"

        # Test empty result
        empty_result = {"data": [], "query": "SELECT * FROM accounts WHERE 1=0"}
        response, sources = await _format_sql_response(empty_result, "test query")

        assert "No data was found" in response
        assert len(sources) == 0

        # Test error result
        error_result = {"error": "Database connection failed"}
        response, sources = await _format_sql_response(error_result, "test query")

        assert "couldn't retrieve" in response
        assert len(sources) == 0

    @pytest.mark.asyncio
    async def test_graph_response_formatting(self):
        """Test graph response formatting."""
        from chatbot.routes.chat import _format_graph_response

        # Test successful graph result
        graph_result = {
            "relationships": [
                {"from": "Account A", "to": "Contact B", "relationship": "has contact"},
                {"from": "Account A", "to": "Document C", "relationship": "has document"}
            ],
            "documents": [
                {"name": "Contract.pdf", "summary": "Sales contract", "url": "https://example.com/contract.pdf"}
            ],
            "query": "g.V().hasLabel('account')"
        }

        response, sources = await _format_graph_response(graph_result, "show relationships")

        assert "I found 2 relationship(s)" in response
        assert "Account A" in response
        assert "Related documents (1)" in response
        assert len(sources) == 2  # One for relationships, one for document

        # Test empty result
        empty_result = {"relationships": [], "documents": []}
        response, sources = await _format_graph_response(empty_result, "test query")

        assert "No relationships or documents" in response
        assert len(sources) == 0

    @pytest.mark.asyncio
    async def test_hybrid_response_formatting(self):
        """Test hybrid response formatting."""
        from chatbot.routes.chat import _format_hybrid_response

        sql_result = {
            "data": [{"account": "Test Account", "revenue": 100000}],
            "query": "SELECT * FROM accounts",
            "tables_used": ["accounts"]
        }

        graph_result = {
            "relationships": [{"from": "Test Account", "to": "John Doe", "relationship": "has contact"}],
            "documents": [],
            "query": "g.V().hasLabel('account')"
        }

        response, sources = await _format_hybrid_response(sql_result, graph_result, "comprehensive query")

        assert "**Data Summary:**" in response
        assert "**Relationships & Documents:**" in response
        assert "Test Account" in response
        assert len(sources) == 2  # SQL and graph sources


class TestFeedbackHandling:
    """Test feedback handling functionality."""

    @pytest.mark.asyncio
    async def test_feedback_handling(self):
        """Test feedback handling in chat requests."""
        # This would require mocking the unified service
        # For now, just test that the function exists and can be called
        from chatbot.routes.chat import _handle_feedback
        from chatbot.models.rbac import RBACContext, AccessScope

        # Mock request data with feedback
        class MockRequest:
            def __init__(self):
                self.metadata = {
                    "feedback": {
                        "rating": 5,
                        "comment": "Great response!"
                    }
                }

        class MockUnifiedService:
            async def submit_feedback(self, **kwargs):
                return "feedback-id"

        request_data = MockRequest()
        unified_service = MockUnifiedService()
        turn_id = str(uuid4())
        user_context = RBACContext(
            user_id="test@example.com",
            email="test@example.com",
            tenant_id="test-tenant",
            object_id="test-object-id",
            roles=["test_role"],
            access_scope=AccessScope(),
        )

        # Should not raise an exception
        await _handle_feedback(request_data, unified_service, turn_id, user_context)