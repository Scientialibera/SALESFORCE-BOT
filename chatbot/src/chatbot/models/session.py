"""
Enhanced session and data models for unified Cosmos DB storage.

This module defines models for comprehensive session tracking including:
- Session metadata with message history
- Query execution tracking (SQL/Graph)
- Feedback linking to specific messages
- RBAC context preservation
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field
from uuid import uuid4

from chatbot.models.message import Message, MessageRole
from chatbot.models.rbac import RBACContext


class QueryType(str, Enum):
    """Type of query executed."""
    SQL = "sql"
    GRAPH = "graph"
    HYBRID = "hybrid"
    DIRECT = "direct"


class QueryExecution(BaseModel):
    """Details of a query execution within a message turn."""

    id: str = Field(default_factory=lambda: str(uuid4()), description="Query execution ID")
    query_type: QueryType = Field(..., description="Type of query executed")
    original_query: str = Field(..., description="Original user query")
    processed_query: str = Field(..., description="Processed/transformed query")

    # SQL-specific fields
    sql_query: Optional[str] = Field(default=None, description="Generated SQL query")
    tables_accessed: List[str] = Field(default_factory=list, description="Database tables accessed")

    # Graph-specific fields
    gremlin_query: Optional[str] = Field(default=None, description="Generated Gremlin query")
    graph_traversal_steps: List[str] = Field(default_factory=list, description="Graph traversal steps")

    # Account resolution
    accounts_resolved: List[Dict[str, Any]] = Field(default_factory=list, description="Resolved account information")

    # Results and metadata
    result_count: int = Field(default=0, description="Number of results returned")
    execution_time_ms: int = Field(default=0, description="Execution time in milliseconds")
    success: bool = Field(default=True, description="Whether execution was successful")
    error_message: Optional[str] = Field(default=None, description="Error message if failed")

    # RBAC context
    rbac_filters_applied: List[str] = Field(default_factory=list, description="RBAC filters that were applied")

    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Execution timestamp")


class MessageTurn(BaseModel):
    """Enhanced conversation turn with comprehensive tracking."""

    id: str = Field(default_factory=lambda: str(uuid4()), description="Turn ID")
    turn_number: int = Field(..., description="Sequential turn number in session")

    # Messages
    user_message: Message = Field(..., description="User message")
    assistant_message: Optional[Message] = Field(default=None, description="Assistant response")

    # Query executions for this turn
    query_executions: List[QueryExecution] = Field(default_factory=list, description="Query executions performed")

    # Plan information
    plan_type: Optional[str] = Field(default=None, description="Type of plan executed")
    plan_id: Optional[str] = Field(default=None, description="Plan ID if generated")

    # Timing
    started_at: datetime = Field(default_factory=datetime.utcnow, description="Turn start time")
    completed_at: Optional[datetime] = Field(default=None, description="Turn completion time")
    total_duration_ms: Optional[int] = Field(default=None, description="Total turn duration")

    # Feedback
    feedback_received: bool = Field(default=False, description="Whether feedback was received")
    feedback_ids: List[str] = Field(default_factory=list, description="IDs of feedback submissions")

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}

    def add_query_execution(self, query_execution: QueryExecution) -> None:
        """Add a query execution to this turn."""
        self.query_executions.append(query_execution)

    def mark_completed(self) -> None:
        """Mark the turn as completed and calculate duration."""
        self.completed_at = datetime.utcnow()
        if self.started_at and self.completed_at:
            self.total_duration_ms = int((self.completed_at - self.started_at).total_seconds() * 1000)


class ChatSession(BaseModel):
    """Enhanced chat session with comprehensive tracking."""

    id: str = Field(..., description="Session ID")
    user_id: str = Field(..., description="User ID")

    # Session metadata
    title: Optional[str] = Field(default=None, description="Session title")
    description: Optional[str] = Field(default=None, description="Session description")

    # Conversation data
    turns: List[MessageTurn] = Field(default_factory=list, description="Message turns")

    # Session statistics
    total_turns: int = Field(default=0, description="Total number of turns")
    total_queries: int = Field(default=0, description="Total queries executed")
    total_sql_queries: int = Field(default=0, description="Total SQL queries")
    total_graph_queries: int = Field(default=0, description="Total graph queries")
    total_tokens_used: int = Field(default=0, description="Total tokens consumed")

    # Session timing
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Session creation time")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Last update time")
    last_activity_at: datetime = Field(default_factory=datetime.utcnow, description="Last activity time")

    # RBAC context for the session
    tenant_id: str = Field(..., description="Tenant ID")
    user_roles: List[str] = Field(default_factory=list, description="User roles")

    # Session metadata
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional session metadata")

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}

    def add_turn(self, turn: MessageTurn) -> None:
        """Add a turn to the session and update statistics."""
        self.turns.append(turn)
        self.total_turns = len(self.turns)
        self.total_queries += len(turn.query_executions)

        # Update query type counters
        for query_exec in turn.query_executions:
            if query_exec.query_type == QueryType.SQL:
                self.total_sql_queries += 1
            elif query_exec.query_type == QueryType.GRAPH:
                self.total_graph_queries += 1
            elif query_exec.query_type == QueryType.HYBRID:
                self.total_sql_queries += 1
                self.total_graph_queries += 1

        # Update token usage
        if turn.user_message.tokens_used:
            self.total_tokens_used += turn.user_message.tokens_used
        if turn.assistant_message and turn.assistant_message.tokens_used:
            self.total_tokens_used += turn.assistant_message.tokens_used

        # Update timestamps
        self.updated_at = datetime.utcnow()
        self.last_activity_at = datetime.utcnow()

    def get_recent_turns(self, count: int = 10) -> List[MessageTurn]:
        """Get recent conversation turns."""
        return self.turns[-count:] if count > 0 else self.turns

    def get_messages_for_context(self, max_turns: int = 5) -> List[Dict[str, str]]:
        """Get messages formatted for LLM context."""
        messages = []
        recent_turns = self.get_recent_turns(max_turns)

        for turn in recent_turns:
            messages.append({
                "role": turn.user_message.role.value,
                "content": turn.user_message.content,
            })

            if turn.assistant_message:
                messages.append({
                    "role": turn.assistant_message.role.value,
                    "content": turn.assistant_message.content,
                })

        return messages


class FeedbackSubmission(BaseModel):
    """Enhanced feedback submission linked to specific messages and queries."""

    id: str = Field(default_factory=lambda: str(uuid4()), description="Feedback ID")

    # Links to conversation elements
    session_id: str = Field(..., description="Session ID")
    turn_id: str = Field(..., description="Turn ID")
    message_id: Optional[str] = Field(default=None, description="Specific message ID if applicable")
    query_execution_ids: List[str] = Field(default_factory=list, description="Query execution IDs being rated")

    # User information
    user_id: str = Field(..., description="User who submitted feedback")

    # Feedback content
    rating: int = Field(..., description="Rating (1-5)", ge=1, le=5)
    comment: Optional[str] = Field(default=None, description="Optional comment")
    feedback_type: str = Field(default="general", description="Type of feedback")

    # Categorization
    categories: List[str] = Field(default_factory=list, description="Feedback categories")
    tags: List[str] = Field(default_factory=list, description="Feedback tags")

    # Context information
    context_metadata: Dict[str, Any] = Field(default_factory=dict, description="Context when feedback was given")

    # Timestamps
    submitted_at: datetime = Field(default_factory=datetime.utcnow, description="Submission timestamp")

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class SessionAnalytics(BaseModel):
    """Analytics data for a chat session."""

    session_id: str = Field(..., description="Session ID")
    user_id: str = Field(..., description="User ID")

    # Query analytics
    query_success_rate: float = Field(default=0.0, description="Percentage of successful queries")
    avg_query_time_ms: float = Field(default=0.0, description="Average query execution time")
    most_used_query_type: Optional[str] = Field(default=None, description="Most frequently used query type")

    # User engagement
    avg_turn_length: float = Field(default=0.0, description="Average characters per user message")
    session_duration_minutes: float = Field(default=0.0, description="Total session duration")

    # Feedback analytics
    avg_rating: Optional[float] = Field(default=None, description="Average user rating")
    feedback_count: int = Field(default=0, description="Number of feedback submissions")

    # Error tracking
    error_rate: float = Field(default=0.0, description="Percentage of turns with errors")
    common_errors: List[str] = Field(default_factory=list, description="Most common error types")

    # Generated at
    generated_at: datetime = Field(default_factory=datetime.utcnow, description="Analytics generation time")

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}