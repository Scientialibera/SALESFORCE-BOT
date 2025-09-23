import asyncio
import sys
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure chatbot/src is on path when running this script directly.
file_path = Path(__file__).resolve()
# repo layout: <repo>/chatbot/src/chatbot/tests
repo_root = file_path.parents[4]
chatbot_src = repo_root / "chatbot" / "src"
sys.path.insert(0, str(chatbot_src))

from chatbot.config.settings import settings
from chatbot.clients.cosmos_client import CosmosDBClient
from chatbot.clients.aoai_client import AzureOpenAIClient
from chatbot.repositories.agent_functions_repository import AgentFunctionsRepository
from chatbot.repositories.prompts_repository import PromptsRepository
from chatbot.services.rbac_service import RBACService
from chatbot.services.account_resolver_service import AccountResolverService_
from chatbot.models.rbac import RBACContext, AccessScope
from chatbot.services.sql_service import SQLService
from chatbot.clients.gremlin_client import GremlinClient
from chatbot.services.graph_service import GraphService


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _pretty(obj: Any) -> str:
    try:
        return json.dumps(obj, indent=2, ensure_ascii=False, default=str)
    except Exception:
        return str(obj)

def to_tools(function_defs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{"type": "function", "function": fd} for fd in function_defs]

def collect_tool_calls(message: Dict[str, Any]) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []
    if not isinstance(message, dict):
        return calls
    if message.get("tool_calls"):
        calls.extend(message["tool_calls"] or [])
    elif message.get("function_call"):
        calls.append(message["function_call"])
    return calls

def get_call_name_args(tc: Dict[str, Any]) -> Tuple[Optional[str], str]:
    if "function" in tc and isinstance(tc["function"], dict):
        return tc["function"].get("name"), tc["function"].get("arguments") or "{}"
    return tc.get("name"), tc.get("arguments") or "{}"

def is_agent_call(tc: Dict[str, Any]) -> bool:
    name, _ = get_call_name_args(tc)
    return isinstance(name, str) and name.endswith("_agent")

def summarize_query_result(qr: Any, max_rows: int = 5) -> Dict[str, Any]:
    """Return a small, planner-friendly summary of a QueryResult-like object."""
    out: Dict[str, Any] = {
        "success": getattr(qr, "success", None),
        "row_count": getattr(qr, "row_count", None),
        "error": getattr(qr, "error", None),
    }
    data = getattr(qr, "data", None)
    if data is not None:
        rows = getattr(data, "rows", None)
        out["sample_rows"] = rows[:max_rows] if isinstance(rows, list) else None
        out["source"] = getattr(data, "source", None)
        out["query"] = getattr(data, "query", None)
        cols = getattr(data, "columns", None)
        if cols:
            out["columns"] = [getattr(c, "name", str(c)) for c in cols]
    return out

def build_agent_summary_markdown(agent_exec_records: List[Dict[str, Any]]) -> str:
    """
    Build the content we inject back to the planner, containing:
    1) Its agent requests
    2) ######Response from agents#######
    """
    lines: List[str] = []
    lines.append("### Its agent requests")
    if not agent_exec_records:
        lines.append("- (no agent requests issued)")
    else:
        for rec in agent_exec_records:
            lines.append(f"- **Agent**: `{rec.get('agent_name')}`")
            for call in rec.get("tool_calls", []):
                lines.append(f"  - **Tool**: `{call.get('function')}`")
                lines.append(f"    - **Arguments**: `{_pretty(call.get('request') or {})}`")

    lines.append("\n######Response from agents#######")
    if not agent_exec_records:
        lines.append("(no agent responses)")
    else:
        for rec in agent_exec_records:
            lines.append(f"- **Agent**: `{rec.get('agent_name')}`")
            for call in rec.get("tool_calls", []):
                lines.append(f"  - **Tool**: `{call.get('function')}`")
                resp = call.get("response") or {}
                # Keep this compact to avoid blowing token budgets:
                lines.append("    - **Summary**:")
                lines.append("      ```json")
                lines.append(_pretty({
                    "success": resp.get("success"),
                    "row_count": resp.get("row_count"),
                    "error": resp.get("error"),
                    "columns": resp.get("columns"),
                    "sample_rows": resp.get("sample_rows"),
                }))
                lines.append("      ```")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

async def run_test():
    print("Starting agentic chatbot test (planner → agents → tool exec → inject → planner final)")

    # Initialize infra
    cosmos_client = CosmosDBClient(settings.cosmos_db)
    agent_funcs_repo = AgentFunctionsRepository(
        cosmos_client,
        settings.cosmos_db.database_name,
        settings.cosmos_db.agent_functions_container,
    )
    prompts_repo = PromptsRepository(
        cosmos_client,
        settings.cosmos_db.database_name,
        settings.cosmos_db.prompts_container,
    )
    aoai_client = AzureOpenAIClient(settings.azure_openai)

    rbac_settings = settings.rbac
    rbac_service = RBACService(rbac_settings)  # kept for parity
    rbac_ctx = RBACContext(
        user_id="test_user",
        email="test_user@example.com",
        tenant_id="test-tenant",
        object_id="test-object-id",
        roles=["admin"],
        permissions=set(),
        access_scope=AccessScope(),
        is_admin=True,
    )

    # Graph + SQL services
    gremlin_client = GremlinClient(settings.gremlin)
    graph_service = GraphService(gremlin_client=gremlin_client, dev_mode=True)
    sql_service = SQLService(
        aoai_client,
        None,
        None,
        None,
        settings.fabric_lakehouse,
        dev_mode=True,
    )

    # Test queries
    test_queries = [
        "How are you?",
        "All sales for Microsoft and its account relationships",
        "All sales",
    ]

    out_file = repo_root / "chatbot_agentic_test_results.md"
    md_lines = ["# Agentic Test Results\n"]

    try:
        # Discover available agents (docs whose name ends with '_agent')
        all_defs = await agent_funcs_repo.list_all_functions()
        agents = [a for a in all_defs if getattr(a, "name", "").endswith("_agent")]

        # Planner tool schema = each agent callable with {query, accounts_mentioned}
        planner_function_defs: List[Dict[str, Any]] = []
        for a in agents:
            planner_function_defs.append({
                "name": a.name,
                "description": getattr(a, "description", "") or f"Agent {a.name}",
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
        planner_tools = to_tools(planner_function_defs)

        # Planner system prompt
        try:
            planner_system = await prompts_repo.get_system_prompt("planner_system")
        except Exception as e:
            planner_system = None
            md_lines.append(f"**Error retrieving planner system prompt (planner_system): {e}**\n")

        if not planner_system:
            md_lines.append("**Planner system prompt not found (planner_system). Aborting tests.**\n")
            out_file.write_text("\n".join(md_lines), encoding="utf-8")
            print("Planner system prompt missing in Cosmos. Wrote partial results and aborting.")
            return

        for q in test_queries:
            md_lines.append(f"## Query: {q}\n")

            # 1) First planner turn: choose agents
            planner_messages: List[Dict[str, Any]] = [
                {"role": "system", "content": planner_system},
                {"role": "user", "content": q},
            ]

            try:
                planner_resp = await aoai_client.create_chat_completion(
                    messages=planner_messages,
                    tools=planner_tools if planner_tools else None,
                    tool_choice="auto",
                )
            except Exception as e:
                md_lines.append(f"**Planner call failed:** {e}\n\n")
                continue

            md_lines.append("### Planner Request (Turn 1)\n")
            md_lines.append("```json\n" + _pretty({
                "messages": planner_messages,
                "tools": planner_tools if planner_tools else None,
                "tool_choice": "auto",
            }) + "\n```\n")

            md_lines.append("### Planner Raw Response (Turn 1)\n")
            md_lines.append("```json\n" + _pretty(planner_resp) + "\n```\n")

            planner_message = (planner_resp.get("choices") or [{}])[0].get("message", {})
            planner_calls = collect_tool_calls(planner_message)

            if planner_message.get("content"):
                md_lines.append("### Planner Assistant Content (Turn 1)\n")
                md_lines.append(planner_message["content"] + "\n")

            if planner_calls:
                md_lines.append("### Planner Tool Calls (Turn 1)\n")
                for tc in planner_calls:
                    name, args_json = get_call_name_args(tc)
                    md_lines.append(f"- Tool Call → {name}\n")
                    md_lines.append(f"  Arguments: {args_json}\n\n")

            # 2) For each selected agent: call, execute tools, collect results
            agent_exec_records: List[Dict[str, Any]] = []
            for tc in planner_calls:
                if not is_agent_call(tc):
                    continue

                agent_name, tc_args_raw = get_call_name_args(tc)

                # Agent system prompt
                prompt_lookup = f"{agent_name}_system"
                try:
                    agent_system = await prompts_repo.get_system_prompt(prompt_lookup)
                except Exception as e:
                    agent_system = None
                    md_lines.append(f"**Error retrieving system prompt for {agent_name} (lookup_key={prompt_lookup}): {e}**\n\n")

                if not agent_system:
                    md_lines.append(f"**Agent system prompt not found for {agent_name} (lookup_key={prompt_lookup}) - skipping.**\n\n")
                    continue

                # Agent tools for execution
                tools_raw = await agent_funcs_repo.get_functions_by_agent(agent_name)
                if not tools_raw:
                    all_funcs = await agent_funcs_repo.list_all_functions()
                    tools_raw = all_funcs

                agent_function_defs: List[Dict[str, Any]] = []
                def _matches_agent(tool, agent_name: str) -> bool:
                    name = getattr(tool, "name", "") or ""
                    if name.endswith("_agent"):
                        return False
                    if name == agent_name:
                        return True
                    if agent_name in name:
                        return True
                    meta_agents = (getattr(tool, "metadata", {}) or {}).get("agents")
                    if isinstance(meta_agents, (list, tuple)) and agent_name in meta_agents:
                        return True
                    return False

                loaded_names: List[str] = []
                for t in tools_raw:
                    if not getattr(t, "name", None) or not getattr(t, "parameters", None):
                        continue
                    if not _matches_agent(t, agent_name):
                        continue
                    agent_function_defs.append({
                        "name": t.name,
                        "description": getattr(t, "description", "") or "",
                        "parameters": t.parameters,
                    })
                    loaded_names.append(t.name)

                agent_tools = to_tools(agent_function_defs) if agent_function_defs else None
                md_lines.append(f"### Agent Tools Loaded for {agent_name}: {loaded_names}\n")

                # Planner hints → agent
                try:
                    planner_args = json.loads(tc_args_raw or "{}")
                except Exception:
                    planner_args = {}
                agent_query = planner_args.get("query") or q

                # Resolve account names (optional)
                accounts_mentioned = planner_args.get("accounts_mentioned")
                resolved_account_names: List[str] = []
                if accounts_mentioned:
                    try:
                        resolved_accounts = await AccountResolverService_.resolve_account_names(accounts_mentioned, rbac_ctx)
                        def _extract_id_name(item) -> tuple:
                            try:
                                if isinstance(item, dict):
                                    _id = item.get("id") or item.get("account_id")
                                    _name = item.get("name") or item.get("account_name")
                                else:
                                    _id = getattr(item, "id", None)
                                    _name = getattr(item, "name", None)
                                return _id, _name
                            except Exception:
                                return None, None
                        for a in resolved_accounts or []:
                            _id, _name = _extract_id_name(a)
                            if _name:
                                resolved_account_names.append(_name)
                    except Exception:
                        pass

                if resolved_account_names:
                    agent_system = agent_system + "\n\nExact Account name values: " + ",".join(resolved_account_names)

                # Agent call
                agent_messages: List[Dict[str, Any]] = [
                    {"role": "system", "content": agent_system},
                    {"role": "user", "content": agent_query},
                ]
                try:
                    agent_resp = await aoai_client.create_chat_completion(
                        messages=agent_messages,
                        tools=agent_tools,
                        tool_choice="auto",
                    )
                except Exception as e:
                    md_lines.append(f"**Agent call failed ({agent_name}):** {e}\n\n")
                    continue

                md_lines.append("### Agent Request\n")
                md_lines.append("```json\n" + _pretty({
                    "messages": agent_messages,
                    "tools": agent_tools,
                    "tool_choice": "auto",
                }) + "\n```\n")

                md_lines.append("### Agent Raw Response\n")
                md_lines.append("```json\n" + _pretty(agent_resp) + "\n```\n")

                agent_msg = (agent_resp.get("choices") or [{}])[0].get("message", {})
                if agent_msg.get("content"):
                    md_lines.append("### Agent Assistant Content\n")
                    md_lines.append(agent_msg["content"] + "\n")

                agent_calls = collect_tool_calls(agent_msg)
                if agent_calls:
                    md_lines.append("### Agent Tool Calls\n")
                    for atc in agent_calls:
                        atc_name, atc_args = get_call_name_args(atc)
                        md_lines.append(f"- Tool Call → {atc_name}\n")
                        md_lines.append(f"  Arguments: {atc_args}\n\n")

                # Execute tools, collect compact summaries for planner injection
                exec_record = {"agent_name": agent_name, "tool_calls": []}
                for atc in agent_calls or []:
                    atc_name, atc_args = get_call_name_args(atc)
                    try:
                        args_obj = json.loads(atc_args or "{}") if isinstance(atc_args, str) else (atc_args or {})
                    except Exception:
                        args_obj = {}

                    # SQL execution
                    if atc_name and agent_name.startswith("sql_agent") and (
                        "sql" in atc_name.lower() or "opportunity" in atc_name.lower() or "query" in atc_name.lower()
                    ):
                        base_query = args_obj.get("query") or q
                        sql_result = await sql_service.execute_query(base_query, rbac_ctx)
                        exec_record["tool_calls"].append({
                            "function": atc_name,
                            "request": {"query": base_query},
                            "response": summarize_query_result(sql_result),
                        })
                        md_lines.append(f"### Executed SQL Tool: {atc_name}\n")
                        md_lines.append("```json\n" + _pretty(summarize_query_result(sql_result)) + "\n```\n")

                    # GRAPH execution (accept either stored name)
                    if agent_name.startswith("graph_agent") and atc_name in ("graph.query", "graph_agent_function"):
                        g_query = args_obj.get("query") or agent_query
                        g_bindings = args_obj.get("bindings") or {}
                        g_result = await graph_service.execute_query(g_query, rbac_ctx, bindings=g_bindings)
                        exec_record["tool_calls"].append({
                            "function": atc_name,
                            "request": {"query": g_query, "bindings": g_bindings},
                            "response": summarize_query_result(g_result),
                        })
                        md_lines.append(f"### Executed Graph Tool: {atc_name}\n")
                        md_lines.append("```json\n" + _pretty(summarize_query_result(g_result)) + "\n```\n")

                if exec_record["tool_calls"]:
                    agent_exec_records.append(exec_record)

            # 3) Inject agent requests + responses back to the planner and ask for the final answer
            # Rebuild conversation history for planner: system + original user + prior planner content (if any) + our injected summary
            injected_md = build_agent_summary_markdown(agent_exec_records)
            planner_followup_messages: List[Dict[str, Any]] = [
                {"role": "system", "content": planner_system},
                {"role": "user", "content": q},
            ]
            if planner_message.get("content"):
                planner_followup_messages.append({"role": "assistant", "content": planner_message["content"]})
            # Inject our coordination summary as assistant (tools coordinator)
            planner_followup_messages.append({
                "role": "assistant",
                "content": injected_md
            })
            # Ask planner explicitly for the final answer to the user
            planner_followup_messages.append({
                "role": "user",
                "content": "Using the information above, provide the final answer to the user."
            })

            try:
                planner_final = await aoai_client.create_chat_completion(
                    messages=planner_followup_messages,
                    tools=None,
                    tool_choice=None,
                )
            except Exception as e:
                md_lines.append(f"**Planner finalization failed:** {e}\n\n")
                md_lines.append("---\n")
                continue

            md_lines.append("### Injection Back to Planner\n")
            md_lines.append("```markdown\n" + injected_md + "\n```\n")

            md_lines.append("### Planner Final Request (Turn 2)\n")
            md_lines.append("```json\n" + _pretty({"messages": planner_followup_messages}) + "\n```\n")

            md_lines.append("### Planner Final Raw Response (Turn 2)\n")
            md_lines.append("```json\n" + _pretty(planner_final) + "\n```\n")

            planner_final_msg = (planner_final.get("choices") or [{}])[0].get("message", {})
            if planner_final_msg.get("content"):
                md_lines.append("## Final Answer\n")
                md_lines.append(planner_final_msg["content"] + "\n")

            md_lines.append("---\n")

        out_file.write_text("\n".join(md_lines), encoding="utf-8")
        print(f"Wrote results to {out_file}")

    finally:
        try:
            await aoai_client.close()
        except Exception:
            pass
        try:
            await cosmos_client.close()
        except Exception:
            pass
        try:
            await gremlin_client.close()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(run_test())
