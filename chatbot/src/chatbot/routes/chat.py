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

from chatbot.models.message import Message, MessageRole, ConversationTurn, Citation, CitationSource
from chatbot.models.rbac import RBACContext, AccessScope
from chatbot.models.plan import Plan, PlanType
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
        # Step 1: Use Auto Function Calling for planning (required)
        if not planner_service:
            raise RuntimeError("Planner service is required but not available")

        planning_result = await planner_service.plan_with_auto_function_calling(
            user_request=user_message,
            rbac_context=user_context
        )

        execution_metadata["planning_result"] = planning_result
        has_function_calls = planning_result["has_function_calls"]
        execution_plan = planning_result["execution_plan"]

        logger.info(
            "Auto Function Calling completed",
            has_function_calls=has_function_calls,
            total_steps=len(execution_plan)
        )

        # Step 2: Execute the plan
        if not has_function_calls:

            assistant_from_llm = None
            if isinstance(planning_result, dict):
                assistant_from_llm = planning_result.get("assistant_message") or planning_result.get("raw_response")

            if assistant_from_llm:
                assistant_response = assistant_from_llm
            else:
                # Preserve legacy fallback for robustness when the planner gave no usable text
                assistant_response = await _generate_direct_response(user_message, user_context)
            sources = []
            plan_type = "direct"

        else:
            # Iteratively execute planner/tool cycles: execute current plan, then re-call planner
            # with the user question + tool outputs until the planner returns a final assistant message.
            MAX_ITERATIONS = 5
            iteration = 0

            all_results = []
            combined_sources = []
            execution_metadata["execution_steps"] = []

            # Start with the initial planning result
            current_plan = planning_result

            while iteration < MAX_ITERATIONS:
                iteration += 1
                if not current_plan.get("has_function_calls"):
                    # Planner provided a final assistant message; prefer assistant_message, then raw_response.
                    assistant_from_llm = current_plan.get("assistant_message") or current_plan.get("raw_response")
                    if assistant_from_llm:
                        assistant_response = assistant_from_llm
                    else:
                        # No assistant text: combine collected tool results
                        assistant_response = await _combine_sequential_results(all_results, user_message)
                    break

                # Execute each step in the returned execution plan
                for step in current_plan.get("execution_plan", []):
                    step_order = step.get("step_order")
                    function_name = step.get("function_name")
                    accounts_mentioned = step.get("accounts_mentioned")
                    query = step.get("query")

                    logger.info(
                        "Executing function call",
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
                        resolved_accounts = []
                        if accounts_mentioned:
                            try:
                                # In dev_mode, if we have the AccountResolverService_ helper AND the
                                # TF-IDF-based AccountResolverService is available, fit the TF-IDF
                                # filter with the dummy accounts so that subsequent resolution uses
                                # the deterministic demo data.
                                if dev_account_resolver is not None and account_resolver_service is not None:
                                    try:
                                        dummy_accounts = await dev_account_resolver.get_dummy_accounts(user_context)
                                        await account_resolver_service._ensure_tfidf_fitted(dummy_accounts, user_context)
                                    except Exception:
                                        # If anything fails, fall back to using the dev resolver directly
                                        resolved_accounts = await dev_account_resolver.resolve_account_names(accounts_mentioned, user_context)

                                if not resolved_accounts and account_resolver_service:
                                    resolved_accounts = await account_resolver_service.resolve_account_names(
                                        accounts_mentioned, user_context
                                    )
                                # If still empty and dev resolver exists, fall back to it
                                if not resolved_accounts and dev_account_resolver is not None:
                                    resolved_accounts = await dev_account_resolver.resolve_account_names(accounts_mentioned, user_context)

                                step_metadata["resolved_accounts"] = [acc.model_dump() for acc in resolved_accounts]
                                logger.info(
                                    "Accounts resolved for step",
                                    step=step_order,
                                    mentioned=len(accounts_mentioned),
                                    resolved=len(resolved_accounts)
                                )
                            except Exception as e:
                                logger.warning("Account resolution failed for step", step=step_order, error=str(e))

                        # Execute the function call
                        if function_name == "sql_agent" and sql_agent:
                            result = await _execute_sql_agent_step(
                                sql_agent, query, resolved_accounts, user_context
                            )

                        elif function_name == "graph_agent" and graph_agent:
                            result = await _execute_graph_agent_step(
                                graph_agent, query, resolved_accounts, user_context
                            )

                        else:
                            raise RuntimeError(f"Unknown function: {function_name}")

                        # Store step results with raw data for planner
                        step_result = {
                            "step_order": step_order,
                            "function_name": function_name,
                            "result": result,
                        }
                        all_results.append(step_result)

                        # Prepare data to feed back to planner
                        try:
                            raw_json = json.dumps(result, default=str)
                        except Exception:
                            raw_json = str(result)

                        # Feed raw tool result back to planner for natural language generation
                        all_results[-1]["planner_feedback"] = {
                            "raw_result": raw_json,
                            "function_name": function_name,
                            "query": query,
                        }

                        step_metadata["success"] = True
                        step_metadata["result_summary"] = f"Executed {function_name} successfully"

                    except Exception as e:
                        logger.error(
                            "Function call execution failed",
                            step=step_order,
                            function_name=function_name,
                            error=str(e)
                        )
                        step_metadata["success"] = False
                        step_metadata["error"] = str(e)

                        # Add error result but continue with next steps
                        error_result = {
                            "step_order": step_order,
                            "function_name": function_name,
                            "error": str(e),
                            "formatted_response": f"Step {step_order} ({function_name}) encountered an error: {str(e)}"
                        }
                        all_results.append(error_result)

                    execution_metadata["execution_steps"].append(step_metadata)

                # After executing current plan steps, feed tool results back to planner for natural language generation
                conversation_context = []
                for r in all_results:
                    fb = r.get("planner_feedback") or {}
                    raw = fb.get("raw_result")
                    function_name = fb.get("function_name")
                    query = fb.get("query")

                    if raw and function_name:
                        # Create assistant message with tool result for planner to process
                        assistant_message = f"Tool: {function_name}\nQuery: {query}\nResult: {raw}"
                        conversation_context.append({"user_message": user_message, "assistant_message": assistant_message})

                # Re-run planner with new context to see if final assistant text is produced
                try:
                    current_plan = await planner_service.plan_with_auto_function_calling(
                        user_request=user_message,
                        rbac_context=user_context,
                        conversation_context=conversation_context or None
                    )
                except Exception as e:
                    logger.error("Re-planning after tool execution failed", error=str(e))
                    # Stop looping and fallback to combining results
                    assistant_response = await _combine_sequential_results(all_results, user_message)
                    break

            # If loop exited without setting assistant_response, build a fallback
            if not assistant_response:
                assistant_response = await _combine_sequential_results(all_results, user_message)

            sources = []  # Sources will be handled by the planner in natural language response
            plan_type = f"iterative_{len(all_results)}_steps"

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




async def _execute_sql_agent_step(sql_agent, query: str, resolved_accounts, rbac_context):
    """Execute a single SQL agent step."""
    # Convert resolved accounts to the format expected by sql_agent
    account_ids = [acc.id for acc in resolved_accounts] if resolved_accounts else []

    # Call the SQL agent function directly
    return await sql_agent.sql_agent(
        query=query,
        accounts_mentioned=account_ids
    )


async def _execute_graph_agent_step(graph_agent, query: str, resolved_accounts, rbac_context):
    """Execute a single Graph agent step."""
    # Convert resolved accounts to the format expected by graph_agent
    account_ids = [acc.id for acc in resolved_accounts] if resolved_accounts else []

    # Call the Graph agent function directly
    return await graph_agent.graph_agent(
        query=query,
        accounts_mentioned=account_ids
    )


async def _combine_sequential_results(all_results, user_message: str) -> str:
    """Combine results from sequential function calls into a coherent response."""
    if not all_results:
        return "I wasn't able to process your request. Please try again."

    # Collect all tool results for summarization
    tool_summaries = []

    for i, result in enumerate(all_results, 1):
        function_name = result.get("function_name", "unknown")

        if "error" in result:
            tool_summaries.append(f"Step {i} ({function_name}): Error - {result.get('error', 'Unknown error')}")
        else:
            raw_result = result.get("result", {})
            # Create a brief summary of the result
            if isinstance(raw_result, dict):
                data_count = len(raw_result.get("data", []))
                if data_count > 0:
                    tool_summaries.append(f"Step {i} ({function_name}): Found {data_count} results")
                else:
                    tool_summaries.append(f"Step {i} ({function_name}): No data found")
            else:
                tool_summaries.append(f"Step {i} ({function_name}): Completed")

    # Create a basic combined response
    response_parts = [
        f"I've processed your request using {len(all_results)} tool(s):",
        "\n".join(f"• {summary}" for summary in tool_summaries),
        "\nFor detailed information, please refer to the specific results above."
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