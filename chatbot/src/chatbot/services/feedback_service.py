"""
Feedback service for managing user feedback and analytics.

This service handles feedback collection, storage, and provides
analytics for model evaluation and improvement.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
import structlog

from chatbot.repositories.feedback_repository import FeedbackRepository
from chatbot.models.result import FeedbackData
from chatbot.models.rbac import RBACContext

logger = structlog.get_logger(__name__)


class FeedbackService:
    """Service for managing user feedback and analytics."""
    
    def __init__(self, feedback_repository: FeedbackRepository):
        """
        Initialize the feedback service.
        
        Args:
            feedback_repository: Repository for feedback data persistence
        """
        self.feedback_repository = feedback_repository
    
    async def submit_feedback(
        self,
        turn_id: str,
        user_id: str,
        rating: int,
        comment: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Submit user feedback for a conversation turn.
        
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
            # Validate rating
            if not 1 <= rating <= 5:
                raise ValueError("Rating must be between 1 and 5")
            
            feedback_id = await self.feedback_repository.save_feedback(
                turn_id=turn_id,
                user_id=user_id,
                rating=rating,
                comment=comment,
                metadata=metadata
            )
            
            logger.info(
                "Feedback submitted",
                feedback_id=feedback_id,
                turn_id=turn_id,
                user_id=user_id,
                rating=rating,
                has_comment=bool(comment)
            )
            
            return feedback_id
            
        except Exception as e:
            logger.error(
                "Failed to submit feedback",
                turn_id=turn_id,
                user_id=user_id,
                error=str(e)
            )
            raise
    
    async def get_feedback_for_turn(self, turn_id: str) -> Optional[FeedbackData]:
        """
        Get feedback for a specific conversation turn.
        
        Args:
            turn_id: ID of the conversation turn
            
        Returns:
            Feedback data or None if not found
        """
        try:
            feedback = await self.feedback_repository.get_feedback_by_turn(turn_id)
            
            if feedback:
                logger.debug("Retrieved feedback for turn", turn_id=turn_id)
            
            return feedback
            
        except Exception as e:
            logger.error(
                "Failed to get feedback for turn",
                turn_id=turn_id,
                error=str(e)
            )
            raise
    
    async def get_user_feedback_history(
        self,
        rbac_context: RBACContext,
        limit: int = 50,
        offset: int = 0
    ) -> List[FeedbackData]:
        """
        Get feedback history for a user.
        
        Args:
            rbac_context: User's RBAC context
            limit: Maximum number of feedback items to return
            offset: Number of items to skip
            
        Returns:
            List of feedback data
        """
        try:
            feedback_list = await self.feedback_repository.get_user_feedback_history(
                user_id=rbac_context.user_id,
                limit=limit,
                offset=offset
            )
            
            logger.info(
                "Retrieved user feedback history",
                user_id=rbac_context.user_id,
                count=len(feedback_list)
            )
            
            return feedback_list
            
        except Exception as e:
            logger.error(
                "Failed to get user feedback history",
                user_id=rbac_context.user_id,
                error=str(e)
            )
            raise
    
    async def get_feedback_analytics(
        self,
        rbac_context: RBACContext,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Get feedback analytics and statistics.
        
        Args:
            rbac_context: User's RBAC context for access control
            start_date: Start date for analytics (optional)
            end_date: End date for analytics (optional)
            
        Returns:
            Dictionary with feedback analytics
        """
        try:
            # Check if user has permission to view analytics
            if not self._can_view_analytics(rbac_context):
                raise PermissionError("User does not have permission to view analytics")
            
            # Default to last 30 days if no dates provided
            if not end_date:
                end_date = datetime.utcnow()
            if not start_date:
                start_date = end_date - timedelta(days=30)
            
            stats = await self.feedback_repository.get_feedback_statistics(
                start_date=start_date,
                end_date=end_date
            )
            
            # Add additional analytics
            analytics = {
                **stats,
                "satisfaction_score": self._calculate_satisfaction_score(stats),
                "feedback_trends": await self._get_feedback_trends(start_date, end_date),
                "top_issues": await self._extract_top_issues(start_date, end_date),
            }
            
            logger.info(
                "Generated feedback analytics",
                user_id=rbac_context.user_id,
                date_range_days=(end_date - start_date).days,
                total_feedback=analytics.get("total_feedback", 0)
            )
            
            return analytics
            
        except Exception as e:
            logger.error(
                "Failed to get feedback analytics",
                user_id=rbac_context.user_id,
                error=str(e)
            )
            raise
    
    def _can_view_analytics(self, rbac_context: RBACContext) -> bool:
        """
        Check if user can view feedback analytics.
        
        Args:
            rbac_context: User's RBAC context
            
        Returns:
            True if user can view analytics
        """
        allowed_roles = {"admin", "manager", "analytics_viewer", "sales_manager"}
        return bool(set(rbac_context.roles) & allowed_roles)
    
    def _calculate_satisfaction_score(self, stats: Dict[str, Any]) -> float:
        """
        Calculate overall satisfaction score from feedback stats.
        
        Args:
            stats: Feedback statistics
            
        Returns:
            Satisfaction score (0-100)
        """
        try:
            avg_rating = stats.get("average_rating", 0)
            if avg_rating == 0:
                return 0.0
            
            # Convert 1-5 scale to 0-100 satisfaction score
            # Ratings 4-5 are considered satisfied
            satisfaction_score = max(0, (avg_rating - 3) * 50)
            return round(satisfaction_score, 2)
            
        except Exception as e:
            logger.error("Failed to calculate satisfaction score", error=str(e))
            return 0.0
    
    async def _get_feedback_trends(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, Any]:
        """
        Get feedback trends over time.
        
        Args:
            start_date: Start date for trends
            end_date: End date for trends
            
        Returns:
            Dictionary with trend data
        """
        try:
            # This would typically query the database for daily/weekly aggregations
            # For now, return a placeholder structure
            return {
                "trend_direction": "stable",  # "improving", "declining", "stable"
                "change_percentage": 0.0,
                "weekly_averages": [],
                "volume_trend": "stable"
            }
            
        except Exception as e:
            logger.error("Failed to get feedback trends", error=str(e))
            return {}
    
    async def _extract_top_issues(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict[str, Any]]:
        """
        Extract top issues from feedback comments.
        
        Args:
            start_date: Start date for analysis
            end_date: End date for analysis
            
        Returns:
            List of top issues with frequencies
        """
        try:
            # This would typically use NLP to analyze comments and extract common themes
            # For now, return a placeholder structure
            return [
                {"issue": "slow_response", "frequency": 15, "sentiment": "negative"},
                {"issue": "inaccurate_data", "frequency": 12, "sentiment": "negative"},
                {"issue": "helpful_insights", "frequency": 25, "sentiment": "positive"},
            ]
            
        except Exception as e:
            logger.error("Failed to extract top issues", error=str(e))
            return []
    
    async def delete_feedback(
        self,
        feedback_id: str,
        rbac_context: RBACContext
    ) -> bool:
        """
        Delete a feedback entry.
        
        Args:
            feedback_id: ID of the feedback to delete
            rbac_context: User's RBAC context for authorization
            
        Returns:
            True if deleted successfully
        """
        try:
            # Check permissions - only admin or the original user can delete
            if not ("admin" in rbac_context.roles):
                # Get the feedback to check ownership
                feedback = await self.feedback_repository.get_feedback_by_turn(feedback_id)
                if not feedback or feedback.user_id != rbac_context.user_id:
                    raise PermissionError("User does not have permission to delete this feedback")
            
            success = await self.feedback_repository.delete_feedback(feedback_id)
            
            if success:
                logger.info(
                    "Feedback deleted",
                    feedback_id=feedback_id,
                    user_id=rbac_context.user_id
                )
            
            return success
            
        except Exception as e:
            logger.error(
                "Failed to delete feedback",
                feedback_id=feedback_id,
                user_id=rbac_context.user_id,
                error=str(e)
            )
            raise
