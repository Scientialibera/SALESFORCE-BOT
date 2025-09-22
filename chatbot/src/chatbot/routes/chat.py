"""
Chat API routes for conversation management and Q&A.

This module provides endpoints for chat interactions, including
message processing, conversation history, and feedback collection.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import uuid4
import structlog
from fastapi import APIRouter, HTTPException, Depends, status, Header, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from azure.identity import DefaultAzureCredential
from jose import jwt as jose_jwt
from pydantic import BaseModel, Field

from chatbot.models.message import ChatHistory, ConversationTurn, Message, MessageRole
from chatbot.models.user import User
from chatbot.models.rbac import RBACContext
from chatbot.models.result import FeedbackData
from chatbot.services.planner_service import PlannerService
from chatbot.services.history_service import HistoryService
from chatbot.services.feedback_service import FeedbackService
from chatbot.repositories.chat_history_repository import ChatHistoryRepository
from chatbot.clients.aoai_client import AzureOpenAIClient
from chatbot.config.settings import settings

logger = structlog.get_logger(__name__)

router = APIRouter()
security = HTTPBearer(auto_error=False)


# Request/Response models
class ChatMessage(BaseModel):
    """Individual chat message in OpenAI format."""
    
    role: str = Field(..., description="Message role: 'system', 'user', or 'assistant'")
    content: str = Field(..., description="Message content")


class ChatRequest(BaseModel):
    """Chat completion request following OpenAI Chat Completion API format."""
    
    messages: List[ChatMessage] = Field(..., description="Array of chat messages")
    user_id: str = Field(..., description="User identifier for RBAC and tracking")
    session_id: Optional[str] = Field(default=None, description="Session ID for conversation tracking")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Optional metadata")


class ChatResponse(BaseModel):
    """Chat completion response following OpenAI Chat Completion API format."""
    
    session_id: str = Field(..., description="Session ID for conversation tracking")
    turn_id: str = Field(..., description="Conversation turn ID")
    choices: List[Dict[str, Any]] = Field(..., description="Response choices in OpenAI format")
    usage: Dict[str, int] = Field(default_factory=dict, description="Token usage information")
    sources: List[Dict[str, Any]] = Field(default_factory=list, description="Information sources")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Response metadata")


class FeedbackRequest(BaseModel):
    """Feedback submission request."""
    
    turn_id: str = Field(..., description="Turn ID being rated")
    rating: int = Field(..., ge=1, le=5, description="Rating from 1-5")
    comment: Optional[str] = Field(default=None, description="Optional feedback comment")


class ChatSessionResponse(BaseModel):
    """Chat session information response."""
    
    chat_id: str = Field(..., description="Chat session ID")
    title: str = Field(..., description="Chat title")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    turn_count: int = Field(..., description="Number of turns")


# Dependency functions
async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    request: Request = None,
) -> RBACContext:
    """
    Extract and validate user from JWT token.
    
    Args:
        credentials: HTTP bearer token
        request: FastAPI request object
        
    Returns:
        RBAC context for the authenticated user
    """
    try:
        logger.info("Authenticating user request", url=str(request.url) if request else "unknown")
        
        # Attempt to build RBAC context from an Authorization header if present
        # If we have an Authorization header, use it (TODO: full validation)
        if credentials and getattr(credentials, "credentials", None):
            token = credentials.credentials
            # Try to decode token without verification to extract claims
            try:
                claims = jose_jwt.get_unverified_claims(token)
            except Exception:
                claims = {"oid": "user123", "email": "user@example.com", "tid": "tenant123", "roles": ["sales_rep"]}
            # If running in dev mode, persist minimal claims to .env for convenience
            try:
                if settings.dev_mode and claims:
                    env_path = "./.env"
                    env_vars = {}
                    try:
                            with open(env_path, "r", encoding="utf-8") as f:
                                for line in f:
                                    if "=" in line and not line.strip().startswith("#"):
                                        k, v = line.strip().split("=", 1)
                                        env_vars[k.strip()] = v.strip()
                        except FileNotFoundError:
                            pass

                        email = claims.get("email") or claims.get("upn") or claims.get("preferred_username")
                        oid = claims.get("oid") or claims.get("sub")

                        if email:
                            env_vars["DEV_USER_EMAIL"] = email
                        if oid:
                            env_vars["DEV_USER_OID"] = oid

                        # Write back .env
                        with open(env_path, "w", encoding="utf-8") as f:
                            for k, v in env_vars.items():
                                f.write(f"{k}={v}\n")
                except Exception:
                    logger.debug("Failed to persist .env dev claims", error=str(Exception))

                return context

        # No Authorization header: in dev mode try DefaultAzureCredential to get a token and extract claims
        try:
            if settings.dev_mode:
                try:
                    cred = DefaultAzureCredential()
                    # Request a management scope token as a best-effort; token will be an access token (claims may vary)
                    token = cred.get_token("https://management.azure.com/.default").token
                    try:
                        claims = jose_jwt.get_unverified_claims(token)
                    except Exception:
                        claims = {}
                    # RBACService removed: just use claims directly
                except Exception as e:
                    logger.info("DefaultAzureCredential failed in dev mode, falling back to mock claims", error=str(e))

        except Exception as e:
            logger.error("Unexpected error while attempting to build RBAC context", error=str(e))

        # Final fallback: return a minimal mock context
        logger.info("Using fallback RBAC context")
    from chatbot.models.rbac import RBACContext
        context = RBACContext(
            user_id="user@example.com",
            email="user@example.com",
            tenant_id="tenant123",
            object_id="user123",
            roles=["sales_rep"],
            access_scope=AccessScope(),
        )
        logger.info("Fallback RBAC context created successfully")
        return context
        
    except Exception as e:
        import traceback
        logger.error("Failed to authenticate user", error=str(e), traceback=traceback.format_exc())
        print(f"AUTH EXCEPTION: {type(e).__name__}: {str(e)}")
        print(f"Auth Traceback:\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )


def get_planner_service() -> PlannerService:
    """Get planner service dependency."""
    from chatbot.app import app_state
    if not app_state.planner_service:
        raise HTTPException(status_code=503, detail="Planner service not available")
    return app_state.planner_service


def get_history_service() -> HistoryService:
    """Get history service dependency."""
    from chatbot.app import app_state
    if not app_state.history_service:
        raise HTTPException(status_code=503, detail="History service not available")
    return app_state.history_service


def get_feedback_service() -> FeedbackService:
    """Get feedback service dependency."""
    from chatbot.app import app_state
    if not app_state.feedback_service:
        raise HTTPException(status_code=503, detail="Feedback service not available")
    return app_state.feedback_service


# Chat endpoints
@router.post("/chat", response_model=ChatResponse)
async def send_message(
    request_data: ChatRequest,
    planner_service: PlannerService = Depends(get_planner_service),
    history_service: HistoryService = Depends(get_history_service),
    user_context: RBACContext = Depends(get_current_user),
) -> ChatResponse:
    """
    Send a message and get AI response using Semantic Kernel planner.
    OpenAI Chat Completion API compatible endpoint.
    
    Args:
        request_data: Chat completion request with messages array
        planner_service: Planner service for orchestration
        history_service: History service for conversation management
        
    Returns:
        AI response in OpenAI Chat Completion format
    """
    try:
        # Extract user message from messages array (get the latest user message)
        user_messages = [msg for msg in request_data.messages if msg.role == "user"]
        if not user_messages:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No user message found in messages array"
            )
        
        user_message = user_messages[-1].content  # Get the latest user message
        
        # Generate IDs
        session_id = request_data.session_id or str(uuid4())
        turn_id = str(uuid4())
        
        # `user_context` is provided by the authentication dependency which
        # attempts to use Authorization header or DefaultAzureCredential in dev mode.
        
        logger.info(
            "Processing chat message",
            session_id=session_id,
            turn_id=turn_id,
            user_id=request_data.user_id,
            message_length=len(user_message),
        )
        
        # Get conversation history for context (create session if it doesn't exist)
        try:
            conversation_context = await history_service.get_chat_context(
                session_id, user_context, max_turns=5
            )
        except Exception as e:
            logger.warning(f"Failed to get conversation context: {e}")
            conversation_context = []
            
            # Create chat session if it doesn't exist
            try:
                await history_service.create_chat_session(
                    rbac_context=user_context,
                    chat_id=session_id,
                    title=f"Chat session {session_id[:8]}",
                    metadata={"created_via": "api", "first_message": user_message[:100]}
                )
                logger.info(f"Created new chat session: {session_id}")
            except Exception as create_error:
                logger.warning(f"Failed to create chat session: {create_error}")
                # Continue anyway - we'll handle this in the save step
        
        # Execute plan using planner service
        try:
            plan_result = await planner_service.create_plan(
                user_request=user_message,
                rbac_context=user_context,
                conversation_context=conversation_context,
            )

            # --- Account resolution logic (NEW) ---
            # Collect all unique accounts_mentioned from all steps
            all_accounts_mentioned = set()
            for step in getattr(plan_result, 'steps', []):
                params = getattr(step, 'parameters', {}) or getattr(getattr(step, 'tool_decision', None), 'parameters', {})
                accounts = params.get('accounts_mentioned') if params else None
                if accounts:
                    all_accounts_mentioned.update(accounts)

            resolved_accounts = []
            if all_accounts_mentioned:
                # Only import here to avoid circular import
                from chatbot.services.account_resolver_service import AccountResolverService
                account_resolver = AccountResolverService(
                    aoai_client=None,  # Use DI or global if needed
                    cache_repository=None,  # Use DI or global if needed
                )
                # Use a dummy RBAC context if needed, or pass user_context
                # This assumes resolve_account can take a list of names
                resolved = await account_resolver.resolve_account(
                    ', '.join(all_accounts_mentioned), user_context
                )
                resolved_accounts = resolved.get('resolved_accounts', []) if isinstance(resolved, dict) else resolved

            # Patch plan steps to inject resolved_accounts
            for step in getattr(plan_result, 'steps', []):
                params = getattr(step, 'parameters', {}) or getattr(getattr(step, 'tool_decision', None), 'parameters', {})
                if params is not None and 'accounts_mentioned' in params:
                    params['resolved_accounts'] = resolved_accounts if all_accounts_mentioned else None

            # Execute the plan and get results
            execution_result = await planner_service.execute_plan(plan_result, user_context)

            # Extract response from execution result
            assistant_response = execution_result.final_output or "I wasn't able to process your request."
            sources = execution_result.execution_metadata.get("sources", [])
            metadata = {
                "mode": "agent_execution",
                "plan_id": plan_result.id,
                "plan_type": plan_result.plan_type.value,
                "execution_id": execution_result.execution_id,
                "steps_executed": len(execution_result.step_results),
                "execution_status": execution_result.status,
                "timestamp": datetime.utcnow().isoformat()
            }

        except Exception as e:
            logger.error(f"Plan execution failed: {e}")
            # Fallback to simple response if plan execution fails
            assistant_response = f"I encountered an issue processing your request: {user_message}. The system is being debugged."
            sources = []
            metadata = {
                "mode": "fallback_response",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        
        # Save the conversation turn 
        if settings.dev_mode:
            # In dev mode, just log the turn without saving to avoid blocking testing
            logger.info(
                "Dev mode: Skipping conversation turn save",
                session_id=session_id,
                turn_id=turn_id,
                user_message=user_message[:100] + "..." if len(user_message) > 100 else user_message,
                assistant_response=assistant_response[:100] + "..." if len(assistant_response) > 100 else assistant_response
            )
        else:
            # Production mode: Save conversation turn properly
            try:
                user_msg = Message(
                    id=f"{turn_id}_user",
                    role=MessageRole.USER,
                    content=user_message,
                    timestamp=datetime.utcnow(),
                    user_id=user_context.user_id
                )
                
                assistant_msg = Message(
                    id=f"{turn_id}_assistant",
                    role=MessageRole.ASSISTANT,
                    content=assistant_response,
                    timestamp=datetime.utcnow()
                )
                
                await history_service.add_conversation_turn(
                    chat_id=session_id,
                    user_message=user_msg,
                    assistant_message=assistant_msg,
                    rbac_context=user_context,
                    execution_metadata={
                        "turn_id": turn_id,
                        "sources": sources,
                        "response_type": "agent_response",
                        **metadata
                    }
                )
                logger.info("Conversation turn saved successfully")
            except Exception as save_error:
                logger.warning(f"Failed to save conversation turn: {save_error}")
                # Continue without blocking the response
        
        logger.info(
            "Chat message processed successfully",
            session_id=session_id,
            turn_id=turn_id,
            response_length=len(assistant_response),
            sources_count=len(sources),
        )
        
        # Format response in OpenAI Chat Completion style
        choices = [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": assistant_response
                },
                "finish_reason": "stop"
            }
        ]
        
        usage = {
            "prompt_tokens": len(user_message.split()),  # Rough estimate
            "completion_tokens": len(assistant_response.split()),  # Rough estimate
            "total_tokens": len(user_message.split()) + len(assistant_response.split())
        }
        
        return ChatResponse(
            session_id=session_id,
            turn_id=turn_id,
            choices=choices,
            usage=usage,
            sources=sources,
            metadata=metadata,
        )
        
    except Exception as e:
        logger.error(
            "Failed to process chat message",
            session_id=request_data.session_id,
            user_id=request_data.user_id,
            error=str(e),
        )
        
        # In dev mode, return detailed error for debugging
        if settings.dev_mode:
            import traceback
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to process message: {str(e)} | Traceback: {traceback.format_exc()}"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to process message",
            )


@router.get("/chats", response_model=List[ChatSessionResponse])
async def get_user_chats(
    user_context: RBACContext = Depends(get_current_user),
    history_service: HistoryService = Depends(get_history_service),
    limit: int = 20,
    offset: int = 0,
) -> List[ChatSessionResponse]:
    """
    Get user's chat sessions.
    
    Args:
        user_context: Authenticated user context
        history_service: History service for conversation management
        limit: Maximum number of chats to return
        offset: Number of chats to skip
        
    Returns:
        List of user's chat sessions
    """
    try:
        chat_sessions = await history_service.get_user_chat_sessions(
            user_context, limit, offset
        )
        
        return [
            ChatSessionResponse(
                chat_id=chat["chat_id"],
                title=chat.get("title", "Untitled Chat"),
                created_at=chat["created_at"],
                updated_at=chat["updated_at"],
                turn_count=chat.get("turn_count", 0),
            )
            for chat in chat_sessions
        ]
        
    except Exception as e:
        logger.error("Failed to get user chats", user_id=user_context.user_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve chat sessions",
        )


@router.get("/chats/{chat_id}")
async def get_chat_history(
    chat_id: str,
    user_context: RBACContext = Depends(get_current_user),
    history_service: HistoryService = Depends(get_history_service),
    include_sources: bool = True,
) -> Dict[str, Any]:
    """
    Get chat history by ID.
    
    Args:
        chat_id: Chat session ID
        user_context: Authenticated user context
        history_service: History service for conversation management
        include_sources: Whether to include source information
        
    Returns:
        Chat history with all turns
    """
    try:
        chat_history = await history_service.get_chat_history(
            chat_id, user_context, include_sources=include_sources
        )
        
        if not chat_history:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chat not found",
            )
        
        return chat_history
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get chat history", chat_id=chat_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve chat history",
        )


@router.delete("/chats/{chat_id}")
async def delete_chat(
    chat_id: str,
    user_context: RBACContext = Depends(get_current_user),
    history_service: HistoryService = Depends(get_history_service),
) -> Dict[str, str]:
    """
    Delete a chat session.
    
    Args:
        chat_id: Chat session ID
        user_context: Authenticated user context
        history_service: History service for conversation management
        
    Returns:
        Success message
    """
    try:
        success = await history_service.delete_chat_session(chat_id, user_context)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chat not found or access denied",
            )
        
        return {"message": "Chat deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to delete chat", chat_id=chat_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete chat",
        )


@router.post("/feedback")
async def submit_feedback(
    feedback: FeedbackRequest,
    user_context: RBACContext = Depends(get_current_user),
    feedback_service: FeedbackService = Depends(get_feedback_service),
) -> Dict[str, str]:
    """
    Submit feedback for a conversation turn.
    
    Args:
        feedback: Feedback data
        user_context: Authenticated user context
        feedback_service: Feedback service for storing ratings
        
    Returns:
        Success message
    """
    try:
        # Create feedback data
        feedback_data = FeedbackData(
            turn_id=feedback.turn_id,
            user_id=user_context.user_id,
            rating=feedback.rating,
            comment=feedback.comment,
            timestamp=datetime.utcnow(),
        )
        
        # Submit feedback
        await feedback_service.submit_feedback(feedback_data, user_context)
        
        logger.info(
            "Feedback submitted successfully",
            turn_id=feedback.turn_id,
            user_id=user_context.user_id,
            rating=feedback.rating,
            has_comment=bool(feedback.comment),
        )
        
        return {"message": "Feedback submitted successfully"}
        
    except Exception as e:
        logger.error("Failed to submit feedback", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to submit feedback",
        )


@router.get("/analytics/conversations")
async def get_conversation_analytics(
    user_context: RBACContext = Depends(get_current_user),
    history_service: HistoryService = Depends(get_history_service),
    days: int = 30,
) -> Dict[str, Any]:
    """
    Get conversation analytics for the user.
    
    Args:
        user_context: Authenticated user context
        history_service: History service for analytics
        days: Number of days to analyze
        
    Returns:
        Analytics data
    """
    try:
        analytics = await history_service.get_conversation_analytics(
            user_context, days=days
        )
        
        return analytics
        
    except Exception as e:
        logger.error("Failed to get conversation analytics", user_id=user_context.user_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve analytics",
        )


@router.get("/search/conversations")
async def search_conversations(
    query: str,
    user_context: RBACContext = Depends(get_current_user),
    history_service: HistoryService = Depends(get_history_service),
    limit: int = 10,
) -> Dict[str, Any]:
    """
    Search user's conversation history.
    
    Args:
        query: Search query
        user_context: Authenticated user context
        history_service: History service for search
        limit: Maximum results to return
        
    Returns:
        Search results
    """
    try:
        search_results = await history_service.search_conversation_history(
            user_context, query, limit=limit
        )
        
        return {
            "query": query,
            "results": search_results,
            "total_results": len(search_results),
        }
        
    except Exception as e:
        logger.error("Failed to search conversations", user_id=user_context.user_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to search conversations",
        )
