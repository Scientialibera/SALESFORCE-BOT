"""
Tests for the unified data service.

Tests the core functionality of session management, message persistence,
and feedback handling using Cosmos DB.
"""

import pytest
import asyncio
from datetime import datetime
from uuid import uuid4

from chatbot.config.settings import settings
from chatbot.clients.cosmos_client import CosmosDBClient
from chatbot.services.unified_service import UnifiedDataService
from chatbot.models.rbac import RBACContext, AccessScope
from chatbot.models.message import Message, MessageRole


@pytest.fixture
async def cosmos_client():
    """Create Cosmos DB client for testing."""
    client = CosmosDBClient(settings.cosmos_db)
    yield client
    await client.close()


@pytest.fixture
async def unified_service(cosmos_client):
    """Create unified data service for testing."""
    return UnifiedDataService(cosmos_client, settings.cosmos_db)


@pytest.fixture
def test_rbac_context():
    """Create test RBAC context."""
    return RBACContext(
        user_id="test@example.com",
        email="test@example.com",
        tenant_id="test-tenant",
        object_id="test-object-id",
        roles=["test_role"],
        access_scope=AccessScope(),
    )


class TestUnifiedDataService:
    """Test suite for unified data service."""

    @pytest.mark.asyncio
    async def test_create_chat_session(self, unified_service, test_rbac_context):
        """Test creating a new chat session."""
        session_id = str(uuid4())
        title = "Test Chat Session"

        chat_history = await unified_service.create_chat_session(
            rbac_context=test_rbac_context,
            chat_id=session_id,
            title=title
        )

        assert chat_history.chat_id == session_id
        assert chat_history.user_id == test_rbac_context.user_id
        assert chat_history.title == title
        assert len(chat_history.turns) == 0

    @pytest.mark.asyncio
    async def test_add_conversation_turn(self, unified_service, test_rbac_context):
        """Test adding a conversation turn to a session."""
        session_id = str(uuid4())

        # Create session first
        await unified_service.create_chat_session(
            rbac_context=test_rbac_context,
            chat_id=session_id
        )

        # Create messages
        user_message = Message(
            id=f"{session_id}_user_1",
            role=MessageRole.USER,
            content="Hello, test message",
            timestamp=datetime.utcnow(),
            user_id=test_rbac_context.user_id
        )

        assistant_message = Message(
            id=f"{session_id}_assistant_1",
            role=MessageRole.ASSISTANT,
            content="Hello! How can I help you?",
            timestamp=datetime.utcnow()
        )

        # Add conversation turn
        turn = await unified_service.add_conversation_turn(
            chat_id=session_id,
            user_message=user_message,
            assistant_message=assistant_message,
            rbac_context=test_rbac_context,
            execution_metadata={"test": "metadata"}
        )

        assert turn.user_message.content == "Hello, test message"
        assert turn.assistant_message.content == "Hello! How can I help you?"
        assert turn.turn_number == 1

    @pytest.mark.asyncio
    async def test_get_chat_context(self, unified_service, test_rbac_context):
        """Test retrieving chat context."""
        session_id = str(uuid4())

        # Create session and add a turn
        await unified_service.create_chat_session(
            rbac_context=test_rbac_context,
            chat_id=session_id
        )

        user_message = Message(
            id=f"{session_id}_user_1",
            role=MessageRole.USER,
            content="Test message",
            timestamp=datetime.utcnow(),
            user_id=test_rbac_context.user_id
        )

        assistant_message = Message(
            id=f"{session_id}_assistant_1",
            role=MessageRole.ASSISTANT,
            content="Test response",
            timestamp=datetime.utcnow()
        )

        await unified_service.add_conversation_turn(
            chat_id=session_id,
            user_message=user_message,
            assistant_message=assistant_message,
            rbac_context=test_rbac_context
        )

        # Get chat context
        context = await unified_service.get_chat_context(
            chat_id=session_id,
            rbac_context=test_rbac_context,
            max_turns=10
        )

        assert len(context) == 1
        assert context[0].user_message.content == "Test message"
        assert context[0].assistant_message.content == "Test response"

    @pytest.mark.asyncio
    async def test_submit_feedback(self, unified_service, test_rbac_context):
        """Test submitting feedback."""
        turn_id = str(uuid4())
        rating = 4
        comment = "Great response!"

        feedback_id = await unified_service.submit_feedback(
            turn_id=turn_id,
            user_id=test_rbac_context.user_id,
            rating=rating,
            comment=comment,
            metadata={"test": "feedback"}
        )

        assert feedback_id is not None
        assert isinstance(feedback_id, str)

    @pytest.mark.asyncio
    async def test_get_feedback_for_turn(self, unified_service, test_rbac_context):
        """Test retrieving feedback for a turn."""
        turn_id = str(uuid4())
        rating = 5
        comment = "Excellent!"

        # Submit feedback
        feedback_id = await unified_service.submit_feedback(
            turn_id=turn_id,
            user_id=test_rbac_context.user_id,
            rating=rating,
            comment=comment
        )

        # Retrieve feedback
        feedback = await unified_service.get_feedback_for_turn(turn_id)

        assert feedback is not None
        if hasattr(feedback, 'rating'):
            assert feedback.rating == rating
            assert feedback.comment == comment

    @pytest.mark.asyncio
    async def test_cache_operations(self, unified_service, test_rbac_context):
        """Test cache set and get operations."""
        query = "SELECT * FROM accounts"
        result = {"data": [{"id": 1, "name": "Test Account"}]}

        # Set cache
        success = await unified_service.set_query_result(
            query=query,
            result=result,
            rbac_context=test_rbac_context,
            query_type="sql"
        )

        assert success is True

        # Get cache
        cached_result = await unified_service.get_query_result(
            query=query,
            rbac_context=test_rbac_context,
            query_type="sql"
        )

        assert cached_result is not None
        assert cached_result == result

    @pytest.mark.asyncio
    async def test_embedding_operations(self, unified_service):
        """Test embedding storage and retrieval."""
        text = "This is a test document"
        embedding = [0.1, 0.2, 0.3, 0.4, 0.5]

        # Set embedding
        success = await unified_service.set_embedding(
            text=text,
            embedding=embedding
        )

        assert success is True

        # Get embedding
        stored_embedding = await unified_service.get_embedding(text)

        assert stored_embedding is not None
        assert stored_embedding == embedding

    @pytest.mark.asyncio
    async def test_user_permissions(self, unified_service, test_rbac_context):
        """Test user permissions storage and retrieval."""
        permissions = {
            "accounts": ["read", "write"],
            "opportunities": ["read"]
        }

        # Set permissions
        success = await unified_service.set_user_permissions(
            user_id=test_rbac_context.user_id,
            permissions=permissions
        )

        assert success is True

        # Get permissions
        stored_permissions = await unified_service.get_user_permissions(
            user_id=test_rbac_context.user_id
        )

        assert stored_permissions is not None
        assert stored_permissions == permissions

    @pytest.mark.asyncio
    async def test_cache_invalidation(self, unified_service, test_rbac_context):
        """Test cache invalidation for a user."""
        # Set some cache data
        await unified_service.set_query_result(
            query="test query",
            result={"test": "data"},
            rbac_context=test_rbac_context
        )

        await unified_service.set_user_permissions(
            user_id=test_rbac_context.user_id,
            permissions={"test": "permissions"}
        )

        # Invalidate cache
        success = await unified_service.invalidate_user_cache(
            user_id=test_rbac_context.user_id
        )

        # Should return True if any items were deleted
        assert isinstance(success, bool)

    @pytest.mark.asyncio
    async def test_get_cache_stats(self, unified_service):
        """Test getting cache statistics."""
        stats = await unified_service.get_cache_stats()

        assert isinstance(stats, dict)
        assert "cache_count" in stats
        assert isinstance(stats["cache_count"], int)