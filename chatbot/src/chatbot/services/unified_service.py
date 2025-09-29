"""UnifiedDataService

This version of the unified service speaks directly to the Cosmos DB client and
provides a single facade for per-user chat sessions, cache entries, embeddings
and feedback items. Legacy services and repositories were removed; this class
implements the minimal functionality required by the rest of the application.
"""
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from uuid import uuid4
import hashlib
import json
import structlog

from chatbot.clients.cosmos_client import CosmosDBClient
from chatbot.config.settings import CosmosDBSettings
from chatbot.models.rbac import RBACContext
from chatbot.models.message import Message, ConversationTurn, ChatHistory
from chatbot.models.result import FeedbackData

logger = structlog.get_logger(__name__)


class UnifiedDataService:
    """Facade that stores and retrieves per-user data in a single container.

    The implementation is intentionally conservative: documents are stored with
    a `doc_type` field to distinguish chat sessions, cache entries and
    feedback documents. The partition key used is `/user_id` so most operations
    require a user identifier (derived from RBACContext when available).
    """

    def __init__(self, cosmos_client: CosmosDBClient, settings: CosmosDBSettings):
        self._client = cosmos_client
        # Default container where unified data lives
        self._container = settings.chat_container
        self._settings = settings

    # -----------------
    # Chat history API
    # -----------------
    async def create_chat_session(self, rbac_context: RBACContext, chat_id: Optional[str] = None, title: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> ChatHistory:
        user_id = rbac_context.user_id
        chat_id = chat_id or str(uuid4())
        chat_history = ChatHistory(chat_id=chat_id, user_id=user_id, title=title, metadata=metadata or {})

        chat_doc = {
            "id": chat_id,
            "user_id": user_id,
            "doc_type": "chat_session",
            "chat_data": chat_history.model_dump(mode="json"),
            "created_at": chat_history.created_at.isoformat(),
            "updated_at": chat_history.updated_at.isoformat(),
        }

        await self._client.create_item(self._container, chat_doc, partition_key="/user_id")
        logger.info("Created chat session", chat_id=chat_id, user_id=user_id)
        return chat_history

    async def add_conversation_turn(self, chat_id: str, user_message: Message, assistant_message: Message, rbac_context: RBACContext, plan=None, tool_calls=None, execution_metadata=None) -> ConversationTurn:
        user_id = rbac_context.user_id
        # Read the chat session
        doc = await self._client.read_item(container_name=self._container, item_id=chat_id, partition_key_value=user_id)
        if not doc:
            # try id-based fallback
            doc = await self._client.read_item(container_name=self._container, item_id=chat_id, partition_key_value=chat_id)
        if not doc:
            raise ValueError("Chat session not found")

        chat_data = doc.get("chat_data", {})
        if isinstance(chat_data, str):
            try:
                chat = ChatHistory.model_validate_json(chat_data)
            except Exception:
                chat = ChatHistory(**json.loads(chat_data))
        else:
            chat = ChatHistory(**chat_data)

        # create turn
        turn = ConversationTurn(
            id=f"turn_{uuid4().hex[:8]}",
            user_message=user_message,
            assistant_message=assistant_message,
            turn_number=(chat.total_turns or 0) + 1,
            planning_time_ms=execution_metadata.get("planning_time_ms") if execution_metadata else None,
            total_time_ms=execution_metadata.get("total_time_ms") if execution_metadata else None,
            execution_metadata=execution_metadata,
        )

        # append and persist
        chat.add_turn(turn)
        chat_doc = {
            "id": chat.chat_id,
            "user_id": chat.user_id,
            "doc_type": "chat_session",
            "chat_data": chat.model_dump(mode="json"),
            "created_at": chat.created_at.isoformat(),
            "updated_at": chat.updated_at.isoformat(),
        }

        await self._client.upsert_item(self._container, chat_doc, partition_key="/user_id")
        logger.info("Added conversation turn", chat_id=chat.chat_id, turn_id=turn.id)
        return turn

    async def get_chat_context(self, chat_id: str, rbac_context: RBACContext, max_turns: int = 10):
        user_id = rbac_context.user_id
        doc = await self._client.read_item(container_name=self._container, item_id=chat_id, partition_key_value=user_id)
        if not doc:
            doc = await self._client.read_item(container_name=self._container, item_id=chat_id, partition_key_value=chat_id)
        if not doc:
            return []

        chat_data = doc.get("chat_data", {})
        if isinstance(chat_data, str):
            try:
                chat = ChatHistory.model_validate_json(chat_data)
            except Exception:
                chat = ChatHistory(**json.loads(chat_data))
        else:
            chat = ChatHistory(**chat_data)

        return chat.turns[-max_turns:] if chat.turns else []

    async def get_user_chat_sessions(self, user_id: str, limit: int = 50, offset: int = 0):
        query = "SELECT * FROM c WHERE c.user_id = @user_id AND c.doc_type = 'chat_session' ORDER BY c.created_at DESC OFFSET @offset LIMIT @limit"
        parameters = [
            {"name": "@user_id", "value": user_id},
            {"name": "@offset", "value": offset},
            {"name": "@limit", "value": limit},
        ]
        docs = await self._client.query_items(container_name=self._container, query=query, parameters=parameters, partition_key_value=user_id)
        sessions = []
        for doc in docs:
            chat_data = doc.get("chat_data", {})
            if isinstance(chat_data, str):
                try:
                    sessions.append(ChatHistory.model_validate_json(chat_data))
                except Exception:
                    sessions.append(ChatHistory(**json.loads(chat_data)))
            else:
                sessions.append(ChatHistory(**chat_data))
        return sessions

    async def delete_chat_session(self, chat_id: str, rbac_context: RBACContext) -> bool:
        user_id = rbac_context.user_id
        # verify ownership
        chat = await self._client.read_item(container_name=self._container, item_id=chat_id, partition_key_value=user_id)
        if not chat:
            return False
        return await self._client.delete_item(container_name=self._container, item_id=chat_id, partition_key_value=user_id)

    # -----------------
    # Cache / embeddings
    # -----------------
    def _query_key(self, query: str, rbac_context: RBACContext, query_type: str) -> str:
        key_data = {"query": query.strip().lower(), "user_id": rbac_context.user_id, "tenant_id": getattr(rbac_context, "tenant_id", None), "roles": sorted(getattr(rbac_context, "roles", [])), "query_type": query_type}
        key_string = json.dumps(key_data, sort_keys=True)
        key_hash = hashlib.md5(key_string.encode()).hexdigest()
        return f"query:{query_type}:user:{rbac_context.user_id}:{key_hash}"

    def _embedding_key(self, text: str) -> str:
        normalized_text = text.strip().lower()
        return f"embedding:{hashlib.md5(normalized_text.encode()).hexdigest()}"

    async def get_query_result(self, query: str, rbac_context: RBACContext, query_type: str = "sql"):
        key = self._query_key(query, rbac_context, query_type)
        doc = await self._client.read_item(container_name=self._container, item_id=key, partition_key_value=rbac_context.user_id)
        if not doc:
            return None
        return doc.get("value")

    async def set_query_result(self, query: str, result: Any, rbac_context: RBACContext, query_type: str = "sql", ttl_seconds: Optional[int] = None) -> bool:
        key = self._query_key(query, rbac_context, query_type)
        ttl = ttl_seconds or 1800
        doc = {"id": key, "user_id": rbac_context.user_id, "doc_type": "cache", "value": result, "expires_at": (datetime.utcnow() + timedelta(seconds=ttl)).isoformat()}
        await self._client.upsert_item(self._container, doc, partition_key="/user_id")
        return True

    async def get_embedding(self, text: str):
        key = self._embedding_key(text)
        doc = await self._client.read_item(container_name=self._container, item_id=key, partition_key_value=key)
        if not doc:
            doc = await self._client.read_item(container_name=self._container, item_id=key, partition_key_value="")
        if not doc:
            return None
        return doc.get("embedding")

    async def set_embedding(self, text: str, embedding: List[float], ttl_seconds: Optional[int] = None) -> bool:
        key = self._embedding_key(text)
        ttl = ttl_seconds or 86400
        doc = {"id": key, "user_id": "", "doc_type": "embedding", "embedding": embedding, "expires_at": (datetime.utcnow() + timedelta(seconds=ttl)).isoformat()}
        await self._client.upsert_item(self._container, doc, partition_key="/user_id")
        return True

    async def get_user_permissions(self, user_id: str):
        key = f"permissions:{user_id}"
        doc = await self._client.read_item(container_name=self._container, item_id=key, partition_key_value=user_id)
        if not doc:
            return None
        return doc.get("permissions")

    async def set_user_permissions(self, user_id: str, permissions: Dict[str, Any], ttl_seconds: Optional[int] = None) -> bool:
        key = f"permissions:{user_id}"
        ttl = ttl_seconds or 3600
        doc = {"id": key, "user_id": user_id, "doc_type": "permissions", "permissions": permissions, "expires_at": (datetime.utcnow() + timedelta(seconds=ttl)).isoformat()}
        await self._client.upsert_item(self._container, doc, partition_key="/user_id")
        return True

    async def invalidate_user_cache(self, user_id: str) -> bool:
        # Best-effort: delete typical cache doc types for user
        deleted = 0
        for doc_type in ("cache", "permissions"):
            query = "SELECT c.id FROM c WHERE c.user_id = @user_id AND c.doc_type = @doc_type"
            params = [{"name": "@user_id", "value": user_id}, {"name": "@doc_type", "value": doc_type}]
            docs = await self._client.query_items(container_name=self._container, query=query, parameters=params, partition_key_value=user_id)
            for d in docs:
                if await self._client.delete_item(container_name=self._container, item_id=d["id"], partition_key_value=user_id):
                    deleted += 1
        return deleted > 0

    async def get_cache_stats(self) -> Dict[str, Any]:
        # Simple stats placeholder
        query = "SELECT VALUE COUNT(1) FROM c WHERE c.doc_type = 'cache'"
        result = await self._client.query_items(container_name=self._container, query=query, parameters=None)
        try:
            count = int(next(iter(result), 0))
        except Exception:
            count = 0
        return {"cache_count": count}

    # -----------------
    # Feedback API
    # -----------------
    async def submit_feedback(self, turn_id: str, user_id: str, rating: int, comment: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> str:
        if not 1 <= rating <= 5:
            raise ValueError("Rating must be between 1 and 5")
        feedback_id = str(uuid4())
        doc = {
            "id": feedback_id,
            "user_id": user_id,
            "doc_type": "feedback",
            "turn_id": turn_id,
            "rating": rating,
            "comment": comment,
            "metadata": metadata or {},
            "created_at": datetime.utcnow().isoformat(),
        }
        await self._client.create_item(self._container, doc, partition_key="/user_id")
        return feedback_id

    async def get_feedback_for_turn(self, turn_id: str) -> Optional[FeedbackData]:
        query = "SELECT * FROM c WHERE c.doc_type = 'feedback' AND c.turn_id = @turn_id"
        params = [{"name": "@turn_id", "value": turn_id}]
        docs = await self._client.query_items(container_name=self._container, query=query, parameters=params)
        for d in docs:
            # Convert to FeedbackData if model exists, otherwise return raw
            try:
                return FeedbackData(**d)
            except Exception:
                return d
        return None

    async def get_user_feedback_history(self, rbac_context: RBACContext, limit: int = 50, offset: int = 0):
        user_id = rbac_context.user_id
        query = "SELECT * FROM c WHERE c.user_id = @user_id AND c.doc_type = 'feedback' ORDER BY c.created_at DESC OFFSET @offset LIMIT @limit"
        params = [{"name": "@user_id", "value": user_id}, {"name": "@offset", "value": offset}, {"name": "@limit", "value": limit}]
        docs = await self._client.query_items(container_name=self._container, query=query, parameters=params, partition_key_value=user_id)
        out = []
        for d in docs:
            try:
                out.append(FeedbackData(**d))
            except Exception:
                out.append(d)
        return out

    async def get_feedback_analytics(self, rbac_context: RBACContext, start_date=None, end_date=None):
        # Basic analytics implementation
        if not end_date:
            end_date = datetime.utcnow()
        if not start_date:
            start_date = end_date - timedelta(days=30)
        query = "SELECT c.rating FROM c WHERE c.doc_type = 'feedback' AND c.created_at >= @start AND c.created_at <= @end"
        params = [{"name": "@start", "value": start_date.isoformat()}, {"name": "@end", "value": end_date.isoformat()}]
        docs = await self._client.query_items(container_name=self._container, query=query, parameters=params)
        ratings = [d.get("rating") for d in docs if d.get("rating") is not None]
        if not ratings:
            return {"total_feedback": 0, "average_rating": 0.0}
        avg = sum(ratings) / len(ratings)
        return {"total_feedback": len(ratings), "average_rating": avg}

    async def delete_feedback(self, feedback_id: str, rbac_context: RBACContext) -> bool:
        # Verify ownership/admin
        item = await self._client.read_item(container_name=self._container, item_id=feedback_id, partition_key_value=rbac_context.user_id)
        if not item:
            # try reading without partition
            item = await self._client.read_item(container_name=self._container, item_id=feedback_id, partition_key_value=feedback_id)
        if not item:
            return False
        # Only admin or owner may delete
        if "admin" not in (rbac_context.roles or []) and item.get("user_id") != rbac_context.user_id:
            raise PermissionError("User does not have permission to delete this feedback")
        return await self._client.delete_item(container_name=self._container, item_id=feedback_id, partition_key_value=item.get("user_id"))
