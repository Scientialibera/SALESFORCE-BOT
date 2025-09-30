"""
Simplified planner service using only Azure OpenAI function calling.

This service handles plan creation and tool selection without Semantic Kernel.
"""

from typing import Any, Dict, List, Optional, Tuple
import json
import structlog

from chatbot.repositories.agent_functions_repository import AgentFunctionsRepository
from chatbot.repositories.prompts_repository import PromptsRepository
from chatbot.models.rbac import RBACContext

logger = structlog.get_logger(__name__)


def collect_tool_calls(message: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Collect tool calls from a message, handling None values properly."""
    calls: List[Dict[str, Any]] = []
    if not isinstance(message, dict):
        return calls
    if message.get("tool_calls"):
        calls.extend(message["tool_calls"] or [])
    elif message.get("function_call"):
        calls.append(message["function_call"])
    return calls


def get_call_name_args(tc: Dict[str, Any]) -> Tuple[Optional[str], str]:
    """Extract function name and arguments from a tool call."""
    if "function" in tc and isinstance(tc["function"], dict):
        return tc["function"].get("name"), tc["function"].get("arguments") or "{}"
    return tc.get("name"), tc.get("arguments") or "{}"


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
            planner_tools = [{"type": "function", "function": fd} for fd in planner_function_defs] if planner_function_defs else None

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
            if conversation_context and len(conversation_context) > 0:
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
                tools=planner_tools,
                tool_choice="auto" if planner_tools else None,
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

    async def plan_with_run_until_done_loop(
        self,
        user_request: str,
        rbac_context: RBACContext,
        conversation_context: Optional[List[Dict[str, Any]]] = None,
        max_rounds: int = 8,
    ) -> Dict[str, Any]:
        """
        Plan using run-until-done loop where planner can make multiple rounds.

        This implements the full agentic flow from the test file:
        1. Planner makes tool calls
        2. Agent results are injected back into conversation
        3. Loop continues until planner returns final answer

        Args:
            user_request: User's natural language request
            rbac_context: User's RBAC context
            conversation_context: Optional conversation history
            max_rounds: Maximum planning rounds to prevent runaway loops

        Returns:
            Dictionary with final response and execution metadata
        """
        try:
            # Get available agents (functions whose name ends with '_agent')
            all_defs = await self.agent_functions_repo.list_all_functions()
            logger.info(f"Retrieved {len(all_defs) if all_defs else 0} function definitions")

            agents = [a for a in all_defs if getattr(a, "name", "").endswith("_agent")] if all_defs else []
            logger.info(f"Found {len(agents)} agent functions")

            # Build planner function definitions - each agent is a function
            planner_function_defs = []
            for agent in agents:
                agent_name = getattr(agent, "name", None)
                if agent_name:
                    planner_function_defs.append({
                        "name": agent_name,
                        "description": getattr(agent, "description", "") or f"Agent {agent_name}",
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
                    logger.info(f"Added agent function definition: {agent_name}")

            logger.info(f"Built {len(planner_function_defs)} planner function definitions")

            # Convert to tools format for Azure OpenAI
            planner_tools = [{"type": "function", "function": fd} for fd in planner_function_defs] if planner_function_defs else None
            logger.info(f"Planner tools: {len(planner_tools) if planner_tools else 0} tools")

            # Get planner system prompt
            try:
                planner_system = await self.prompts_repo.get_system_prompt("planner_system")
            except Exception as e:
                logger.error("Failed to get planner system prompt", error=str(e))
                planner_system = "You are a planner service for a Salesforce Q&A chatbot. Choose the appropriate agent to handle the user request."

            # Initialize conversation with system prompt and user request
            conversation_msgs = [
                {"role": "system", "content": planner_system},
                {"role": "user", "content": user_request},
            ]

            # Add conversation context if provided
            if conversation_context and len(conversation_context) > 0:
                logger.info(f"Adding conversation context: {len(conversation_context)} turns")
                for turn in conversation_context[-3:]:  # Last 3 turns
                    if isinstance(turn, dict):
                        user_msg = turn.get("user_message", "")
                        assistant_msg = turn.get("assistant_message", "")
                        if user_msg:
                            conversation_msgs.insert(-1, {"role": "user", "content": user_msg})
                        if assistant_msg:
                            conversation_msgs.insert(-1, {"role": "assistant", "content": assistant_msg})
            else:
                logger.info("No conversation context provided")

            round_num = 0
            execution_metadata = {
                "rounds": [],
                "total_agent_calls": 0,
                "final_round": None
            }

            # Run-until-done loop: keep asking the planner until it returns a message with no tool calls
            while True:
                round_num += 1

                if round_num > max_rounds:
                    logger.warning(f"Reached max_rounds ({max_rounds}); stopping loop")
                    break

                # Call planner with full toolset each round
                try:
                    planner_resp = await self.aoai_client.create_chat_completion(
                        messages=conversation_msgs,
                        tools=planner_tools,
                        tool_choice="auto" if planner_tools else None,
                    )
                except Exception as e:
                    logger.error(f"Planner call failed (round {round_num})", error=str(e))
                    break

                planner_message = (planner_resp.get("choices") or [{}])[0].get("message", {})
                planner_calls = collect_tool_calls(planner_message)

                round_metadata = {
                    "round": round_num,
                    "tool_calls_count": len(planner_calls),
                    "planner_content": planner_message.get("content"),
                    "agent_executions": []
                }

                # Add planner's assistant content to conversation (preserve prior rounds)
                if planner_message.get("content"):
                    conversation_msgs.append({"role": "assistant", "content": planner_message["content"]})

                # If planner returned no tool calls, we are done
                if not planner_calls:
                    if planner_message.get("content"):
                        execution_metadata["final_round"] = round_num
                        execution_metadata["rounds"].append(round_metadata)
                        return {
                            "has_function_calls": False,
                            "assistant_message": planner_message["content"],
                            "execution_metadata": execution_metadata,
                            "final_answer": True
                        }
                    break

                # Execute the agent requests from this round
                agent_exec_records = []
                for tool_call in planner_calls:
                    agent_name, tc_args_raw = get_call_name_args(tool_call)

                    if not agent_name or not agent_name.endswith("_agent"):
                        continue

                    try:
                        args = json.loads(tc_args_raw or "{}")
                    except json.JSONDecodeError:
                        args = {}

                    agent_query = args.get("query", user_request)
                    accounts_mentioned = args.get("accounts_mentioned")

                    agent_exec_metadata = {
                        "agent_name": agent_name,
                        "query": agent_query,
                        "accounts_mentioned": accounts_mentioned,
                        "success": False,
                        "tool_calls": []
                    }

                    try:
                        # Execute agent with tool calling logic from chat.py
                        if agent_name == "sql_agent":
                            result = await self._execute_sql_agent_with_tools(agent_query, accounts_mentioned, rbac_context)
                        elif agent_name == "graph_agent":
                            result = await self._execute_graph_agent_with_tools(agent_query, accounts_mentioned, rbac_context)
                        else:
                            logger.warning(f"Unknown agent: {agent_name}")
                            continue

                        # Record agent execution for planner injection
                        exec_record = {"agent_name": agent_name, "tool_calls": []}
                        if isinstance(result, dict) and isinstance(result.get("tool_calls"), list):
                            for r in result["tool_calls"]:
                                # Summarized version for planner injection
                                exec_record["tool_calls"].append({
                                    "function": r.get("tool_name", agent_name),
                                    "request": {"query": r.get("query", agent_query)},
                                    "response": self._summarize_query_result(r)
                                })
                                # Full version for metadata storage with complete results
                                agent_exec_metadata["tool_calls"].append({
                                    "tool_name": r.get("tool_name"),
                                    "success": r.get("success", False),
                                    "query": r.get("query", agent_query),
                                    "row_count": r.get("row_count", 0),
                                    "error": r.get("error", None),
                                    "source": r.get("source", None),
                                    "data": r.get("data", None),  # Store full data
                                    "bindings": r.get("bindings", None),  # For graph queries
                                })
                        else:
                            # Backwards-compatible single-result shape
                            exec_record["tool_calls"].append({
                                "function": result.get("tool_name", agent_name),
                                "request": {"query": agent_query},
                                "response": self._summarize_query_result(result)
                            })
                            # Full version for metadata storage
                            agent_exec_metadata["tool_calls"].append({
                                "tool_name": result.get("tool_name"),
                                "success": result.get("success", False),
                                "query": agent_query,
                                "row_count": result.get("row_count", 0),
                                "error": result.get("error", None),
                                "source": result.get("source", None),
                                "data": result.get("data", None),  # Store full data
                                "bindings": result.get("bindings", None),  # For graph queries
                            })

                        agent_exec_records.append(exec_record)
                        agent_exec_metadata["success"] = True
                        execution_metadata["total_agent_calls"] += 1

                    except Exception as e:
                        logger.error(f"Agent execution failed ({agent_name})", error=str(e))
                        # Add error record but continue
                        error_record = {
                            "agent_name": agent_name,
                            "tool_calls": [{
                                "function": agent_name,
                                "request": {"query": agent_query},
                                "response": {"success": False, "error": str(e)}
                            }]
                        }
                        agent_exec_records.append(error_record)
                        agent_exec_metadata["error"] = str(e)

                    round_metadata["agent_executions"].append(agent_exec_metadata)

                # Inject THIS ROUND'S agent summaries back to planner and continue conversation
                if agent_exec_records:
                    injected_md = self._build_agent_summary_markdown(agent_exec_records)
                    conversation_msgs.append({"role": "assistant", "content": injected_md})

                # Nudge the planner to continue planning or finalize
                conversation_msgs.append({
                    "role": "user",
                    "content": "Using the information above, continue the plan or provide the final answer."
                })

                execution_metadata["rounds"].append(round_metadata)

            # If we exit the loop without a final answer, generate fallback response
            logger.warning(f"Loop ended without final answer after {round_num} rounds")
            execution_metadata["final_round"] = round_num

            return {
                "has_function_calls": False,
                "assistant_message": "I've processed your request but encountered some complexity. Please try asking in a different way.",
                "execution_metadata": execution_metadata,
                "final_answer": False,
                "timeout": True
            }

        except Exception as e:
            import traceback
            logger.error(
                "Run-until-done planning failed",
                user_id=rbac_context.user_id,
                error=str(e),
                traceback=traceback.format_exc()
            )
            return {
                "has_function_calls": False,
                "assistant_message": "I apologize, but I encountered an error while processing your request. Please try again.",
                "execution_metadata": {"error": str(e)},
                "error": str(e)
            }

    async def _execute_sql_agent_with_tools(self, query: str, accounts_mentioned, rbac_context):
        """Execute SQL agent using the same logic as in chat.py."""
        # Import here to avoid circular imports
        from chatbot.app import app_state
        from chatbot.services.account_resolver_service import AccountResolverService_

        # Get agent functions and system prompt
        agent_funcs_repo = app_state.agent_functions_repository
        prompts_repo = app_state.prompts_repository
        aoai_client = app_state.aoai_client
        sql_service = app_state.sql_service

        agent_name = "sql_agent"

        # Get agent system prompt
        try:
            agent_system = await prompts_repo.get_system_prompt(f"{agent_name}_system")
        except Exception:
            agent_system = "You are a SQL agent for querying sales data."

        # Resolve accounts if mentioned
        resolved_account_names = []
        if accounts_mentioned:
            try:
                resolved_accounts = await AccountResolverService_.resolve_account_names(accounts_mentioned, rbac_context)
                for acc in resolved_accounts:
                    if hasattr(acc, 'name') and acc.name:
                        resolved_account_names.append(acc.name)
                    elif isinstance(acc, dict) and acc.get('name'):
                        resolved_account_names.append(acc['name'])
            except Exception as e:
                logger.warning("Account resolution failed", error=str(e))

        # Append resolved account names to system prompt
        if resolved_account_names:
            agent_system = agent_system + "\n\nExact Account name values: " + ",".join(resolved_account_names)

        # Get agent tools
        tools_raw = await agent_funcs_repo.get_functions_by_agent(agent_name)
        if not tools_raw:
            all_funcs = await agent_funcs_repo.list_all_functions()
            tools_raw = [f for f in all_funcs if agent_name in getattr(f, 'name', '') or
                         agent_name in (getattr(f, 'metadata', {}) or {}).get('agents', [])]

        # Build agent tools
        agent_tools = []
        for t in tools_raw:
            if not getattr(t, "name", None) or not getattr(t, "parameters", None):
                continue
            if not agent_name in getattr(t, "name", "") and agent_name not in (getattr(t, 'metadata', {}) or {}).get('agents', []):
                continue
            agent_tools.append({
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": getattr(t, "description", "") or "",
                    "parameters": t.parameters,
                }
            })

        # Call agent with tools
        agent_messages = [
            {"role": "system", "content": agent_system},
            {"role": "user", "content": query},
        ]

        agent_resp = await aoai_client.create_chat_completion(
            messages=agent_messages,
            tools=agent_tools,
            tool_choice="auto",
        )

        # Extract tool calls and execute all of them
        agent_msg = (agent_resp.get("choices") or [{}])[0].get("message", {})
        tool_calls = agent_msg.get("tool_calls", [])

        results = []
        for tool_call in tool_calls:
            function_info = tool_call.get("function", {})

            try:
                args = json.loads(function_info.get("arguments", "{}"))
            except Exception:
                args = {}

            # Execute SQL service
            base_query = args.get("query") or query
            sql_result = await sql_service.execute_query(base_query, rbac_context)

            results.append({
                "tool_name": function_info.get("name", "sql_agent_function"),
                "success": getattr(sql_result, "success", True),
                "row_count": getattr(sql_result, "row_count", 0),
                "error": getattr(sql_result, "error", None),
                "source": "sql",
                "query": base_query,
                "data": getattr(sql_result, "data", None)
            })

        if results:
            return {"tool_calls": results}

        return {"success": False, "error": "No tool calls made", "tool_calls": []}

    async def _execute_graph_agent_with_tools(self, query: str, accounts_mentioned, rbac_context):
        """Execute Graph agent using the same logic as in chat.py."""
        # Import here to avoid circular imports
        from chatbot.app import app_state
        from chatbot.services.account_resolver_service import AccountResolverService_

        # Get agent functions and system prompt
        agent_funcs_repo = app_state.agent_functions_repository
        prompts_repo = app_state.prompts_repository
        aoai_client = app_state.aoai_client
        graph_service = app_state.graph_service

        agent_name = "graph_agent"

        # Get agent system prompt
        try:
            agent_system = await prompts_repo.get_system_prompt(f"{agent_name}_system")
        except Exception:
            agent_system = "You are a graph agent for querying account relationships."

        # Resolve accounts if mentioned
        resolved_account_names = []
        if accounts_mentioned:
            try:
                resolved_accounts = await AccountResolverService_.resolve_account_names(accounts_mentioned, rbac_context)
                for acc in resolved_accounts:
                    if hasattr(acc, 'name') and acc.name:
                        resolved_account_names.append(acc.name)
                    elif isinstance(acc, dict) and acc.get('name'):
                        resolved_account_names.append(acc['name'])
            except Exception as e:
                logger.warning("Account resolution failed", error=str(e))

        # Append resolved account names to system prompt
        if resolved_account_names:
            agent_system = agent_system + "\n\nExact Account name values: " + ",".join(resolved_account_names)

        # Get agent tools
        tools_raw = await agent_funcs_repo.get_functions_by_agent(agent_name)
        if not tools_raw:
            all_funcs = await agent_funcs_repo.list_all_functions()
            tools_raw = [f for f in all_funcs if agent_name in getattr(f, 'name', '') or
                         agent_name in (getattr(f, 'metadata', {}) or {}).get('agents', [])]

        # Build agent tools
        agent_tools = []
        for t in tools_raw:
            if not getattr(t, "name", None) or not getattr(t, "parameters", None):
                continue
            if not agent_name in getattr(t, "name", "") and agent_name not in (getattr(t, 'metadata', {}) or {}).get('agents', []):
                continue
            agent_tools.append({
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": getattr(t, "description", "") or "",
                    "parameters": t.parameters,
                }
            })

        # Call agent with tools
        agent_messages = [
            {"role": "system", "content": agent_system},
            {"role": "user", "content": query},
        ]

        agent_resp = await aoai_client.create_chat_completion(
            messages=agent_messages,
            tools=agent_tools,
            tool_choice="auto",
        )

        # Extract tool calls and execute all of them
        agent_msg = (agent_resp.get("choices") or [{}])[0].get("message", {})
        tool_calls = agent_msg.get("tool_calls", [])

        results = []
        for tool_call in tool_calls:
            function_info = tool_call.get("function", {})

            try:
                args = json.loads(function_info.get("arguments", "{}"))
            except Exception:
                args = {}

            # Execute Graph service
            g_query = args.get("query") or query
            g_bindings = args.get("bindings") or {}
            graph_result = await graph_service.execute_query(g_query, rbac_context, bindings=g_bindings)

            results.append({
                "tool_name": function_info.get("name", "graph_agent_function"),
                "success": getattr(graph_result, "success", True),
                "row_count": getattr(graph_result, "row_count", 0),
                "error": getattr(graph_result, "error", None),
                "source": "gremlin",
                "query": g_query,
                "bindings": g_bindings,
                "data": getattr(graph_result, "data", None)
            })

        if results:
            return {"tool_calls": results}

        return {"success": False, "error": "No tool calls made", "tool_calls": []}

    def _summarize_query_result(self, qr: Any) -> Dict[str, Any]:
        """Return a small, planner-friendly summary of a QueryResult-like object."""
        out = {
            "success": qr.get("success", None),
            "row_count": qr.get("row_count", None),
            "error": qr.get("error", None),
        }

        data = qr.get("data", None)
        if data is not None:
            if hasattr(data, "rows"):
                rows = getattr(data, "rows", None)
                out["sample_rows"] = rows[:5] if isinstance(rows, list) else None
            elif isinstance(data, list):
                out["sample_rows"] = data[:5]

            out["source"] = qr.get("source", None)
            out["query"] = qr.get("query", None)

            if hasattr(data, "columns"):
                cols = getattr(data, "columns", None)
                if cols:
                    out["columns"] = [getattr(c, "name", str(c)) for c in cols]

        return out

    def _build_agent_summary_markdown(self, agent_exec_records) -> str:
        """Build the content we inject back to the planner."""
        lines = []
        lines.append("### Its agent requests")
        if not agent_exec_records:
            lines.append("- (no agent requests issued)")
        else:
            for rec in agent_exec_records:
                lines.append(f"- **Agent**: `{rec.get('agent_name')}`")
                for call in rec.get("tool_calls", []):
                    lines.append(f"  - **Tool**: `{call.get('function')}`")
                    req = call.get('request', {})
                    lines.append(f"    - **Arguments**: `{json.dumps(req, default=str)}`")

        lines.append("\n######Response from agents#######")
        if not agent_exec_records:
            lines.append("(no agent responses)")
        else:
            for rec in agent_exec_records:
                lines.append(f"- **Agent**: `{rec.get('agent_name')}`")
                for call in rec.get("tool_calls", []):
                    lines.append(f"  - **Tool**: `{call.get('function')}`")
                    resp = call.get("response") or {}
                    lines.append("    - **Summary**:")
                    lines.append("      ```json")
                    lines.append(json.dumps({
                        "success": resp.get("success"),
                        "row_count": resp.get("row_count"),
                        "error": resp.get("error"),
                        "columns": resp.get("columns"),
                        "sample_rows": resp.get("sample_rows"),
                    }, indent=2, default=str))
                    lines.append("      ```")

        return "\n".join(lines)

    async def generate_final_response(
        self,
        user_request: str,
        agent_summary: str,
        rbac_context: RBACContext,
    ) -> Dict[str, Any]:
        """
        Generate final response after agent execution (MVP pattern).

        This method takes the user request and agent execution summary,
        then asks the planner to provide a final natural language response.

        Args:
            user_request: Original user request
            agent_summary: Markdown summary of agent requests and responses
            rbac_context: User's RBAC context

        Returns:
            Dictionary with final assistant response
        """
        try:
            # Get planner system prompt
            try:
                planner_system = await self.prompts_repo.get_system_prompt("planner_system")
            except Exception as e:
                logger.error("Failed to get planner system prompt", error=str(e))
                planner_system = "You are a planner service for a Salesforce Q&A chatbot. Provide comprehensive responses based on the data retrieved by your agents."

            # Build conversation with agent results injected (MVP pattern)
            planner_messages = [
                {"role": "system", "content": planner_system},
                {"role": "user", "content": user_request},
                {"role": "assistant", "content": agent_summary},
                {"role": "user", "content": "Using the information above, provide the final answer to the user."}
            ]

            # Call planner for final response (no tools needed)
            final_resp = await self.aoai_client.create_chat_completion(
                messages=planner_messages,
                tools=None,
                tool_choice=None,
            )

            # Extract final response
            final_message = (final_resp.get("choices") or [{}])[0].get("message", {})
            assistant_content = final_message.get("content", "")

            logger.info(
                "Generated final response",
                user_id=rbac_context.user_id,
                response_length=len(assistant_content)
            )

            return {
                "assistant_message": assistant_content,
                "raw_response": final_resp
            }

        except Exception as e:
            logger.error(
                "Final response generation failed",
                user_id=rbac_context.user_id,
                error=str(e)
            )
            return {
                "assistant_message": "I apologize, but I encountered an error while generating the final response. Please try again.",
                "error": str(e)
            }