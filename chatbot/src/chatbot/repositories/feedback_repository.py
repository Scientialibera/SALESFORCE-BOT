"""
Repository for managing user feedback on chat responses.

This module handles storage and retrieval of feedback data
for improving model performance and user experience.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
from uuid import uuid4
import structlog

from azure.cosmos import exceptions as cosmos_exceptions
from azure.cosmos.aio import CosmosClient

from chatbot.models.result import FeedbackData

logger = structlog.get_logger(__name__)


class FeedbackRepository:
    """Repository for managing user feedback data."""
    
    def __init__(self, cosmos_client: CosmosClient, database_name: str, container_name: str):
        """
        Initialize the feedback repository.
        
        Args:
            cosmos_client: Azure Cosmos DB client
            database_name: Cosmos database name
            container_name: Container name for feedback
        """
        self.cosmos_client = cosmos_client
        self.database_name = database_name
        self.container_name = container_name
        self._container = None
        
    async def _get_container(self):
        """Get or create the container reference."""
        if self._container is None:
            database = self.cosmos_client.get_database_client(self.database_name)
            self._container = database.get_container_client(self.container_name)
        return self._container
    
    async def save_feedback(
        self,
        turn_id: str,
        user_id: str,
        rating: int,
        comment: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Save user feedback for a conversation turn.
        
        Args:
            turn_id: ID of the conversation turn
            user_id: ID of the user providing feedback
            rating: Feedback rating (1-5 scale)
            comment: Optional feedback comment
            metadata: Optional additional metadata
            
        Returns:
            Feedback ID
        """
        try:
            container = await self._get_container()
            
            feedback_id = str(uuid4())
            feedback_data = {
                "id": feedback_id,
                "turn_id": turn_id,
                "user_id": user_id,
                "rating": rating,
                "comment": comment,
                "metadata": metadata or {},
                "created_at": datetime.utcnow().isoformat(),
            }
            
            await container.create_item(feedback_data)
            
            logger.info(
                "Saved feedback",
                feedback_id=feedback_id,
                turn_id=turn_id,
                user_id=user_id,
                rating=rating
            )
            
            return feedback_id
            
        except Exception as e:
            logger.error(
                "Failed to save feedback",
                turn_id=turn_id,
                user_id=user_id,
                error=str(e)
            )
            raise
    
    async def get_feedback_by_turn(self, turn_id: str) -> Optional[FeedbackData]:
        """
        Get feedback for a specific conversation turn.
        
        Args:
            turn_id: ID of the conversation turn
            
        Returns:
            Feedback data or None if not found
        """
        try:
            container = await self._get_container()
            
            query = "SELECT * FROM c WHERE c.turn_id = @turn_id"
            parameters = [{"name": "@turn_id", "value": turn_id}]
            
            items = []
            async for item in container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True
            ):
                items.append(item)
            
            if items:
                feedback = items[0]  # Should be only one feedback per turn
                return FeedbackData(
                    feedback_id=feedback["id"],
                    turn_id=feedback["turn_id"],
                    user_id=feedback["user_id"],
                    rating=feedback["rating"],
                    comment=feedback.get("comment"),
                    metadata=feedback.get("metadata", {}),
                    timestamp=datetime.fromisoformat(feedback["created_at"]),
                )
            
            return None
            
        except Exception as e:
            logger.error(
                "Failed to get feedback by turn",
                turn_id=turn_id,
                error=str(e)
            )
            raise
    
    async def get_user_feedback_history(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0
    ) -> List[FeedbackData]:
        """
        Get feedback history for a specific user.
        
        Args:
            user_id: ID of the user
            limit: Maximum number of feedback items to return
            offset: Number of items to skip
            
        Returns:
            List of feedback data
        """
        try:
            container = await self._get_container()
            
            query = """
                SELECT * FROM c 
                WHERE c.user_id = @user_id 
                ORDER BY c.created_at DESC 
                OFFSET @offset LIMIT @limit
            """
            parameters = [
                {"name": "@user_id", "value": user_id},
                {"name": "@offset", "value": offset},
                {"name": "@limit", "value": limit}
            ]
            
            feedback_list = []
            async for item in container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True
            ):
                feedback_list.append(FeedbackData(
                    feedback_id=item["id"],
                    turn_id=item["turn_id"],
                    user_id=item["user_id"],
                    rating=item["rating"],
                    comment=item.get("comment"),
                    metadata=item.get("metadata", {}),
                    timestamp=datetime.fromisoformat(item["created_at"]),
                ))
            
            logger.info(
                "Retrieved user feedback history",
                user_id=user_id,
                count=len(feedback_list)
            )
            
            return feedback_list
            
        except Exception as e:
            logger.error(
                "Failed to get user feedback history",
                user_id=user_id,
                error=str(e)
            )
            raise
    
    async def get_feedback_statistics(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Get feedback statistics for a date range.
        
        Args:
            start_date: Start date for statistics (optional)
            end_date: End date for statistics (optional)
            
        Returns:
            Dictionary with feedback statistics
        """
        try:
            container = await self._get_container()
            
            # Build query with optional date filtering
            where_clause = "WHERE 1=1"
            parameters = []
            
            if start_date:
                where_clause += " AND c.created_at >= @start_date"
                parameters.append({
                    "name": "@start_date",
                    "value": start_date.isoformat()
                })
            
            if end_date:
                where_clause += " AND c.created_at <= @end_date"
                parameters.append({
                    "name": "@end_date",
                    "value": end_date.isoformat()
                })
            
            # Get total count and average rating
            stats_query = f"""
                SELECT 
                    COUNT(1) as total_count,
                    AVG(c.rating) as avg_rating,
                    MIN(c.rating) as min_rating,
                    MAX(c.rating) as max_rating
                FROM c {where_clause}
            """
            
            stats_result = []
            async for item in container.query_items(
                query=stats_query,
                parameters=parameters,
                enable_cross_partition_query=True
            ):
                stats_result.append(item)
            
            stats = stats_result[0] if stats_result else {}
            
            # Get rating distribution
            rating_query = f"""
                SELECT c.rating, COUNT(1) as count
                FROM c {where_clause}
                GROUP BY c.rating
                ORDER BY c.rating
            """
            
            rating_distribution = {}
            async for item in container.query_items(
                query=rating_query,
                parameters=parameters,
                enable_cross_partition_query=True
            ):
                rating_distribution[str(item["rating"])] = item["count"]
            
            result = {
                "total_feedback": stats.get("total_count", 0),
                "average_rating": round(stats.get("avg_rating", 0), 2),
                "min_rating": stats.get("min_rating", 0),
                "max_rating": stats.get("max_rating", 0),
                "rating_distribution": rating_distribution,
                "date_range": {
                    "start": start_date.isoformat() if start_date else None,
                    "end": end_date.isoformat() if end_date else None,
                },
                "generated_at": datetime.utcnow().isoformat(),
            }
            
            logger.info("Generated feedback statistics", **result)
            return result
            
        except Exception as e:
            logger.error("Failed to get feedback statistics", error=str(e))
            raise
    
    async def delete_feedback(self, feedback_id: str) -> bool:
        """
        Delete a feedback entry.
        
        Args:
            feedback_id: ID of the feedback to delete
            
        Returns:
            True if deleted successfully
        """
        try:
            container = await self._get_container()
            
            await container.delete_item(
                item=feedback_id,
                partition_key=feedback_id
            )
            
            logger.info("Deleted feedback", feedback_id=feedback_id)
            return True
            
        except cosmos_exceptions.CosmosResourceNotFoundError:
            logger.warning("Feedback not found for deletion", feedback_id=feedback_id)
            return False
        except Exception as e:
            logger.error(
                "Failed to delete feedback",
                feedback_id=feedback_id,
                error=str(e)
            )
            raise
