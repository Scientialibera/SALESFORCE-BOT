"""Clean minimal chat router exposing only POST /chat.

This file is a safe, minimal implementation intended to replace the
existing `chat.py`. It exposes a single POST `/chat` endpoint, uses
`UnifiedDataService` for persistence and calls the AOAI client (if
configured) to obtain an assistant response. The file intentionally
contains no markdown fences, duplicated blocks, or stray text.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import uuid4
import structlog
from fastapi import APIRouter, HTTPException, Depends, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt as jose_jwt
from pydantic import BaseModel, Field

from chatbot.models.message import Message, MessageRole
from chatbot.models.rbac import RBACContext, AccessScope
from chatbot.services.unified_service import UnifiedDataService
from chatbot.config.settings import settings

logger = structlog.get_logger(__name__)

router = APIRouter()
security = HTTPBearer(auto_error=False)


class ChatMessage(BaseModel):
    role: str = Field(..., description="Message role: 'system', 'user', or 'assistant'")
    content: str = Field(..., description="Message content")


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    user_id: str
    session_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    session_id: str
    turn_id: str
    choices: List[Dict[str, Any]]
    usage: Dict[str, int] = Field(default_factory=dict)
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    request: Request = None,
) -> RBACContext:
    logger.info("Authenticating user request", url=str(request.url) if request else "unknown")

    if credentials and getattr(credentials, "credentials", None):
        token = credentials.credentials
        try:
            claims = jose_jwt.get_unverified_claims(token)
        except Exception:
            claims = {"oid": "user123", "email": "user@example.com", "tid": "tenant123", "roles": ["sales_rep"]}

        return RBACContext(
            user_id=claims.get("email", "user@example.com"),
            email=claims.get("email", "user@example.com"),
            tenant_id=claims.get("tid", "tenant123"),
            object_id=claims.get("oid", "user123"),
            roles=claims.get("roles", ["sales_rep"]),
            access_scope=AccessScope(),
        )

    return RBACContext(
        user_id="user@example.com",
        email="user@example.com",
        tenant_id="tenant123",
        object_id="user123",
        roles=["sales_rep"],
        access_scope=AccessScope(),
    )


def get_unified_service() -> UnifiedDataService:
    from chatbot.app import app_state

    uds = getattr(app_state, "unified_data_service", None)
    if not uds:
        raise HTTPException(status_code=503, detail="Unified data service not available")
    return uds


@router.post("/chat", response_model=ChatResponse)
async def send_message(
    request_data: ChatRequest,
    unified_service: UnifiedDataService = Depends(get_unified_service),
    user_context: RBACContext = Depends(get_current_user),
) -> ChatResponse:
    # If no messages provided but a session_id is present, return chat history
    if not request_data.messages or len(request_data.messages) == 0:
        if request_data.session_id:
            # fetch chat context from unified service
            chat_ctx = await unified_service.get_chat_context(request_data.session_id, user_context, max_turns=50)
            # convert chat_ctx to ChatResponse-like structure (lightweight)
            turns = getattr(chat_ctx, "turns", [])
            choices = []
            for t in turns:
                choices.append({"index": len(choices), "message": {"role": t.assistant_message.role.value if t.assistant_message else "assistant", "content": t.assistant_message.content if t.assistant_message else ""}, "finish_reason": "history"})
            return ChatResponse(session_id=request_data.session_id, turn_id="", choices=choices, usage={}, sources=[], metadata={"history": True})
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No user message provided and no session_id to fetch history")

    # Validate incoming user messages
    user_messages = [m for m in request_data.messages if m.role == "user"]
    if not user_messages:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No user message provided")

    user_message = user_messages[-1].content
    session_id = request_data.session_id or str(uuid4())
    turn_id = str(uuid4())

    logger.info("Processing chat message", session_id=session_id, turn_id=turn_id, user_id=request_data.user_id)

    # Obtain AOAI client from app state if available
    from chatbot.app import app_state

    aoai_client = getattr(app_state, "aoai_client", None)
    assistant_response: Optional[str] = None
    usage: Dict[str, int] = {}

    if aoai_client:
        try:
            llm_result = await aoai_client.create_chat_completion([m.model_dump() for m in request_data.messages])
            if llm_result and llm_result.get("choices"):
                assistant_response = llm_result["choices"][0]["message"]["content"]
                usage = llm_result.get("usage", {}) or {}
            else:
                assistant_response = "[Error: No response from language model.]"
        except Exception as e:
            logger.error("LLM call failed", error=str(e))
            assistant_response = f"[Error: LLM call failed: {e}]"
    else:
        assistant_response = "[AOAI client not configured]"

    # Persist conversation turn (best-effort)
    try:
        user_msg = Message(id=f"{turn_id}_user", role=MessageRole.USER, content=user_message, timestamp=datetime.utcnow(), user_id=user_context.user_id)
        assistant_msg = Message(id=f"{turn_id}_assistant", role=MessageRole.ASSISTANT, content=assistant_response or "", timestamp=datetime.utcnow())
        await unified_service.add_conversation_turn(
            chat_id=session_id,
            user_message=user_msg,
            assistant_message=assistant_msg,
            rbac_context=user_context,
            execution_metadata={"turn_id": turn_id},
        )
    except Exception:
        logger.warning("Failed to persist conversation turn; continuing")

    # If metadata contains feedback, attempt to persist it via unified_service
    try:
        fb = request_data.metadata.get("feedback") if request_data.metadata else None
        if fb:
            # expected feedback shape: {"rating": int, "comment": str}
            rating = int(fb.get("rating")) if fb.get("rating") is not None else None
            comment = fb.get("comment") if fb.get("comment") is not None else None
            if rating is not None:
                await unified_service.submit_feedback(turn_id=turn_id, user_id=user_context.user_id, rating=rating, comment=comment, metadata={k: v for k, v in request_data.metadata.items() if k != "feedback"})
    except Exception:
        logger.warning("Failed to persist feedback; continuing")

    # Fallback usage calculation when AOAI doesn't return usage
    if not usage:
        prompt_tokens = len(user_message.split())
        completion_tokens = len((assistant_response or "").split())
        usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }

    choices = [
        {"index": 0, "message": {"role": "assistant", "content": assistant_response}, "finish_reason": "stop"}
    ]

    return ChatResponse(session_id=session_id, turn_id=turn_id, choices=choices, usage=usage, sources=[], metadata={"mode": "direct_answer"})
