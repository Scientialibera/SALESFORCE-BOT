"""
Chat history repository for conversation management.

This module provides repository pattern for managing chat history
and conversation turns in Cosmos DB.
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from uuid import uuid4
import structlog

from chatbot.clients.cosmos_client import CosmosDBClient
from chatbot.models.message import ChatHistory, ConversationTurn, Message
from chatbot.config.settings import CosmosDBSettings

logger = structlog.get_logger(__name__)


class ChatHistoryRepository:
    """
    Repository for managing chat history and conversation turns.
    
    This repository handles:
    - Chat session management
    - Conversation turn storage and retrieval
    - History cleanup and archival
    - User-based filtering
    """
    
    def __init__(self, cosmos_client: CosmosDBClient, settings: CosmosDBSettings):
        """
        Initialize the chat history repository.
        
        Args:
            cosmos_client: Cosmos DB client instance
            settings: Cosmos DB settings
        """
        self.client = cosmos_client
        self.container_name = settings.chat_container
        self.settings = settings
        
        logger.info("Initialized chat history repository", container=self.container_name)
    
    async def create_chat_session(
        self,
        user_id: str,
        title: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> ChatHistory:
        """
        Create a new chat session.
        
        Args:
            user_id: User ID for the chat
            title: Optional chat title
            chat_id: Optional chat ID (generated if not provided)
            
        Returns:
            Created chat history
        """
        chat_id = chat_id or str(uuid4())
        
        chat_history = ChatHistory(
            chat_id=chat_id,
            user_id=user_id,
            title=title or f"Chat {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
        )
        
        # Store in Cosmos DB
        chat_doc = {
            "id": chat_id,
            "user_id": user_id,
            "chat_data": chat_history.model_dump(),
            "doc_type": "chat_session",
            "created_at": chat_history.created_at.isoformat(),
            "updated_at": chat_history.updated_at.isoformat(),
        }
        
        await self.client.create_item(self.container_name, chat_doc)
        
        logger.info(
            "Created chat session",
            chat_id=chat_id,
            user_id=user_id,
            title=title,
        )
        
        return chat_history
    
    async def get_chat_history(self, chat_id: str, user_id: str) -> Optional[ChatHistory]:
        """
        Get chat history by ID and user.
        
        Args:
            chat_id: Chat session ID
            user_id: User ID for security
            
        Returns:
            Chat history if found and user has access
        """
        try:
            doc = await self.client.read_item(
                container_name=self.container_name,
                item_id=chat_id,
                partition_key_value=user_id,
            )
            
            if doc and doc.get("user_id") == user_id:
                chat_data = doc.get("chat_data", {})
                return ChatHistory(**chat_data)
            
            return None
            
        except Exception as e:
            logger.error("Failed to get chat history", chat_id=chat_id, user_id=user_id, error=str(e))
            return None
    
    async def update_chat_history(self, chat_history: ChatHistory) -> bool:
        """
        Update chat history in storage.
        
        Args:
            chat_history: Chat history to update
            
        Returns:
            True if successful
        """
        try:
            chat_history.updated_at = datetime.utcnow()
            
            chat_doc = {
                "id": chat_history.chat_id,
                "user_id": chat_history.user_id,
                "chat_data": chat_history.model_dump(),
                "doc_type": "chat_session",
                "created_at": chat_history.created_at.isoformat(),
                "updated_at": chat_history.updated_at.isoformat(),
            }
            
            await self.client.upsert_item(self.container_name, chat_doc)
            
            logger.debug(
                "Updated chat history",
                chat_id=chat_history.chat_id,
                user_id=chat_history.user_id,
                turns=chat_history.total_turns,
            )
            
            return True
            
        except Exception as e:
            logger.error(
                "Failed to update chat history",
                chat_id=chat_history.chat_id,
                error=str(e),
            )
            return False
    
    async def add_turn_to_chat(
        self,
        chat_id: str,
        user_id: str,
        turn: ConversationTurn,
    ) -> bool:
        """
        Add a conversation turn to chat history.
        
        Args:
            chat_id: Chat session ID
            user_id: User ID for security
            turn: Conversation turn to add
            
        Returns:
            True if successful
        """
        try:
            # Get current chat history
            chat_history = await self.get_chat_history(chat_id, user_id)
            if not chat_history:
                logger.warning("Chat history not found for turn addition", chat_id=chat_id)
                return False
            
            # Add turn and update
            chat_history.add_turn(turn)
            return await self.update_chat_history(chat_history)
            
        except Exception as e:
            logger.error(
                "Failed to add turn to chat",
                chat_id=chat_id,
                turn_id=turn.id,
                error=str(e),
            )
            return False
    
    async def get_user_chat_sessions(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> List[ChatHistory]:
        """
        Get chat sessions for a user.
        
        Args:
            user_id: User ID to filter by
            limit: Maximum number of sessions to return
            offset: Number of sessions to skip
            
        Returns:
            List of chat sessions
        """
        try:
            query = """
                SELECT * FROM c 
                WHERE c.user_id = @user_id 
                AND c.doc_type = 'chat_session'
                ORDER BY c.updated_at DESC
                OFFSET @offset LIMIT @limit
            """
            
            parameters = [
                {"name": "@user_id", "value": user_id},
                {"name": "@offset", "value": offset},
                {"name": "@limit", "value": limit},
            ]
            
            docs = await self.client.query_items(
                container_name=self.container_name,
                query=query,
                parameters=parameters,
                partition_key_value=user_id,
            )
            
            chat_sessions = []
            for doc in docs:
                chat_data = doc.get("chat_data", {})
                chat_sessions.append(ChatHistory(**chat_data))
            
            logger.debug(
                "Retrieved user chat sessions",
                user_id=user_id,
                count=len(chat_sessions),
                limit=limit,
                offset=offset,
            )
            
            return chat_sessions
            
        except Exception as e:
            logger.error("Failed to get user chat sessions", user_id=user_id, error=str(e))
            return []
    
    async def delete_chat_session(self, chat_id: str, user_id: str) -> bool:
        """
        Delete a chat session.
        
        Args:
            chat_id: Chat session ID
            user_id: User ID for security
            
        Returns:
            True if successful
        """
        try:
            # Verify ownership before deletion
            chat_history = await self.get_chat_history(chat_id, user_id)
            if not chat_history:
                logger.warning("Cannot delete chat: not found or access denied", chat_id=chat_id)
                return False
            
            success = await self.client.delete_item(
                container_name=self.container_name,
                item_id=chat_id,
                partition_key_value=user_id,
            )
            
            if success:
                logger.info("Deleted chat session", chat_id=chat_id, user_id=user_id)
            
            return success
            
        except Exception as e:
            logger.error("Failed to delete chat session", chat_id=chat_id, error=str(e))
            return False
    
    async def cleanup_old_chats(self, retention_days: int = 90) -> int:
        """
        Clean up old chat sessions.
        
        Args:
            retention_days: Number of days to retain chats
            
        Returns:
            Number of chats deleted
        """
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=retention_days)
            
            query = """
                SELECT c.id, c.user_id FROM c 
                WHERE c.doc_type = 'chat_session'
                AND c.updated_at < @cutoff_date
            """
            
            parameters = [
                {"name": "@cutoff_date", "value": cutoff_date.isoformat()},
            ]
            
            old_chats = await self.client.query_items(
                container_name=self.container_name,
                query=query,
                parameters=parameters,
            )
            
            deleted_count = 0
            for chat_doc in old_chats:
                success = await self.client.delete_item(
                    container_name=self.container_name,
                    item_id=chat_doc["id"],
                    partition_key_value=chat_doc["user_id"],
                )
                if success:
                    deleted_count += 1
            
            logger.info(
                "Cleaned up old chat sessions",
                retention_days=retention_days,
                deleted_count=deleted_count,
            )
            
            return deleted_count
            
        except Exception as e:
            logger.error("Failed to cleanup old chats", error=str(e))
            return 0
    
    async def get_chat_statistics(self, user_id: str) -> Dict[str, Any]:
        """
        Get chat statistics for a user.
        
        Args:
            user_id: User ID
            
        Returns:
            Dictionary with chat statistics
        """
        try:
            query = """
                SELECT 
                    COUNT(1) as total_chats,
                    SUM(c.chat_data.total_turns) as total_turns,
                    SUM(c.chat_data.total_tokens) as total_tokens,
                    AVG(c.chat_data.total_turns) as avg_turns_per_chat
                FROM c 
                WHERE c.user_id = @user_id 
                AND c.doc_type = 'chat_session'
            """
            
            parameters = [
                {"name": "@user_id", "value": user_id},
            ]
            
            results = await self.client.query_items(
                container_name=self.container_name,
                query=query,
                parameters=parameters,
                partition_key_value=user_id,
            )
            
            if results:
                stats = results[0]
                return {
                    "total_chats": stats.get("total_chats", 0),
                    "total_turns": stats.get("total_turns", 0),
                    "total_tokens": stats.get("total_tokens", 0),
                    "avg_turns_per_chat": stats.get("avg_turns_per_chat", 0),
                }
            
            return {
                "total_chats": 0,
                "total_turns": 0,
                "total_tokens": 0,
                "avg_turns_per_chat": 0,
            }
            
        except Exception as e:
            logger.error("Failed to get chat statistics", user_id=user_id, error=str(e))
            return {}
