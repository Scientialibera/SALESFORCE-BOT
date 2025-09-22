"""
Interactive test script for CacheService and ChatHistoryRepository.

This script is intended to be run manually (not as pytest) to exercise
Cosmos-backed chat history operations and the CacheService set/get flows.

It uses the real clients configured by the application settings. If the
environment or Cosmos DB is not available, the script will print a helpful
message and exit gracefully.

Usage:
    python chatbot/src/chatbot/tests/test_cache_service.py

Note: ensure environment variables and `.env` are configured for Cosmos.
"""

import asyncio
import traceback
import os
import sys
from datetime import datetime
from pathlib import Path

# Ensure project src directory is on sys.path so `import chatbot` works when
# running this script directly from the tests directory.
_here = Path(__file__).resolve()
# tests -> chatbot (package) -> src
_src_dir = _here.parent.parent.parent
if _src_dir.exists() and str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

try:
    # Import application modules from the project
    from chatbot.config.settings import settings, CosmosDBSettings
    from chatbot.clients.cosmos_client import CosmosDBClient
    from chatbot.services.unified_service import UnifiedDataService
    from chatbot.models.rbac import RBACContext, AccessScope
    from chatbot.models.message import Message, MessageRole
except Exception as e:
    print("Failed to import project modules. Ensure you run this script from the project and that the virtualenv is activated.")
    print("Added to sys.path:", str(_src_dir))
    print("Import error:")
    traceback.print_exc()
    raise


async def run_test():
    print("Starting interactive cache/history test")

    # Prepare RBAC context (dev/test values)
    rbac = RBACContext(
        user_id=os.environ.get("DEV_USER_EMAIL", "testuser@example.com"),
        email=os.environ.get("DEV_USER_EMAIL", "testuser@example.com"),
        tenant_id=os.environ.get("DEV_USER_TENANT", "tenant123"),
        object_id=os.environ.get("DEV_USER_OID", "user123"),
        roles=["sales_rep"],
        access_scope=AccessScope(),
    )

    # Initialize Cosmos client and repositories
    try:
        cosmos_settings = CosmosDBSettings()
        cosmos_client = CosmosDBClient(cosmos_settings)
        chat_repo = ChatHistoryRepository(cosmos_client, cosmos_settings)

        # Construct cache repository with the same Cosmos client and configured container
        cache_db = getattr(cosmos_settings, "database", None) or getattr(cosmos_settings, "cosmos_database", None)
        cache_container = getattr(cosmos_settings, "cache_container", None) or "cache"
        if not cache_db:
            # Fallback to settings.database if different naming is used
            cache_db = getattr(cosmos_settings, "database_name", None) or getattr(cosmos_settings, "database", None)

        cache_repo = CacheRepository(cosmos_client, cache_db, cache_container)
        cache_service = CacheService(cache_repo)
    except Exception as e:
        print("Failed to initialize Cosmos or repositories. Check configuration:")
        traceback.print_exc()
        return

    # Create or ensure chat session
    chat_id = f"interactive-test-{int(datetime.utcnow().timestamp())}"
    try:
        print(f"Creating chat session with id: {chat_id}")
        chat_history = await chat_repo.create_chat_session(user_id=rbac.user_id, chat_id=chat_id, title="Interactive Test Chat")
        print("Created chat session:", chat_history.chat_id)
    except Exception:
        print("create_chat_session failed; attempting to continue and read existing chat if present")
        traceback.print_exc()

    # Retrieve chat history
    try:
        print(f"Retrieving chat history for id: {chat_id}")
        retrieved = await chat_repo.get_chat_history(chat_id, rbac.user_id)
        print("Retrieved chat history:")
        print(retrieved)
    except Exception:
        print("get_chat_history failed")
        traceback.print_exc()

    # If incoming request has no messages but has chat_id, return history logic
    print("Simulating incoming request with no messages but chat_id provided")
    incoming_messages = ""
    if not incoming_messages and chat_id:
        try:
            chat_hist = await chat_repo.get_chat_history(chat_id, rbac.user_id)
            print("Returning chat history because no incoming messages provided:")
            print(chat_hist)
        except Exception:
            print("Failed to fetch chat history for empty message path")
            traceback.print_exc()

    # Test adding a conversation turn via HistoryService pattern (direct repository here)
    try:
        # Construct messages
        user_msg = Message(id=f"{chat_id}-u1", role=MessageRole.USER, content="Hello from interactive test", timestamp=datetime.utcnow(), user_id=rbac.user_id)
        assistant_msg = Message(id=f"{chat_id}-a1", role=MessageRole.ASSISTANT, content="Hello! This is a test reply.", timestamp=datetime.utcnow())

        from chatbot.services.history_service import HistoryService
        history_service = HistoryService(chat_repo)

        print("Adding a conversation turn...")
        turn = await history_service.add_conversation_turn(
            chat_id=chat_id,
            user_message=user_msg,
            assistant_message=assistant_msg,
            rbac_context=rbac,
            execution_metadata={"turn_id": "interactive-1", "sources": [], "response_type": "direct"}
        )
        print("Added turn:", turn)
    except Exception:
        print("Failed to add conversation turn")
        traceback.print_exc()

    # Test cache set/get
    try:
        print("Testing cache set/get for a simple query key")
        key_query = "SELECT 1 AS test"
        sample_result = {"rows": [[1]], "meta": {"executed_at": datetime.utcnow().isoformat()}}
        ok = await cache_service.set_query_result(key_query, sample_result, rbac, query_type="sql")
        print("Cache set returned:", ok)
        cached = await cache_service.get_query_result(key_query, rbac, query_type="sql")
        print("Cached value:", cached)
    except Exception:
        print("Cache test failed")
        traceback.print_exc()

    print("Interactive test finished")
    # Attempt to close the cosmos client to avoid unclosed session warnings
    try:
        await cosmos_client.close()
    except Exception:
        pass


if __name__ == "__main__":
    asyncio.run(run_test())
