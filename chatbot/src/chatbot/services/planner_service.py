"""
Simplified planner service using only Azure OpenAI function calling.

This service handles plan creation and tool selection without Semantic Kernel.
"""

from typing import Any, Dict, List, Optional
import json
import structlog

from chatbot.repositories.agent_functions_repository import AgentFunctionsRepository
from chatbot.repositories.prompts_repository import PromptsRepository
from chatbot.models.rbac import RBACContext

logger = structlog.get_logger(__name__)


class PlannerService:
    """Simplified planner service using Azure OpenAI function calling only."""

    def __init__(
        self,
        agent_functions_repo: AgentFunctionsRepository,
        prompts_repo: PromptsRepository,
        rbac_service,
        aoai_client,
    ):
        """
        Initialize the planner service.

        Args:
            agent_functions_repo: Repository for agent function definitions
            prompts_repo: Repository for system prompts
            rbac_service: RBAC service for permission filtering
            aoai_client: Azure OpenAI client for function calling
        """
        self.agent_functions_repo = agent_functions_repo
        self.prompts_repo = prompts_repo
        self.rbac_service = rbac_service
        self.aoai_client = aoai_client

    async def plan_with_auto_function_calling(
        self,
        user_request: str,
        rbac_context: RBACContext,
        conversation_context: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Plan using Auto Function Calling based on the simplified approach.

        This method uses the simple loop logic where:
        1. Call planner with agent functions to get tool selection
        2. Return structured response for execution

        Args:
            user_request: User's natural language request
            rbac_context: User's RBAC context
            conversation_context: Optional conversation history

        Returns:
            Dictionary with execution plan or direct assistant response
        """
        try:
            # Get available agents (functions whose name ends with '_agent')
            all_defs = await self.agent_functions_repo.list_all_functions()
            agents = [a for a in all_defs if getattr(a, "name", "").endswith("_agent")]

            # Build planner function definitions - each agent is a function
            planner_function_defs = []
            for agent in agents:
                planner_function_defs.append({
                    "name": agent.name,
                    "description": getattr(agent, "description", "") or f"Agent {agent.name}",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "accounts_mentioned": {
                                "type": ["array", "null"],
                                "items": {"type": "string"}
                            }
                        },
                        "required": ["query", "accounts_mentioned"],
                    },
                })

            # Convert to tools format for Azure OpenAI
            planner_tools = [{"type": "function", "function": fd} for fd in planner_function_defs]

            # Get planner system prompt
            try:
                planner_system = await self.prompts_repo.get_system_prompt("planner_system")
            except Exception as e:
                logger.error("Failed to get planner system prompt", error=str(e))
                planner_system = "You are a planner service for a Salesforce Q&A chatbot. Choose the appropriate agent to handle the user request."

            # Prepare messages
            planner_messages = [
                {"role": "system", "content": planner_system},
                {"role": "user", "content": user_request},
            ]

            # Add conversation context if provided
            if conversation_context:
                for turn in conversation_context[-3:]:  # Last 3 turns
                    if isinstance(turn, dict):
                        user_msg = turn.get("user_message", "")
                        assistant_msg = turn.get("assistant_message", "")
                        if user_msg:
                            planner_messages.insert(-1, {"role": "user", "content": user_msg})
                        if assistant_msg:
                            planner_messages.insert(-1, {"role": "assistant", "content": assistant_msg})

            # Call Azure OpenAI with function calling
            planner_resp = await self.aoai_client.create_chat_completion(
                messages=planner_messages,
                tools=planner_tools if planner_tools else None,
                tool_choice="auto",
            )

            # Extract planner response
            planner_message = (planner_resp.get("choices") or [{}])[0].get("message", {})

            # Check if planner returned direct content (no function calls)
            if planner_message.get("content") and not planner_message.get("tool_calls"):
                return {
                    "has_function_calls": False,
                    "assistant_message": planner_message["content"],
                    "raw_response": planner_message.get("content"),
                    "execution_plan": []
                }

            # Extract tool calls
            tool_calls = planner_message.get("tool_calls", [])
            if not tool_calls:
                # No tool calls, treat as direct response
                content = planner_message.get("content", "I can help you with your request.")
                return {
                    "has_function_calls": False,
                    "assistant_message": content,
                    "raw_response": content,
                    "execution_plan": []
                }

            # Build execution plan from tool calls
            execution_plan = []
            for i, tool_call in enumerate(tool_calls):
                function_info = tool_call.get("function", {})
                function_name = function_info.get("name", "")

                # Parse arguments
                try:
                    args = json.loads(function_info.get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {}

                query = args.get("query", user_request)
                accounts_mentioned = args.get("accounts_mentioned")

                execution_plan.append({
                    "step_order": i + 1,
                    "function_name": function_name,
                    "query": query,
                    "accounts_mentioned": accounts_mentioned,
                    "tool_call_id": tool_call.get("id", ""),
                    "arguments": args
                })

            result = {
                "has_function_calls": True,
                "execution_plan": execution_plan,
                "planner_response": planner_resp,
                "raw_response": planner_message.get("content")
            }

            logger.info(
                "Auto function calling plan created",
                user_id=rbac_context.user_id,
                has_function_calls=result["has_function_calls"],
                total_steps=len(execution_plan)
            )

            return result

        except Exception as e:
            logger.error(
                "Auto function calling planning failed",
                user_id=rbac_context.user_id,
                error=str(e)
            )
            # Return fallback direct response
            return {
                "has_function_calls": False,
                "assistant_message": "I apologize, but I encountered an error while processing your request. Please try again.",
                "raw_response": "I apologize, but I encountered an error while processing your request. Please try again.",
                "execution_plan": [],
                "error": str(e)
            }