"""
Plan model for semantic kernel planner decisions and execution.

This module defines models for planner decisions, tool selections,
and execution strategies.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field


class StepStatus(str, Enum):
    """Step execution status enumeration."""
    
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PlanType(str, Enum):
    """Plan type enumeration."""
    
    NO_TOOL = "no_tool"
    SQL_ONLY = "sql_only" 
    GRAPH_ONLY = "graph_only"
    HYBRID = "hybrid"
    ACCOUNT_RESOLUTION = "account_resolution"


class ToolDecision(BaseModel):
    """Tool selection decision with reasoning."""
    
    tool_name: str = Field(..., description="Name of the selected tool")
    confidence: float = Field(..., description="Confidence in tool selection (0-1)")
    reasoning: str = Field(..., description="Reasoning for tool selection")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Tool parameters")
    
    # Execution metadata
    estimated_duration_ms: Optional[int] = Field(default=None, description="Estimated execution time")
    priority: int = Field(default=1, description="Execution priority (1=highest)")


class AccountResolutionStep(BaseModel):
    """Account resolution step in the plan."""
    
    extracted_name: str = Field(..., description="Extracted account name from query")
    confidence_threshold: float = Field(default=0.7, description="Confidence threshold for selection")
    requires_disambiguation: bool = Field(default=False, description="Whether disambiguation is needed")
    candidates: List[str] = Field(default_factory=list, description="Candidate account names")


class ExecutionStep(BaseModel):
    """Individual execution step in the plan."""
    
    step_id: str = Field(..., description="Step identifier")
    step_type: str = Field(..., description="Type of step (tool, filter, merge)")
    description: str = Field(..., description="Step description")
    
    # Tool information
    tool_decision: Optional[ToolDecision] = Field(default=None, description="Tool to execute")
    
    # Account resolution
    account_resolution: Optional[AccountResolutionStep] = Field(default=None, description="Account resolution step")
    
    # Dependencies
    depends_on: List[str] = Field(default_factory=list, description="Step IDs this depends on")
    can_run_parallel: bool = Field(default=False, description="Whether step can run in parallel")
    
    # Execution results
    status: str = Field(default="pending", description="Execution status")
    result: Optional[Dict[str, Any]] = Field(default=None, description="Step execution result")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    execution_time_ms: Optional[int] = Field(default=None, description="Actual execution time")


class Plan(BaseModel):
    """Execution plan created by the planner."""
    
    id: str = Field(..., description="Plan ID")
    plan_type: PlanType = Field(..., description="Type of plan")
    
    # Plan metadata
    query: str = Field(..., description="Original user query")
    user_id: str = Field(..., description="User ID who requested the plan")
    reasoning: str = Field(..., description="Planner reasoning for this plan")
    confidence: float = Field(..., description="Overall plan confidence (0-1)")
    
    # Execution steps
    steps: List[ExecutionStep] = Field(default_factory=list, description="Execution steps")
    
    # Account context
    resolved_account_id: Optional[str] = Field(default=None, description="Resolved account ID")
    resolved_account_name: Optional[str] = Field(default=None, description="Resolved account name")
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Plan creation time")
    started_at: Optional[datetime] = Field(default=None, description="Execution start time")
    completed_at: Optional[datetime] = Field(default=None, description="Execution completion time")
    
    # Execution metadata
    status: str = Field(default="created", description="Plan execution status")
    total_steps: int = Field(default=0, description="Total number of steps")
    completed_steps: int = Field(default=0, description="Number of completed steps")
    
    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }
    
    def add_step(self, step: ExecutionStep) -> None:
        """Add an execution step to the plan."""
        self.steps.append(step)
        self.total_steps = len(self.steps)
    
    def get_next_steps(self) -> List[ExecutionStep]:
        """Get steps that are ready to execute."""
        ready_steps = []
        completed_step_ids = {step.step_id for step in self.steps if step.status == "completed"}
        
        for step in self.steps:
            if step.status == "pending":
                # Check if all dependencies are completed
                if all(dep_id in completed_step_ids for dep_id in step.depends_on):
                    ready_steps.append(step)
        
        return ready_steps
    
    def get_parallel_steps(self) -> List[List[ExecutionStep]]:
        """Get steps grouped by parallel execution capability."""
        ready_steps = self.get_next_steps()
        parallel_groups = []
        sequential_steps = []
        
        for step in ready_steps:
            if step.can_run_parallel:
                parallel_groups.append([step])
            else:
                sequential_steps.append(step)
        
        # Add sequential steps as individual groups
        for step in sequential_steps:
            parallel_groups.append([step])
        
        return parallel_groups
    
    def mark_step_completed(self, step_id: str, result: Optional[Dict[str, Any]] = None) -> None:
        """Mark a step as completed with optional result."""
        for step in self.steps:
            if step.step_id == step_id:
                step.status = "completed"
                step.result = result
                self.completed_steps += 1
                break
    
    def mark_step_failed(self, step_id: str, error: str) -> None:
        """Mark a step as failed with error message."""
        for step in self.steps:
            if step.step_id == step_id:
                step.status = "failed"
                step.error = error
                break
    
    @property
    def is_complete(self) -> bool:
        """Check if plan execution is complete."""
        return self.completed_steps == self.total_steps
    
    @property
    def has_failed_steps(self) -> bool:
        """Check if any steps have failed."""
        return any(step.status == "failed" for step in self.steps)
    
    @property
    def progress_percentage(self) -> float:
        """Get execution progress as percentage."""
        if self.total_steps == 0:
            return 0.0
        return (self.completed_steps / self.total_steps) * 100.0


class PlanningRequest(BaseModel):
    """Request for plan creation."""
    
    query: str = Field(..., description="User query to plan for")
    user_id: str = Field(..., description="User ID making the request")
    chat_id: str = Field(..., description="Chat session ID")
    context: Dict[str, Any] = Field(default_factory=dict, description="Additional context")
    
    # Planning preferences
    max_steps: int = Field(default=10, description="Maximum number of steps")
    timeout_seconds: int = Field(default=300, description="Planning timeout")
    prefer_parallel: bool = Field(default=True, description="Prefer parallel execution")


class PlanningResult(BaseModel):
    """Result of plan creation."""
    
    request: PlanningRequest = Field(..., description="Original planning request")
    plan: Optional[Plan] = Field(default=None, description="Generated plan")
    
    # Planning metadata
    planning_time_ms: int = Field(..., description="Time taken to create plan")
    alternatives_considered: int = Field(default=1, description="Number of alternatives considered")
    
    # Error handling
    success: bool = Field(default=True, description="Whether planning succeeded")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    fallback_used: bool = Field(default=False, description="Whether fallback plan was used")


class ExecutionResult(BaseModel):
    """Result of plan execution."""
    
    plan_id: str = Field(..., description="Plan ID that was executed")
    execution_id: str = Field(..., description="Unique execution identifier")
    
    # Timestamps
    started_at: datetime = Field(..., description="Execution start time")
    completed_at: Optional[datetime] = Field(default=None, description="Execution completion time")
    
    # Status and results
    status: str = Field(..., description="Execution status")
    step_results: List[Dict[str, Any]] = Field(default_factory=list, description="Results from each step")
    final_output: str = Field(..., description="Final compiled output")
    
    # Error handling
    error_message: Optional[str] = Field(default=None, description="Error message if execution failed")
    
    # Metadata
    duration_seconds: Optional[float] = Field(default=None, description="Total execution duration")
    execution_metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional execution metadata")
