"""
Planner service for semantic kernel orchestration and tool selection.

This service handles plan creation, execution, and tool invocation using
Semantic Kernel's planner capabilities with RBAC filtering.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
from uuid import uuid4
import json
import structlog

from semantic_kernel import Kernel
from semantic_kernel.planners import SequentialPlanner, StepwisePlanner
from semantic_kernel.core_plugins import ConversationSummaryPlugin, TimePlugin
from semantic_kernel.planning.sequential_planner.sequential_planner_config import SequentialPlannerConfig
from semantic_kernel.planning.stepwise_planner.stepwise_planner_config import StepwisePlannerConfig

from chatbot.repositories.agent_functions_repository import AgentFunctionsRepository
from chatbot.repositories.prompts_repository import PromptsRepository
from chatbot.models.rbac import RBACContext
from chatbot.models.plan import Plan, PlanStep, ExecutionResult, StepStatus
from chatbot.services.rbac_service import RBACService

logger = structlog.get_logger(__name__)


class PlannerService:
    """Service for managing semantic kernel planning and execution."""
    
    def __init__(
        self,
        kernel: Kernel,
        agent_functions_repo: AgentFunctionsRepository,
        prompts_repo: PromptsRepository,
        rbac_service: RBACService
    ):
        """
        Initialize the planner service.
        
        Args:
            kernel: Semantic Kernel instance
            agent_functions_repo: Repository for agent function definitions
            prompts_repo: Repository for system prompts
            rbac_service: RBAC service for permission filtering
        """
        self.kernel = kernel
        self.agent_functions_repo = agent_functions_repo
        self.prompts_repo = prompts_repo
        self.rbac_service = rbac_service
        
        # Configure planners
        self.sequential_planner = None
        self.stepwise_planner = None
        self._configure_planners()
    
    def _configure_planners(self):
        """Configure the available planners."""
        try:
            # Sequential planner for structured multi-step plans
            sequential_config = SequentialPlannerConfig(
                max_iterations=10,
                max_tokens=4000,
                excluded_plugins=[],
                excluded_functions=[]
            )
            self.sequential_planner = SequentialPlanner(self.kernel, sequential_config)
            
            # Stepwise planner for iterative reasoning
            stepwise_config = StepwisePlannerConfig(
                max_iterations=15,
                max_tokens=4000,
                excluded_plugins=[],
                excluded_functions=[]
            )
            self.stepwise_planner = StepwisePlanner(self.kernel, stepwise_config)
            
            logger.info("Planners configured successfully")
            
        except Exception as e:
            logger.error("Failed to configure planners", error=str(e))
            raise
    
    async def create_plan(
        self,
        user_request: str,
        rbac_context: RBACContext,
        conversation_context: Optional[List[Dict[str, Any]]] = None,
        planner_type: str = "sequential"
    ) -> Plan:
        """
        Create an execution plan for the user request.
        
        Args:
            user_request: User's natural language request
            rbac_context: User's RBAC context
            conversation_context: Optional conversation history
            planner_type: Type of planner to use ("sequential" or "stepwise")
            
        Returns:
            Created execution plan
        """
        try:
            # Get available functions based on RBAC
            available_functions = await self._get_filtered_functions(rbac_context)
            
            # Get system prompt for planning
            planning_prompt = await self.prompts_repo.get_prompt(
                "planner_system",
                tenant_id=rbac_context.tenant_id,
                scenario="general"
            )
            
            # Prepare context for planner
            context_text = self._prepare_context(
                user_request, conversation_context, available_functions
            )
            
            # Create plan using selected planner
            if planner_type == "stepwise":
                sk_plan = await self.stepwise_planner.create_plan(context_text)
            else:
                sk_plan = await self.sequential_planner.create_plan(context_text)
            
            # Convert SK plan to our plan model
            plan = self._convert_sk_plan_to_plan(sk_plan, rbac_context)
            
            logger.info(
                "Plan created successfully",
                plan_id=plan.plan_id,
                user_id=rbac_context.user_id,
                steps_count=len(plan.steps),
                planner_type=planner_type
            )
            
            return plan
            
        except Exception as e:
            logger.error(
                "Failed to create plan",
                user_id=rbac_context.user_id,
                planner_type=planner_type,
                error=str(e)
            )
            raise
    
    async def execute_plan(
        self,
        plan: Plan,
        rbac_context: RBACContext,
        execution_context: Optional[Dict[str, Any]] = None
    ) -> ExecutionResult:
        """
        Execute a plan step by step.
        
        Args:
            plan: Plan to execute
            rbac_context: User's RBAC context
            execution_context: Optional execution context
            
        Returns:
            Execution result
        """
        try:
            execution_result = ExecutionResult(
                plan_id=plan.plan_id,
                execution_id=str(uuid4()),
                started_at=datetime.utcnow(),
                status="running",
                step_results=[],
                final_output="",
                execution_metadata=execution_context or {}
            )
            
            logger.info(
                "Starting plan execution",
                plan_id=plan.plan_id,
                execution_id=execution_result.execution_id,
                user_id=rbac_context.user_id
            )
            
            # Execute each step
            for step in plan.steps:
                step_result = await self._execute_step(step, rbac_context, execution_context)
                execution_result.step_results.append(step_result)
                
                # Check if step failed and should stop execution
                if step_result["status"] == "failed" and step.required:
                    execution_result.status = "failed"
                    execution_result.error_message = step_result.get("error_message", "Step execution failed")
                    break
            
            # Finalize execution result
            if execution_result.status != "failed":
                execution_result.status = "completed"
                execution_result.final_output = self._compile_final_output(execution_result.step_results)
            
            execution_result.completed_at = datetime.utcnow()
            execution_result.duration_seconds = (
                execution_result.completed_at - execution_result.started_at
            ).total_seconds()
            
            logger.info(
                "Plan execution completed",
                plan_id=plan.plan_id,
                execution_id=execution_result.execution_id,
                status=execution_result.status,
                duration_seconds=execution_result.duration_seconds
            )
            
            return execution_result
            
        except Exception as e:
            logger.error(
                "Plan execution failed",
                plan_id=plan.plan_id,
                user_id=rbac_context.user_id,
                error=str(e)
            )
            
            # Return failed execution result
            return ExecutionResult(
                plan_id=plan.plan_id,
                execution_id=str(uuid4()),
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
                status="failed",
                error_message=str(e),
                step_results=[],
                final_output="",
                execution_metadata=execution_context or {}
            )
    
    async def _get_filtered_functions(self, rbac_context: RBACContext) -> List[Dict[str, Any]]:
        """
        Get functions available to the user based on RBAC.
        
        Args:
            rbac_context: User's RBAC context
            
        Returns:
            List of available function definitions
        """
        try:
            # Get all function definitions
            all_functions = await self.agent_functions_repo.get_all_functions()
            
            # Filter based on RBAC permissions
            available_functions = []
            for function in all_functions:
                # Check if user has permission for this function
                if await self.rbac_service.check_function_permission(
                    rbac_context, function["name"]
                ):
                    available_functions.append(function)
            
            logger.debug(
                "Functions filtered by RBAC",
                user_id=rbac_context.user_id,
                total_functions=len(all_functions),
                available_functions=len(available_functions)
            )
            
            return available_functions
            
        except Exception as e:
            logger.error(
                "Failed to get filtered functions",
                user_id=rbac_context.user_id,
                error=str(e)
            )
            return []
    
    def _prepare_context(
        self,
        user_request: str,
        conversation_context: Optional[List[Dict[str, Any]]],
        available_functions: List[Dict[str, Any]]
    ) -> str:
        """
        Prepare context for the planner.
        
        Args:
            user_request: User's request
            conversation_context: Previous conversation
            available_functions: Available functions
            
        Returns:
            Formatted context string
        """
        context_parts = [
            f"User Request: {user_request}",
            "",
            "Available Functions:"
        ]
        
        # Add function descriptions
        for func in available_functions:
            context_parts.append(f"- {func['name']}: {func.get('description', '')}")
        
        # Add conversation context if available
        if conversation_context:
            context_parts.extend([
                "",
                "Previous Conversation:",
            ])
            for turn in conversation_context[-3:]:  # Last 3 turns
                if isinstance(turn, dict):
                    context_parts.append(f"User: {turn.get('user_message', '')}")
                    context_parts.append(f"Assistant: {turn.get('assistant_message', '')}")
        
        return "\n".join(context_parts)
    
    def _convert_sk_plan_to_plan(self, sk_plan, rbac_context: RBACContext) -> Plan:
        """
        Convert Semantic Kernel plan to our plan model.
        
        Args:
            sk_plan: Semantic Kernel plan
            rbac_context: User's RBAC context
            
        Returns:
            Converted plan
        """
        plan_steps = []
        
        # Extract steps from SK plan
        for i, step in enumerate(sk_plan._steps):
            plan_step = PlanStep(
                step_id=str(uuid4()),
                step_number=i + 1,
                function_name=step.plugin_name + "." + step.name if step.plugin_name else step.name,
                parameters=dict(step.parameters) if step.parameters else {},
                description=step.description or f"Execute {step.name}",
                required=True,
                status=StepStatus.PENDING,
                depends_on=[]
            )
            plan_steps.append(plan_step)
        
        return Plan(
            plan_id=str(uuid4()),
            user_id=rbac_context.user_id,
            original_request=sk_plan.description or "User request",
            steps=plan_steps,
            created_at=datetime.utcnow(),
            status="created",
            metadata={
                "planner_type": "semantic_kernel",
                "sk_plan_description": sk_plan.description
            }
        )
    
    async def _execute_step(
        self,
        step: PlanStep,
        rbac_context: RBACContext,
        execution_context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Execute a single plan step.
        
        Args:
            step: Step to execute
            rbac_context: User's RBAC context
            execution_context: Execution context
            
        Returns:
            Step execution result
        """
        try:
            logger.info(
                "Executing plan step",
                step_id=step.step_id,
                function_name=step.function_name,
                user_id=rbac_context.user_id
            )
            
            step.status = StepStatus.RUNNING
            step.started_at = datetime.utcnow()
            
            # Get function from kernel
            plugin_name, function_name = self._parse_function_name(step.function_name)
            
            if plugin_name:
                kernel_function = self.kernel.plugins[plugin_name][function_name]
            else:
                # Look for function in all plugins
                kernel_function = None
                for plugin in self.kernel.plugins.values():
                    if function_name in plugin:
                        kernel_function = plugin[function_name]
                        break
            
            if not kernel_function:
                raise ValueError(f"Function not found: {step.function_name}")
            
            # Execute the function
            result = await kernel_function.invoke(
                variables=step.parameters,
                context=execution_context
            )
            
            step.status = StepStatus.COMPLETED
            step.completed_at = datetime.utcnow()
            step.output = str(result)
            
            step_result = {
                "step_id": step.step_id,
                "status": "completed",
                "output": step.output,
                "execution_time": (step.completed_at - step.started_at).total_seconds()
            }
            
            logger.info(
                "Step executed successfully",
                step_id=step.step_id,
                execution_time=step_result["execution_time"]
            )
            
            return step_result
            
        except Exception as e:
            step.status = StepStatus.FAILED
            step.completed_at = datetime.utcnow()
            step.error_message = str(e)
            
            logger.error(
                "Step execution failed",
                step_id=step.step_id,
                error=str(e)
            )
            
            return {
                "step_id": step.step_id,
                "status": "failed",
                "error_message": str(e),
                "execution_time": (step.completed_at - step.started_at).total_seconds()
            }
    
    def _parse_function_name(self, function_name: str) -> tuple[Optional[str], str]:
        """
        Parse function name to extract plugin and function.
        
        Args:
            function_name: Full function name
            
        Returns:
            Tuple of (plugin_name, function_name)
        """
        if "." in function_name:
            parts = function_name.split(".", 1)
            return parts[0], parts[1]
        return None, function_name
    
    def _compile_final_output(self, step_results: List[Dict[str, Any]]) -> str:
        """
        Compile final output from step results.
        
        Args:
            step_results: Results from all executed steps
            
        Returns:
            Compiled final output
        """
        outputs = []
        for result in step_results:
            if result["status"] == "completed" and result.get("output"):
                outputs.append(result["output"])
        
        if not outputs:
            return "Plan executed but no output generated"
        
        # If single output, return it directly
        if len(outputs) == 1:
            return outputs[0]
        
        # Multiple outputs, combine them
        return "\n\n".join(f"Step {i+1}: {output}" for i, output in enumerate(outputs))
    
    async def validate_plan(self, plan: Plan, rbac_context: RBACContext) -> Dict[str, Any]:
        """
        Validate a plan before execution.
        
        Args:
            plan: Plan to validate
            rbac_context: User's RBAC context
            
        Returns:
            Validation result
        """
        try:
            validation_result = {
                "valid": True,
                "errors": [],
                "warnings": [],
                "estimated_duration": 0
            }
            
            # Check function permissions
            for step in plan.steps:
                function_name = step.function_name.split(".")[-1]
                if not await self.rbac_service.check_function_permission(
                    rbac_context, function_name
                ):
                    validation_result["errors"].append(
                        f"No permission for function: {function_name}"
                    )
                    validation_result["valid"] = False
            
            # Check function availability
            available_functions = await self._get_filtered_functions(rbac_context)
            available_names = {f["name"] for f in available_functions}
            
            for step in plan.steps:
                function_name = step.function_name.split(".")[-1]
                if function_name not in available_names:
                    validation_result["errors"].append(
                        f"Function not available: {function_name}"
                    )
                    validation_result["valid"] = False
            
            # Estimate duration (simplified)
            validation_result["estimated_duration"] = len(plan.steps) * 2  # 2 seconds per step
            
            # Check for potential issues
            if len(plan.steps) > 10:
                validation_result["warnings"].append(
                    "Plan has many steps, execution may take longer"
                )
            
            logger.debug(
                "Plan validation completed",
                plan_id=plan.plan_id,
                valid=validation_result["valid"],
                errors_count=len(validation_result["errors"])
            )
            
            return validation_result
            
        except Exception as e:
            logger.error(
                "Plan validation failed",
                plan_id=plan.plan_id,
                error=str(e)
            )
            
            return {
                "valid": False,
                "errors": [f"Validation error: {str(e)}"],
                "warnings": [],
                "estimated_duration": 0
            }
