"""
History service for conversation management and context retrieval.

This service manages chat history persistence, retrieval for planner context,
and storage of tool calls and plans for observability.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from uuid import uuid4
import structlog

from chatbot.repositories.chat_history_repository import ChatHistoryRepository
from chatbot.models.message import ChatHistory, ConversationTurn, Message, MessageRole
from chatbot.models.rbac import RBACContext
from chatbot.models.plan import Plan

logger = structlog.get_logger(__name__)


class HistoryService:
    """Service for managing conversation history and context."""
    
    def __init__(self, chat_repository: ChatHistoryRepository):
        """
        Initialize the history service.
        
        Args:
            chat_repository: Repository for chat history persistence
        """
        self.chat_repository = chat_repository
    
    async def create_chat_session(
        self,
        rbac_context: RBACContext,
        title: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ChatHistory:
        """
        Create a new chat session.
        
        Args:
            rbac_context: User's RBAC context
            title: Optional chat title
            metadata: Optional session metadata
            
        Returns:
            Created chat history
        """
        try:
            chat_history = await self.chat_repository.create_chat_session(
                user_id=rbac_context.user_id,
                chat_id=str(uuid4()),
                title=title,
                metadata=metadata
            )
            
            logger.info(
                "Chat session created",
                chat_id=chat_history.chat_id,
                user_id=rbac_context.user_id,
                title=title
            )
            
            return chat_history
            
        except Exception as e:
            logger.error(
                "Failed to create chat session",
                user_id=rbac_context.user_id,
                error=str(e)
            )
            raise
    
    async def add_conversation_turn(
        self,
        chat_id: str,
        user_message: Message,
        assistant_message: Message,
        rbac_context: RBACContext,
        plan: Optional[Plan] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        execution_metadata: Optional[Dict[str, Any]] = None
    ) -> ConversationTurn:
        """
        Add a conversation turn to chat history.
        
        Args:
            chat_id: Chat session ID
            user_message: User's message
            assistant_message: Assistant's response
            rbac_context: User's RBAC context
            plan: Optional execution plan used
            tool_calls: Optional list of tool calls made
            execution_metadata: Optional execution metadata
            
        Returns:
            Created conversation turn
        """
        try:
            turn = await self.chat_repository.add_conversation_turn(
                chat_id=chat_id,
                user_message=user_message,
                assistant_message=assistant_message,
                user_id=rbac_context.user_id,
                plan=plan,
                tool_calls=tool_calls,
                execution_metadata=execution_metadata
            )
            
            logger.info(
                "Conversation turn added",
                chat_id=chat_id,
                turn_id=turn.turn_id,
                user_id=rbac_context.user_id,
                has_plan=bool(plan),
                tool_calls_count=len(tool_calls) if tool_calls else 0
            )
            
            return turn
            
        except Exception as e:
            logger.error(
                "Failed to add conversation turn",
                chat_id=chat_id,
                user_id=rbac_context.user_id,
                error=str(e)
            )
            raise
    
    async def get_chat_context(
        self,
        chat_id: str,
        rbac_context: RBACContext,
        max_turns: int = 10
    ) -> List[ConversationTurn]:
        """
        Get recent conversation context for planner.
        
        Args:
            chat_id: Chat session ID
            rbac_context: User's RBAC context
            max_turns: Maximum number of turns to retrieve
            
        Returns:
            List of recent conversation turns
        """
        try:
            chat_history = await self.chat_repository.get_chat_history(
                chat_id, rbac_context.user_id
            )
            
            if not chat_history:
                logger.warning(
                    "Chat history not found",
                    chat_id=chat_id,
                    user_id=rbac_context.user_id
                )
                return []
            
            # Get recent turns for context
            recent_turns = chat_history.turns[-max_turns:] if chat_history.turns else []
            
            logger.debug(
                "Retrieved chat context",
                chat_id=chat_id,
                user_id=rbac_context.user_id,
                turns_retrieved=len(recent_turns)
            )
            
            return recent_turns
            
        except Exception as e:
            logger.error(
                "Failed to get chat context",
                chat_id=chat_id,
                user_id=rbac_context.user_id,
                error=str(e)
            )
            raise
    
    async def get_conversation_summary(
        self,
        chat_id: str,
        rbac_context: RBACContext
    ) -> Dict[str, Any]:
        """
        Get conversation summary and metadata.
        
        Args:
            chat_id: Chat session ID
            rbac_context: User's RBAC context
            
        Returns:
            Conversation summary with metadata
        """
        try:
            chat_history = await self.chat_repository.get_chat_history(
                chat_id, rbac_context.user_id
            )
            
            if not chat_history:
                return {}
            
            # Calculate summary statistics
            turn_count = len(chat_history.turns)
            total_messages = sum(2 for _ in chat_history.turns)  # User + Assistant per turn
            
            # Extract topics and entities (simplified)
            topics = self._extract_topics(chat_history.turns)
            entities = self._extract_entities(chat_history.turns)
            
            # Calculate conversation duration
            duration_minutes = 0
            if chat_history.turns:
                start_time = chat_history.created_at
                end_time = chat_history.turns[-1].timestamp
                duration_minutes = (end_time - start_time).total_seconds() / 60
            
            summary = {
                "chat_id": chat_id,
                "title": chat_history.title,
                "turn_count": turn_count,
                "total_messages": total_messages,
                "duration_minutes": round(duration_minutes, 2),
                "topics": topics,
                "entities": entities,
                "created_at": chat_history.created_at.isoformat(),
                "updated_at": chat_history.updated_at.isoformat(),
                "metadata": chat_history.metadata
            }
            
            logger.debug(
                "Generated conversation summary",
                chat_id=chat_id,
                user_id=rbac_context.user_id,
                turn_count=turn_count
            )
            
            return summary
            
        except Exception as e:
            logger.error(
                "Failed to get conversation summary",
                chat_id=chat_id,
                user_id=rbac_context.user_id,
                error=str(e)
            )
            raise
    
    async def search_conversation_history(
        self,
        rbac_context: RBACContext,
        query: str,
        limit: int = 20,
        days_back: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Search through conversation history.
        
        Args:
            rbac_context: User's RBAC context
            query: Search query
            limit: Maximum results to return
            days_back: Number of days to search back
            
        Returns:
            List of matching conversation snippets
        """
        try:
            # Get date range
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=days_back)
            
            # Get user's chat sessions
            chat_sessions = await self.chat_repository.get_user_chat_sessions(
                rbac_context.user_id, limit=100
            )
            
            # Search through conversations
            matches = []
            query_lower = query.lower()
            
            for session in chat_sessions:
                if session.created_at < start_date:
                    continue
                
                # Get full chat history
                chat_history = await self.chat_repository.get_chat_history(
                    session.chat_id, rbac_context.user_id
                )
                
                if not chat_history:
                    continue
                
                # Search through turns
                for turn in chat_history.turns:
                    # Check user message
                    if query_lower in turn.user_message.content.lower():
                        matches.append({
                            "chat_id": chat_history.chat_id,
                            "turn_id": turn.turn_id,
                            "timestamp": turn.timestamp.isoformat(),
                            "message_type": "user",
                            "content": turn.user_message.content,
                            "context": self._get_turn_context(chat_history.turns, turn)
                        })
                    
                    # Check assistant message
                    if query_lower in turn.assistant_message.content.lower():
                        matches.append({
                            "chat_id": chat_history.chat_id,
                            "turn_id": turn.turn_id,
                            "timestamp": turn.timestamp.isoformat(),
                            "message_type": "assistant",
                            "content": turn.assistant_message.content,
                            "context": self._get_turn_context(chat_history.turns, turn)
                        })
                    
                    if len(matches) >= limit:
                        break
                
                if len(matches) >= limit:
                    break
            
            # Sort by relevance/recency
            matches.sort(key=lambda x: x["timestamp"], reverse=True)
            
            logger.info(
                "Conversation search completed",
                user_id=rbac_context.user_id,
                query=query,
                matches_found=len(matches)
            )
            
            return matches[:limit]
            
        except Exception as e:
            logger.error(
                "Failed to search conversation history",
                user_id=rbac_context.user_id,
                query=query,
                error=str(e)
            )
            raise
    
    async def delete_chat_session(
        self,
        chat_id: str,
        rbac_context: RBACContext
    ) -> bool:
        """
        Delete a chat session and all its turns.
        
        Args:
            chat_id: Chat session ID to delete
            rbac_context: User's RBAC context
            
        Returns:
            True if deleted successfully
        """
        try:
            # Verify ownership
            chat_history = await self.chat_repository.get_chat_history(
                chat_id, rbac_context.user_id
            )
            
            if not chat_history:
                logger.warning(
                    "Chat session not found for deletion",
                    chat_id=chat_id,
                    user_id=rbac_context.user_id
                )
                return False
            
            # Delete the session
            success = await self.chat_repository.delete_chat_session(
                chat_id, rbac_context.user_id
            )
            
            if success:
                logger.info(
                    "Chat session deleted",
                    chat_id=chat_id,
                    user_id=rbac_context.user_id
                )
            
            return success
            
        except Exception as e:
            logger.error(
                "Failed to delete chat session",
                chat_id=chat_id,
                user_id=rbac_context.user_id,
                error=str(e)
            )
            raise
    
    def _extract_topics(self, turns: List[ConversationTurn]) -> List[str]:
        """
        Extract topics from conversation turns.
        
        Args:
            turns: List of conversation turns
            
        Returns:
            List of extracted topics
        """
        # Simplified topic extraction
        # In a real implementation, this would use NLP techniques
        topics = set()
        common_business_terms = {
            "sales", "revenue", "account", "customer", "opportunity",
            "forecast", "pipeline", "quota", "territory", "lead"
        }
        
        for turn in turns:
            words = turn.user_message.content.lower().split()
            for word in words:
                if word in common_business_terms:
                    topics.add(word)
        
        return list(topics)[:10]  # Limit to top 10 topics
    
    def _extract_entities(self, turns: List[ConversationTurn]) -> List[str]:
        """
        Extract entities from conversation turns.
        
        Args:
            turns: List of conversation turns
            
        Returns:
            List of extracted entities
        """
        # Simplified entity extraction
        # In a real implementation, this would use NER models
        entities = set()
        
        for turn in turns:
            # Look for potential company names (capitalized words)
            words = turn.user_message.content.split()
            for word in words:
                if word.istitle() and len(word) > 2:
                    entities.add(word)
        
        return list(entities)[:20]  # Limit to top 20 entities
    
    def _get_turn_context(
        self,
        all_turns: List[ConversationTurn],
        target_turn: ConversationTurn
    ) -> str:
        """
        Get context around a specific turn.
        
        Args:
            all_turns: All conversation turns
            target_turn: Target turn to get context for
            
        Returns:
            Context string
        """
        try:
            # Find the target turn index
            target_index = -1
            for i, turn in enumerate(all_turns):
                if turn.turn_id == target_turn.turn_id:
                    target_index = i
                    break
            
            if target_index == -1:
                return ""
            
            # Get surrounding context (1 turn before and after)
            context_parts = []
            
            if target_index > 0:
                prev_turn = all_turns[target_index - 1]
                context_parts.append(f"Previous: {prev_turn.user_message.content[:100]}...")
            
            if target_index < len(all_turns) - 1:
                next_turn = all_turns[target_index + 1]
                context_parts.append(f"Next: {next_turn.user_message.content[:100]}...")
            
            return " | ".join(context_parts)
            
        except Exception:
            return ""
