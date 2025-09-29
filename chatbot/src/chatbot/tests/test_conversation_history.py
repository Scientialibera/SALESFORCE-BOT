import asyncio
import sys
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

# Fix encoding for Windows console
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

# Ensure chatbot/src is on path when running this script directly.
file_path = Path(__file__).resolve()
# repo layout: <repo>/chatbot/src/chatbot/tests
repo_root = file_path.parents[4]
chatbot_src = repo_root / "chatbot" / "src"
sys.path.insert(0, str(chatbot_src))

from chatbot.config.settings import settings
from chatbot.clients.cosmos_client import CosmosDBClient
from chatbot.services.unified_service import UnifiedDataService
from chatbot.models.rbac import RBACContext, AccessScope
from chatbot.models.message import Message, MessageRole


# ──────────────────────────────────────────────────────────────────────────────
# Test Functions
# ──────────────────────────────────────────────────────────────────────────────

async def test_create_chat_session(unified_service: UnifiedDataService, rbac_ctx: RBACContext) -> str:
    """Test creating a new chat session."""
    print("\n=== Test: Create Chat Session ===")

    try:
        chat_history = await unified_service.create_chat_session(
            rbac_context=rbac_ctx,
            chat_id=None,  # Let it auto-generate
            title="Test Conversation",
            metadata={"source": "test_script", "environment": "dev"}
        )

        print(f"[OK] Created chat session: {chat_history.chat_id}")
        print(f"  User ID: {chat_history.user_id}")
        print(f"  Title: {chat_history.title}")
        print(f"  Created at: {chat_history.created_at}")
        print(f"  Total turns: {chat_history.total_turns}")

        return chat_history.chat_id

    except Exception as e:
        print(f"[FAIL] Failed to create chat session: {e}")
        import traceback
        traceback.print_exc()
        raise


async def test_add_conversation_turn(
    unified_service: UnifiedDataService,
    rbac_ctx: RBACContext,
    chat_id: str
) -> str:
    """Test adding a conversation turn to existing chat session."""
    print("\n=== Test: Add Conversation Turn ===")

    try:
        # Create user and assistant messages
        user_msg = Message(
            id=f"msg_user_{datetime.utcnow().timestamp()}",
            role=MessageRole.USER,
            content="What are the top accounts by revenue?",
            timestamp=datetime.utcnow(),
            user_id=rbac_ctx.user_id
        )

        assistant_msg = Message(
            id=f"msg_asst_{datetime.utcnow().timestamp()}",
            role=MessageRole.ASSISTANT,
            content="Based on the data, here are the top accounts by revenue: Microsoft ($5M), Amazon ($4M), Google ($3M).",
            timestamp=datetime.utcnow()
        )

        turn = await unified_service.add_conversation_turn(
            chat_id=chat_id,
            user_message=user_msg,
            assistant_message=assistant_msg,
            rbac_context=rbac_ctx,
            execution_metadata={"execution_time_ms": 1234, "plan_type": "sql"}
        )

        print(f"[OK] Added conversation turn: {turn.id}")
        print(f"  Turn number: {turn.turn_number}")
        print(f"  User message: {user_msg.content}")
        print(f"  Assistant message: {assistant_msg.content[:50]}...")

        return turn.id

    except Exception as e:
        print(f"[FAIL] Failed to add conversation turn: {e}")
        import traceback
        traceback.print_exc()
        raise


async def test_get_chat_context(
    unified_service: UnifiedDataService,
    rbac_ctx: RBACContext,
    chat_id: str
) -> None:
    """Test retrieving chat context (conversation history)."""
    print("\n=== Test: Get Chat Context ===")

    try:
        turns = await unified_service.get_chat_context(
            chat_id=chat_id,
            rbac_context=rbac_ctx,
            max_turns=10
        )

        print(f"[OK] Retrieved {len(turns)} conversation turn(s)")

        if isinstance(turns, list):
            for i, turn in enumerate(turns):
                print(f"\n  Turn {i + 1}:")
                if hasattr(turn, 'user_message') and turn.user_message:
                    print(f"    User: {turn.user_message.content[:60]}...")
                if hasattr(turn, 'assistant_message') and turn.assistant_message:
                    print(f"    Assistant: {turn.assistant_message.content[:60]}...")
        else:
            print(f"  Warning: Expected list, got {type(turns)}")

        return turns

    except Exception as e:
        print(f"[FAIL] Failed to get chat context: {e}")
        import traceback
        traceback.print_exc()
        raise


async def test_get_user_chat_sessions(
    unified_service: UnifiedDataService,
    user_id: str
) -> None:
    """Test retrieving all chat sessions for a user."""
    print("\n=== Test: Get User Chat Sessions ===")

    try:
        sessions = await unified_service.get_user_chat_sessions(
            user_id=user_id,
            limit=50,
            offset=0
        )

        print(f"[OK] Retrieved {len(sessions)} chat session(s) for user {user_id}")

        for i, session in enumerate(sessions[:3]):  # Show first 3
            print(f"\n  Session {i + 1}:")
            print(f"    ID: {session.chat_id}")
            print(f"    Title: {session.title}")
            print(f"    Total turns: {session.total_turns}")
            print(f"    Created: {session.created_at}")
            print(f"    Updated: {session.updated_at}")

        if len(sessions) > 3:
            print(f"\n  ... and {len(sessions) - 3} more session(s)")

    except Exception as e:
        print(f"[FAIL] Failed to get user chat sessions: {e}")
        import traceback
        traceback.print_exc()
        raise


async def test_add_multiple_turns(
    unified_service: UnifiedDataService,
    rbac_ctx: RBACContext,
    chat_id: str
) -> None:
    """Test adding multiple conversation turns to verify history accumulation."""
    print("\n=== Test: Add Multiple Turns ===")

    try:
        conversations = [
            ("Tell me about Microsoft account", "Microsoft is one of our key accounts with $5M revenue."),
            ("What about their recent opportunities?", "Microsoft has 3 open opportunities totaling $1.2M."),
            ("Who is the primary contact?", "The primary contact is John Doe, VP of Engineering."),
        ]

        for i, (user_content, assistant_content) in enumerate(conversations):
            user_msg = Message(
                id=f"msg_user_{i}_{datetime.utcnow().timestamp()}",
                role=MessageRole.USER,
                content=user_content,
                timestamp=datetime.utcnow(),
                user_id=rbac_ctx.user_id
            )

            assistant_msg = Message(
                id=f"msg_asst_{i}_{datetime.utcnow().timestamp()}",
                role=MessageRole.ASSISTANT,
                content=assistant_content,
                timestamp=datetime.utcnow()
            )

            turn = await unified_service.add_conversation_turn(
                chat_id=chat_id,
                user_message=user_msg,
                assistant_message=assistant_msg,
                rbac_context=rbac_ctx,
                execution_metadata={"execution_time_ms": 1000 + i * 100}
            )

            print(f"  [OK] Added turn {turn.turn_number}: {user_content[:40]}...")

        print(f"\n[OK] Successfully added {len(conversations)} conversation turns")

    except Exception as e:
        print(f"[FAIL] Failed to add multiple turns: {e}")
        import traceback
        traceback.print_exc()
        raise


async def test_conversation_context_format(
    unified_service: UnifiedDataService,
    rbac_ctx: RBACContext,
    chat_id: str
) -> None:
    """Test that conversation context is returned in the format expected by planner_service."""
    print("\n=== Test: Conversation Context Format ===")

    try:
        # Get chat context
        turns = await unified_service.get_chat_context(
            chat_id=chat_id,
            rbac_context=rbac_ctx,
            max_turns=3
        )

        print(f"[OK] Retrieved {len(turns)} turn(s)")
        print(f"  Type of turns: {type(turns)}")

        # Transform to the format expected by planner_service.py:295-302
        if turns and isinstance(turns, list):
            conversation_context = []
            for turn in turns[-3:]:
                if hasattr(turn, 'user_message') and hasattr(turn, 'assistant_message'):
                    if turn.user_message and turn.assistant_message:
                        ctx_dict = {
                            "user_message": turn.user_message.content,
                            "assistant_message": turn.assistant_message.content
                        }
                        conversation_context.append(ctx_dict)
                        print(f"\n  Formatted turn:")
                        print(f"    user_message: {ctx_dict['user_message'][:50]}...")
                        print(f"    assistant_message: {ctx_dict['assistant_message'][:50]}...")
                else:
                    print(f"  Warning: Turn missing expected attributes: {turn}")

            print(f"\n[OK] Successfully formatted {len(conversation_context)} turn(s) for planner context")
        else:
            print(f"  Warning: No turns to format or unexpected type: {type(turns)}")

    except Exception as e:
        print(f"[FAIL] Failed to format conversation context: {e}")
        import traceback
        traceback.print_exc()
        raise


async def test_delete_chat_session(
    unified_service: UnifiedDataService,
    rbac_ctx: RBACContext,
    chat_id: str
) -> None:
    """Test deleting a chat session."""
    print("\n=== Test: Delete Chat Session ===")

    try:
        success = await unified_service.delete_chat_session(
            chat_id=chat_id,
            rbac_context=rbac_ctx
        )

        if success:
            print(f"[OK] Successfully deleted chat session: {chat_id}")
        else:
            print(f"[FAIL] Failed to delete chat session: {chat_id}")

    except Exception as e:
        print(f"[FAIL] Failed to delete chat session: {e}")
        import traceback
        traceback.print_exc()
        raise


# ──────────────────────────────────────────────────────────────────────────────
# Main Test Runner
# ──────────────────────────────────────────────────────────────────────────────

async def run_tests():
    """Run all conversation history tests."""
    print("\n" + "=" * 80)
    print("CONVERSATION HISTORY TESTS")
    print("=" * 80)

    # Initialize clients
    print("\nInitializing Cosmos DB client...")
    cosmos_client = CosmosDBClient(settings.cosmos_db)

    print("Initializing unified data service...")
    unified_service = UnifiedDataService(cosmos_client, settings.cosmos_db)

    # Create test RBAC context
    rbac_ctx = RBACContext(
        user_id="test_user_history",
        email="test_user_history@example.com",
        tenant_id="test-tenant",
        object_id="test-object-id",
        roles=["admin"],
        permissions=set(),
        access_scope=AccessScope(),
        is_admin=True,
    )

    print(f"Using test user: {rbac_ctx.user_id}")

    try:
        # Test 1: Create chat session
        chat_id = await test_create_chat_session(unified_service, rbac_ctx)

        # Test 2: Add single conversation turn
        turn_id = await test_add_conversation_turn(unified_service, rbac_ctx, chat_id)

        # Test 3: Get chat context
        turns = await test_get_chat_context(unified_service, rbac_ctx, chat_id)

        # Test 4: Add multiple turns
        await test_add_multiple_turns(unified_service, rbac_ctx, chat_id)

        # Test 5: Get chat context again (should have more turns)
        turns = await test_get_chat_context(unified_service, rbac_ctx, chat_id)

        # Test 6: Test conversation context format for planner
        await test_conversation_context_format(unified_service, rbac_ctx, chat_id)

        # Test 7: Get all user chat sessions
        await test_get_user_chat_sessions(unified_service, rbac_ctx.user_id)

        # Test 8: Delete chat session (cleanup)
        await test_delete_chat_session(unified_service, rbac_ctx, chat_id)

        print("\n" + "=" * 80)
        print("ALL TESTS COMPLETED SUCCESSFULLY")
        print("=" * 80)

    except Exception as e:
        print("\n" + "=" * 80)
        print(f"TESTS FAILED: {e}")
        print("=" * 80)
        import traceback
        traceback.print_exc()

    finally:
        # Cleanup
        try:
            await cosmos_client.close()
            print("\n[OK] Cosmos DB client closed")
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(run_tests())