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
from pydantic import BaseModel, Field

from chatbot.models.message import ChatHistory, ConversationTurn, Message, MessageRole
from chatbot.models.user import User
from chatbot.models.rbac import RBACContext
from chatbot.models.result import FeedbackData
from chatbot.services.rbac_service import RBACService
from chatbot.services.planner_service import PlannerService
from chatbot.services.history_service import HistoryService
from chatbot.services.feedback_service import FeedbackService
from chatbot.repositories.chat_history_repository import ChatHistoryRepository
from chatbot.clients.aoai_client import AzureOpenAIClient
from chatbot.config.settings import settings

logger = structlog.get_logger(__name__)

router = APIRouter()
security = HTTPBearer()


# Request/Response models
class ChatRequest(BaseModel):
    """Chat message request."""
    
    message: str = Field(..., description="User message text")
    chat_id: Optional[str] = Field(default=None, description="Chat session ID")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Optional metadata")


class ChatResponse(BaseModel):
    """Chat message response."""
    
    chat_id: str = Field(..., description="Chat session ID")
    turn_id: str = Field(..., description="Conversation turn ID")
    message: str = Field(..., description="Assistant response")
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
    credentials: HTTPAuthorizationCredentials = Depends(security),
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
        # TODO: Implement actual JWT validation
        # For now, create a mock user context
        mock_claims = {
            "oid": "user123",
            "email": "user@example.com",
            "name": "Test User",
            "tid": "tenant123",
            "roles": ["sales_rep"],
        }
        
        # Get RBAC service from app
        from chatbot.app import app_state
        rbac_service = app_state.rbac_service
        
        if rbac_service:
            return await rbac_service.create_rbac_context_from_jwt(mock_claims)
        else:
            # Fallback for testing
            from chatbot.models.rbac import RBACContext, AccessScope
            return RBACContext(
                user_id="user@example.com",
                email="user@example.com",
                tenant_id="tenant123",
                object_id="user123",
                roles=["sales_rep"],
                access_scope=AccessScope(),
            )
        
    except Exception as e:
        logger.error("Failed to authenticate user", error=str(e))
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
    user_context: RBACContext = Depends(get_current_user),
    planner_service: PlannerService = Depends(get_planner_service),
    history_service: HistoryService = Depends(get_history_service),
) -> ChatResponse:
    """
    Send a message and get AI response using Semantic Kernel planner.
    
    Args:
        request_data: Chat message request
        user_context: Authenticated user context
        planner_service: Planner service for orchestration
        history_service: History service for conversation management
        
    Returns:
        AI response with sources and metadata
    """
    try:
        # Generate IDs
        chat_id = request_data.chat_id or str(uuid4())
        turn_id = str(uuid4())
        
        logger.info(
            "Processing chat message",
            chat_id=chat_id,
            turn_id=turn_id,
            user_id=user_context.user_id,
            message_length=len(request_data.message),
        )
        
        # Get conversation history for context
        conversation_context = await history_service.get_conversation_context(
            chat_id, user_context, max_turns=5
        )
        
        # Create a plan using the planner service
        plan_result = await planner_service.create_plan(
            goal=request_data.message,
            rbac_context=user_context,
            conversation_context=conversation_context,
        )
        
        if not plan_result["success"]:
            logger.warning(
                "Failed to create plan",
                chat_id=chat_id,
                error=plan_result.get("error"),
            )
            
            # Fallback to simple response
            assistant_response = "I apologize, but I'm having trouble processing your request right now. Please try rephrasing your question or contact support if the issue persists."
            sources = []
            metadata = {"error": plan_result.get("error"), "fallback_used": True}
        else:
            # Execute the plan
            execution_result = await planner_service.execute_plan(
                plan_result["plan"],
                user_context,
                conversation_context,
            )
            
            if execution_result["success"]:
                assistant_response = execution_result["final_answer"]
                sources = execution_result.get("sources", [])
                metadata = {
                    "plan_steps": len(plan_result["plan"].steps),
                    "execution_time_ms": execution_result.get("execution_time_ms", 0),
                    "agents_used": execution_result.get("agents_used", []),
                    "function_calls": execution_result.get("function_calls", 0),
                }
            else:
                logger.warning(
                    "Plan execution failed",
                    chat_id=chat_id,
                    error=execution_result.get("error"),
                )
                assistant_response = "I encountered an issue while processing your request. Please try again or rephrase your question."
                sources = []
                metadata = {"execution_error": execution_result.get("error")}
        
        # Save the conversation turn
        turn_data = {
            "turn_id": turn_id,
            "user_message": request_data.message,
            "assistant_message": assistant_response,
            "sources": sources,
            "metadata": {
                **metadata,
                "timestamp": datetime.utcnow().isoformat(),
                "user_id": user_context.user_id,
            },
        }
        
        await history_service.save_conversation_turn(
            chat_id, user_context, turn_data
        )
        
        logger.info(
            "Chat message processed successfully",
            chat_id=chat_id,
            turn_id=turn_id,
            response_length=len(assistant_response),
            sources_count=len(sources),
        )
        
        return ChatResponse(
            chat_id=chat_id,
            turn_id=turn_id,
            message=assistant_response,
            sources=sources,
            metadata=metadata,
        )
        
    except Exception as e:
        logger.error(
            "Failed to process chat message",
            chat_id=request_data.chat_id,
            user_id=user_context.user_id,
            error=str(e),
        )
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
