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

    assistant_response = ""
    sources = []
    usage = {}
    execution_metadata = {"turn_id": turn_id}
    plan_type = "unknown"

    try:
        # Step 1: Simple plan determination based on keywords
        plan_type, should_use_sql, should_use_graph = await _determine_plan_type(user_message)
        execution_metadata["plan_type"] = plan_type

        logger.info("Plan determined", plan_type=plan_type, use_sql=should_use_sql, use_graph=should_use_graph)

        # Step 2: Resolve accounts if agents will be used
        resolved_accounts = []
        if (should_use_sql or should_use_graph) and account_resolver_service:
            try:
                resolved_accounts = await account_resolver_service.resolve_accounts_from_query(user_message, user_context)
                execution_metadata["resolved_accounts"] = [acc.model_dump() for acc in resolved_accounts]
                logger.info("Accounts resolved", count=len(resolved_accounts))
            except Exception as e:
                logger.warning("Account resolution failed", error=str(e))

        # Step 3: Execute based on plan type
        if plan_type == "direct":
            assistant_response = await _generate_direct_response(user_message, user_context)
            sources = []

        elif plan_type == "sql" and should_use_sql and sql_agent:
            sql_result = await sql_agent.execute_query(user_message, user_context, resolved_accounts)
            assistant_response, sql_sources = await _format_sql_response(sql_result, user_message)
            sources.extend(sql_sources)

        elif plan_type == "graph" and should_use_graph and graph_agent:
            graph_result = await graph_agent.execute_query(user_message, user_context, resolved_accounts)
            assistant_response, graph_sources = await _format_graph_response(graph_result, user_message)
            sources.extend(graph_sources)

        elif plan_type == "hybrid" and should_use_sql and should_use_graph and sql_agent and graph_agent:
            try:
                sql_result = await sql_agent.execute_query(user_message, user_context, resolved_accounts)
                graph_result = await graph_agent.execute_query(user_message, user_context, resolved_accounts)

                assistant_response, combined_sources = await _format_hybrid_response(sql_result, graph_result, user_message)
                sources.extend(combined_sources)
            except Exception as e:
                logger.error("Hybrid execution failed", error=str(e))
                assistant_response = f"I encountered an error while retrieving information: {str(e)}"

        else:
            # Fallback to direct response
            assistant_response = await _generate_direct_response(user_message, user_context)
            plan_type = "fallback"

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


async def _determine_plan_type(user_message: str) -> tuple[str, bool, bool]:
    """Determine plan type based on user message keywords."""
    message_lower = user_message.lower()

    # Check for SQL-related keywords
    sql_keywords = ["sales", "revenue", "opportunity", "performance", "data", "amount", "count", "total", "sum"]
    has_sql_intent = any(keyword in message_lower for keyword in sql_keywords)

    # Check for Graph-related keywords
    graph_keywords = ["contact", "relationship", "who", "associated", "connection", "document", "contract"]
    has_graph_intent = any(keyword in message_lower for keyword in graph_keywords)

    # Check for conversational keywords
    conversational_keywords = ["hello", "hi", "hey", "thanks", "thank you", "help", "what can you do"]
    is_conversational = any(keyword in message_lower for keyword in conversational_keywords)

    if is_conversational:
        return "direct", False, False
    elif has_sql_intent and has_graph_intent:
        return "hybrid", True, True
    elif has_sql_intent:
        return "sql", True, False
    elif has_graph_intent:
        return "graph", False, True
    else:
        return "direct", False, False


async def _generate_direct_response(query: str, rbac_context: RBACContext) -> str:
    """Generate direct response for conversational queries."""
    query_lower = query.lower()

    if any(greeting in query_lower for greeting in ["hello", "hi", "hey", "good morning", "good afternoon"]):
        return "Hello! I'm your Salesforce Q&A assistant. I can help you find information about accounts, opportunities, contacts, and sales data. What would you like to know?"

    elif any(thanks in query_lower for thanks in ["thank", "thanks"]):
        return "You're welcome! I'm here to help with your Salesforce data and business questions anytime. Feel free to ask about accounts, opportunities, contacts, or sales analytics."

    else:
        return "I'm a specialized Salesforce Q&A assistant focused on helping with business data, accounts, opportunities, and sales analytics. How can I help you with your Salesforce data today?"


async def _format_sql_response(sql_result: Dict[str, Any], user_query: str) -> tuple[str, List[Dict[str, Any]]]:
    """Format SQL agent result into natural language response with sources."""
    if not sql_result or sql_result.get("error"):
        return "I couldn't retrieve the requested data from the database. Please try rephrasing your question.", []

    # Extract data and metadata
    data = sql_result.get("data", [])
    query_executed = sql_result.get("query", "")
    table_info = sql_result.get("tables_used", [])

    if not data:
        return "No data was found matching your query.", []

    # Generate natural language response
    response_parts = []

    if len(data) == 1:
        response_parts.append("Here's what I found:")
    else:
        response_parts.append(f"I found {len(data)} results:")

    # Format data into readable text
    for i, row in enumerate(data[:5]):  # Limit to 5 rows for readability
        if isinstance(row, dict):
            row_text = ", ".join([f"{k}: {v}" for k, v in row.items() if v is not None])
            response_parts.append(f"• {row_text}")

    if len(data) > 5:
        response_parts.append(f"... and {len(data) - 5} more results")

    # Create sources
    sources = []
    for table in table_info:
        sources.append({
            "type": "sql",
            "title": f"Database Table: {table}",
            "content": query_executed,
            "metadata": {"table_name": table, "rows_returned": len(data)}
        })

    return "\n".join(response_parts), sources


async def _format_graph_response(graph_result: Dict[str, Any], user_query: str) -> tuple[str, List[Dict[str, Any]]]:
    """Format Graph agent result into natural language response with sources."""
    if not graph_result or graph_result.get("error"):
        return "I couldn't retrieve the requested relationship data. Please try rephrasing your question.", []

    # Extract data and metadata
    relationships = graph_result.get("relationships", [])
    documents = graph_result.get("documents", [])
    query_executed = graph_result.get("query", "")

    if not relationships and not documents:
        return "No relationships or documents were found matching your query.", []

    # Generate natural language response
    response_parts = []

    if relationships:
        response_parts.append(f"I found {len(relationships)} relationship(s):")
        for rel in relationships[:3]:  # Limit for readability
            if isinstance(rel, dict):
                from_entity = rel.get("from", "Unknown")
                to_entity = rel.get("to", "Unknown")
                rel_type = rel.get("relationship", "connected to")
                response_parts.append(f"• {from_entity} {rel_type} {to_entity}")

    if documents:
        response_parts.append(f"\nRelated documents ({len(documents)}):")
        for doc in documents[:3]:  # Limit for readability
            if isinstance(doc, dict):
                doc_name = doc.get("name", "Document")
                doc_summary = doc.get("summary", "No summary available")
                response_parts.append(f"• {doc_name}: {doc_summary}")

    # Create sources
    sources = []
    if relationships:
        sources.append({
            "type": "graph",
            "title": "Relationship Data",
            "content": query_executed,
            "metadata": {"relationships_count": len(relationships)}
        })

    for doc in documents:
        if isinstance(doc, dict) and doc.get("url"):
            sources.append({
                "type": "document",
                "title": doc.get("name", "Document"),
                "content": doc.get("summary", ""),
                "url": doc.get("url"),
                "metadata": doc
            })

    return "\n".join(response_parts), sources


async def _format_hybrid_response(sql_result: Dict[str, Any], graph_result: Dict[str, Any], user_query: str) -> tuple[str, List[Dict[str, Any]]]:
    """Format combined SQL and Graph results into natural language response."""
    sql_response, sql_sources = await _format_sql_response(sql_result, user_query)
    graph_response, graph_sources = await _format_graph_response(graph_result, user_query)

    # Combine responses
    response_parts = []

    if sql_response and "No data was found" not in sql_response and "couldn't retrieve" not in sql_response:
        response_parts.append("**Data Summary:**")
        response_parts.append(sql_response)

    if graph_response and "No relationships" not in graph_response and "couldn't retrieve" not in graph_response:
        if response_parts:
            response_parts.append("\n**Relationships & Documents:**")
        response_parts.append(graph_response)

    if not response_parts:
        return "I couldn't find any relevant data or relationships for your query. Please try rephrasing your question.", []

    combined_response = "\n".join(response_parts)
    combined_sources = sql_sources + graph_sources

    return combined_response, combined_sources


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