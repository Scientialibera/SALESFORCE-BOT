"""Chat router implementing planner-first agentic architecture.

This module implements the sophisticated chat logic where:
1. Planner parses user input and determines execution strategy
2. Account resolver maps account names to IDs with confidence scoring
3. Agents (SQL/Graph) execute queries within RBAC scope
4. Natural language responses are generated from retrieved context
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import uuid4
import json
import structlog
from fastapi import APIRouter, HTTPException, Depends, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt as jose_jwt
from pydantic import BaseModel, Field

from chatbot.models.message import Message, MessageRole, Citation, CitationSource
from chatbot.models.rbac import RBACContext, AccessScope
from chatbot.services.unified_service import UnifiedDataService
from chatbot.config.settings import settings

logger = structlog.get_logger(__name__)

router = APIRouter()
security = HTTPBearer(auto_error=False)


class ChatMessage(BaseModel):
    role: str = Field(..., description="Message role: 'system', 'user', or 'assistant'")
    content: str = Field(..., description="Message content")


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    user_id: str
    session_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    session_id: str
    turn_id: str
    choices: List[Dict[str, Any]]
    usage: Dict[str, int] = Field(default_factory=dict)
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    plan_type: Optional[str] = Field(default=None, description="Type of plan executed")
    execution_time_ms: Optional[int] = Field(default=None, description="Total execution time")


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    request: Request = None,
) -> RBACContext:
    logger.info("Authenticating user request", url=str(request.url) if request else "unknown")

    if credentials and getattr(credentials, "credentials", None):
        token = credentials.credentials
        try:
            claims = jose_jwt.get_unverified_claims(token)
        except Exception:
            claims = {"oid": "user123", "email": "user@example.com", "tid": "tenant123", "roles": ["sales_rep"]}

        return RBACContext(
            user_id=claims.get("email", "user@example.com"),
            email=claims.get("email", "user@example.com"),
            tenant_id=claims.get("tid", "tenant123"),
            object_id=claims.get("oid", "user123"),
            roles=claims.get("roles", ["sales_rep"]),
            access_scope=AccessScope(),
        )

    return RBACContext(
        user_id="user@example.com",
        email="user@example.com",
        tenant_id="tenant123",
        object_id="user123",
        roles=["sales_rep"],
        access_scope=AccessScope(),
    )


def get_unified_service() -> UnifiedDataService:
    from chatbot.app import app_state

    uds = getattr(app_state, "unified_data_service", None)
    if not uds:
        raise HTTPException(status_code=503, detail="Unified data service not available")
    return uds


@router.post("/chat", response_model=ChatResponse)
async def send_message(
    request_data: ChatRequest,
    unified_service: UnifiedDataService = Depends(get_unified_service),
    user_context: RBACContext = Depends(get_current_user),
) -> ChatResponse:
    """Process chat message using planner-first agentic architecture."""
    start_time = datetime.utcnow()

    # If no messages provided but a session_id is present, return chat history
    if not request_data.messages or len(request_data.messages) == 0:
        if request_data.session_id:
            chat_ctx = await unified_service.get_chat_context(request_data.session_id, user_context, max_turns=50)
            turns = getattr(chat_ctx, "turns", [])
            choices = []
            for t in turns:
                choices.append({
                    "index": len(choices),
                    "message": {
                        "role": t.assistant_message.role.value if t.assistant_message else "assistant",
                        "content": t.assistant_message.content if t.assistant_message else ""
                    },
                    "finish_reason": "history"
                })
            return ChatResponse(
                session_id=request_data.session_id,
                turn_id="",
                choices=choices,
                usage={},
                sources=[],
                metadata={"history": True}
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No user message provided and no session_id to fetch history")

    # Validate incoming user messages
    user_messages = [m for m in request_data.messages if m.role == "user"]
    if not user_messages:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No user message provided")

    user_message = user_messages[-1].content
    session_id = request_data.session_id or str(uuid4())
    turn_id = str(uuid4())

    logger.info("Processing chat message", session_id=session_id, turn_id=turn_id, user_id=request_data.user_id)

    # Get required services from app state
    from chatbot.app import app_state

    account_resolver_service = getattr(app_state, "account_resolver_service", None)
    sql_agent = getattr(app_state, "sql_agent", None)
    graph_agent = getattr(app_state, "graph_agent", None)
    planner_service = getattr(app_state, "planner_service", None)

    # In dev_mode, prefer the lightweight AccountResolverService_ helper for deterministic accounts
    dev_account_resolver = None
    if settings.dev_mode:
        try:
            from chatbot.services.account_resolver_service import AccountResolverService_ as DevAccountResolver
            dev_account_resolver = DevAccountResolver
        except Exception as e:
            logger.warning("Failed to import dev account resolver", error=str(e))
            dev_account_resolver = None

    assistant_response = ""
    sources = []
    usage = {}
    execution_metadata = {"turn_id": turn_id}
    plan_type = "unknown"

    try:
        # Step 1: Get conversation history for context
        conversation_context = None
        if session_id:
            try:
                chat_ctx = await unified_service.get_chat_context(session_id, user_context, max_turns=3)
                turns = getattr(chat_ctx, "turns", [])
                if turns:
                    conversation_context = []
                    for turn in turns[-3:]:  # Last 3 turns for context
                        if turn.user_message and turn.assistant_message:
                            conversation_context.append({
                                "user_message": turn.user_message.content,
                                "assistant_message": turn.assistant_message.content
                            })
            except Exception as e:
                logger.warning("Failed to retrieve conversation history", error=str(e))

        # Step 2: Use Auto Function Calling for planning (required)
        if not planner_service:
            raise RuntimeError("Planner service is required but not available")

        planning_result = await planner_service.plan_with_auto_function_calling(
            user_request=user_message,
            rbac_context=user_context,
            conversation_context=conversation_context
        )

        execution_metadata["planning_result"] = planning_result
        has_function_calls = planning_result["has_function_calls"]
        execution_plan = planning_result["execution_plan"]

        logger.info(
            "Auto Function Calling completed",
            has_function_calls=has_function_calls,
            total_steps=len(execution_plan)
        )

        # Step 2: Execute the plan using MVP pattern
        if not has_function_calls:
            # Direct response from planner
            assistant_from_llm = None
            if isinstance(planning_result, dict):
                assistant_from_llm = planning_result.get("assistant_message") or planning_result.get("raw_response")

            if assistant_from_llm:
                assistant_response = assistant_from_llm
            else:
                assistant_response = await _generate_direct_response(user_message, user_context)
            sources = []
            plan_type = "direct"

        else:
            # MVP pattern: Execute agents → Collect results → Re-inject to planner for final response
            agent_exec_records = []
            execution_metadata["execution_steps"] = []

            # Execute each agent call in the execution plan
            for step in execution_plan:
                step_order = step.get("step_order")
                function_name = step.get("function_name")
                accounts_mentioned = step.get("accounts_mentioned")
                query = step.get("query")

                logger.info(
                    "Executing agent step",
                    step=step_order,
                    function_name=function_name,
                    accounts_mentioned=accounts_mentioned
                )

                step_metadata = {
                    "step_order": step_order,
                    "function_name": function_name,
                    "accounts_mentioned": accounts_mentioned,
                    "query": query
                }

                try:
                    # Resolve accounts if mentioned
                    resolved_account_names = []
                    if accounts_mentioned:
                        try:
                            if dev_account_resolver is not None:
                                resolved_accounts = await dev_account_resolver.resolve_account_names(accounts_mentioned, user_context)
                            elif account_resolver_service:
                                resolved_accounts = await account_resolver_service.resolve_account_names(
                                    accounts_mentioned, user_context
                                )
                            else:
                                resolved_accounts = []

                            # Extract account names for agent system prompt
                            for acc in resolved_accounts:
                                if hasattr(acc, 'name') and acc.name:
                                    resolved_account_names.append(acc.name)
                                elif isinstance(acc, dict) and acc.get('name'):
                                    resolved_account_names.append(acc['name'])

                            step_metadata["resolved_accounts"] = len(resolved_accounts)
                            logger.info(
                                "Accounts resolved for step",
                                step=step_order,
                                mentioned=len(accounts_mentioned),
                                resolved=len(resolved_accounts)
                            )
                        except Exception as e:
                            logger.warning("Account resolution failed for step", step=step_order, error=str(e))

                    # Execute the agent with tool calling (MVP pattern)
                    if function_name == "sql_agent":
                        result = await _execute_sql_agent_mvp_pattern(
                            query, resolved_account_names, user_context
                        )
                    elif function_name == "graph_agent":
                        result = await _execute_graph_agent_mvp_pattern(
                            query, resolved_account_names, user_context
                        )
                    else:
                        raise RuntimeError(f"Unknown function: {function_name}")

                    # Record agent execution for planner injection
                    exec_record = {
                        "agent_name": function_name,
                        "tool_calls": [{
                            "function": result.get("tool_name", function_name),
                            "request": {"query": query},
                            "response": _summarize_query_result(result)
                        }]
                    }
                    agent_exec_records.append(exec_record)

                    step_metadata["success"] = True
                    step_metadata["result_summary"] = f"Executed {function_name} successfully"

                except Exception as e:
                    logger.error(
                        "Agent execution failed",
                        step=step_order,
                        function_name=function_name,
                        error=str(e)
                    )
                    step_metadata["success"] = False
                    step_metadata["error"] = str(e)

                    # Add error record but continue
                    error_record = {
                        "agent_name": function_name,
                        "tool_calls": [{
                            "function": function_name,
                            "request": {"query": query},
                            "response": {"success": False, "error": str(e)}
                        }]
                    }
                    agent_exec_records.append(error_record)

                execution_metadata["execution_steps"].append(step_metadata)

            # Build agent summary markdown for planner injection (MVP pattern)
            injected_md = _build_agent_summary_markdown(agent_exec_records)

            # Re-call planner with injected agent results for final response
            try:
                final_response = await planner_service.generate_final_response(
                    user_request=user_message,
                    agent_summary=injected_md,
                    rbac_context=user_context
                )
                assistant_response = final_response.get("assistant_message", "")
            except Exception as e:
                logger.error("Final response generation failed", error=str(e))
                assistant_response = await _combine_sequential_results_mvp(agent_exec_records, user_message)

            sources = []
            plan_type = f"agentic_{len(agent_exec_records)}_agents"

    except Exception as e:
        logger.error("Chat processing failed", error=str(e), session_id=session_id)
        assistant_response = "I apologize, but I encountered an error while processing your request. Please try again."
        plan_type = "error"

    # Calculate execution time
    end_time = datetime.utcnow()
    execution_time_ms = int((end_time - start_time).total_seconds() * 1000)
    execution_metadata["execution_time_ms"] = execution_time_ms

    # Handle feedback if provided
    await _handle_feedback(request_data, unified_service, turn_id, user_context)

    # Persist conversation turn
    await _persist_conversation_turn(
        unified_service, session_id, turn_id, user_message, assistant_response,
        user_context, sources, execution_metadata
    )

    # Calculate usage if not provided
    if not usage:
        prompt_tokens = len(user_message.split())
        completion_tokens = len(assistant_response.split())
        usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }

    choices = [
        {"index": 0, "message": {"role": "assistant", "content": assistant_response}, "finish_reason": "stop"}
    ]

    return ChatResponse(
        session_id=session_id,
        turn_id=turn_id,
        choices=choices,
        usage=usage,
        sources=sources,
        metadata=execution_metadata,
        plan_type=plan_type,
        execution_time_ms=execution_time_ms
    )




async def _execute_sql_agent_mvp_pattern(query: str, resolved_account_names, rbac_context):
    """Execute SQL agent using MVP pattern with agent tools."""
    from chatbot.app import app_state

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

    # Append resolved account names to system prompt (MVP pattern)
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

    # Extract tool calls and execute
    agent_msg = (agent_resp.get("choices") or [{}])[0].get("message", {})
    tool_calls = agent_msg.get("tool_calls", [])

    if tool_calls:
        # Execute first tool call (SQL execution)
        tool_call = tool_calls[0]
        function_info = tool_call.get("function", {})

        try:
            args = json.loads(function_info.get("arguments", "{}"))
        except:
            args = {}

        # Execute SQL service
        base_query = args.get("query") or query
        sql_result = await sql_service.execute_query(base_query, rbac_context)

        return {
            "tool_name": function_info.get("name", "sql_agent_function"),
            "success": getattr(sql_result, "success", True),
            "row_count": getattr(sql_result, "row_count", 0),
            "error": getattr(sql_result, "error", None),
            "source": "sql",
            "query": base_query,
            "data": getattr(sql_result, "data", None)
        }

    return {"success": False, "error": "No tool calls made"}


async def _execute_graph_agent_mvp_pattern(query: str, resolved_account_names, rbac_context):
    """Execute Graph agent using MVP pattern with agent tools."""
    from chatbot.app import app_state

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

    # Append resolved account names to system prompt (MVP pattern)
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

    # Extract tool calls and execute
    agent_msg = (agent_resp.get("choices") or [{}])[0].get("message", {})
    tool_calls = agent_msg.get("tool_calls", [])

    if tool_calls:
        # Execute first tool call (Graph execution)
        tool_call = tool_calls[0]
        function_info = tool_call.get("function", {})

        try:
            args = json.loads(function_info.get("arguments", "{}"))
        except:
            args = {}

        # Execute Graph service
        g_query = args.get("query") or query
        g_bindings = args.get("bindings") or {}
        graph_result = await graph_service.execute_query(g_query, rbac_context, bindings=g_bindings)

        return {
            "tool_name": function_info.get("name", "graph_agent_function"),
            "success": getattr(graph_result, "success", True),
            "row_count": getattr(graph_result, "row_count", 0),
            "error": getattr(graph_result, "error", None),
            "source": "gremlin",
            "query": g_query,
            "data": getattr(graph_result, "data", None)
        }

    return {"success": False, "error": "No tool calls made"}


def _summarize_query_result(qr: Any) -> Dict[str, Any]:
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


def _build_agent_summary_markdown(agent_exec_records) -> str:
    """Build the content we inject back to the planner (MVP pattern)."""
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


async def _combine_sequential_results_mvp(agent_exec_records, user_message: str) -> str:
    """Combine results from agent executions into a coherent response (fallback)."""
    if not agent_exec_records:
        return "I wasn't able to process your request. Please try again."

    # Create summary from agent records
    summaries = []
    for rec in agent_exec_records:
        agent_name = rec.get("agent_name", "unknown")
        tool_calls = rec.get("tool_calls", [])

        if tool_calls:
            for call in tool_calls:
                resp = call.get("response", {})
                if resp.get("error"):
                    summaries.append(f"{agent_name}: Error - {resp.get('error')}")
                elif resp.get("success"):
                    row_count = resp.get("row_count", 0)
                    summaries.append(f"{agent_name}: Found {row_count} results")
                else:
                    summaries.append(f"{agent_name}: Completed")

    response_parts = [
        f"I've processed your request using {len(agent_exec_records)} agent(s):",
        "\n".join(f"• {summary}" for summary in summaries)
    ]

    return "\n".join(response_parts)


async def _generate_direct_response(query: str, rbac_context: RBACContext) -> str:
    """Generate direct response for conversational queries."""
    query_lower = query.lower()

    if any(greeting in query_lower for greeting in ["hello", "hi", "hey", "good morning", "good afternoon"]):
        return "Hello! I'm your Salesforce Q&A assistant. I can help you find information about accounts, opportunities, contacts, and sales data. What would you like to know?"

    elif any(thanks in query_lower for thanks in ["thank", "thanks"]):
        return "You're welcome! I'm here to help with your Salesforce data and business questions anytime. Feel free to ask about accounts, opportunities, contacts, or sales analytics."

    else:
        return "I'm a specialized Salesforce Q&A assistant focused on helping with business data, accounts, opportunities, and sales analytics. How can I help you with your Salesforce data today?"






async def _handle_feedback(request_data: ChatRequest, unified_service: UnifiedDataService, turn_id: str, user_context: RBACContext) -> None:
    """Handle feedback submission if provided in metadata."""
    try:
        fb = request_data.metadata.get("feedback") if request_data.metadata else None
        if fb:
            rating = int(fb.get("rating")) if fb.get("rating") is not None else None
            comment = fb.get("comment") if fb.get("comment") is not None else None
            if rating is not None:
                await unified_service.submit_feedback(
                    turn_id=turn_id,
                    user_id=user_context.user_id,
                    rating=rating,
                    comment=comment,
                    metadata={k: v for k, v in request_data.metadata.items() if k != "feedback"}
                )
    except Exception:
        logger.warning("Failed to persist feedback; continuing")


async def _persist_conversation_turn(
    unified_service: UnifiedDataService,
    session_id: str,
    turn_id: str,
    user_message: str,
    assistant_response: str,
    user_context: RBACContext,
    sources: List[Dict[str, Any]],
    execution_metadata: Dict[str, Any]
) -> None:
    """Persist conversation turn to Cosmos DB."""
    try:
        # Create message objects with citations
        user_msg = Message(
            id=f"{turn_id}_user",
            role=MessageRole.USER,
            content=user_message,
            timestamp=datetime.utcnow(),
            user_id=user_context.user_id
        )

        assistant_msg = Message(
            id=f"{turn_id}_assistant",
            role=MessageRole.ASSISTANT,
            content=assistant_response,
            timestamp=datetime.utcnow()
        )

        # Add citations to assistant message
        for source in sources:
            citation_source = CitationSource(
                source_type=source.get("type", "unknown"),
                title=source.get("title", "Unknown Source"),
                url=source.get("url"),
                snippet=source.get("content", "")[:200],
                metadata=source.get("metadata", {})
            )

            citation = Citation(
                id=str(uuid4()),
                sources=[citation_source]
            )

            assistant_msg.add_citation(citation)

        await unified_service.add_conversation_turn(
            chat_id=session_id,
            user_message=user_msg,
            assistant_message=assistant_msg,
            rbac_context=user_context,
            execution_metadata=execution_metadata,
        )
    except Exception as e:
        logger.warning("Failed to persist conversation turn", error=str(e))