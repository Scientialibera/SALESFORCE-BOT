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


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _pretty(obj: Any) -> str:
    try:
        return json.dumps(obj, indent=2, ensure_ascii=False, default=str)
    except Exception:
        return str(obj)

def to_tools(function_defs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Convert legacy function defs [{"name","description","parameters"}]
    into Chat Completions tools entries:
      {"type":"function","function":{...}}
    """
    return [{"type": "function", "function": fd} for fd in function_defs]

def collect_tool_calls(message: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Normalize tool calls across new/legacy shapes.
    Returns a list:
      - new style items (with {"id","function":{"name","arguments"}}), or
      - a single legacy item {"name","arguments"} if present.
    """
    calls: List[Dict[str, Any]] = []
    if not isinstance(message, dict):
        return calls
    if message.get("tool_calls"):
        calls.extend(message["tool_calls"] or [])
    elif message.get("function_call"):
        calls.append(message["function_call"])
    return calls

def get_call_name_args(tc: Dict[str, Any]) -> Tuple[Optional[str], str]:
    """
    Extract (name, arguments_json) from a tool/function call dict.
    Handles both new-style and legacy shapes.
    """
    if "function" in tc and isinstance(tc["function"], dict):
        return tc["function"].get("name"), tc["function"].get("arguments") or "{}"
    return tc.get("name"), tc.get("arguments") or "{}"

def is_agent_call(tc: Dict[str, Any]) -> bool:
    """
    True when the target looks like an agent (name ends with '_agent').
    """
    name, _ = get_call_name_args(tc)
    return isinstance(name, str) and name.endswith("_agent")


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

async def run_test():
    print("Starting simple agentic chatbot test (planner-first, then agent calls) - NO FALLBACKS")

    # Initialize clients and repositories (real Cosmos + real AOAI)
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

    # RBAC service - use settings as-is (no dev-mode fallback)
    rbac_settings = settings.rbac
    rbac_service = RBACService(rbac_settings)  # noqa: F841 (kept for parity / future use)

    # Admin RBAC context for test visibility (not used directly but kept for parity)
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

    # Test queries
    test_queries = [
        "How are you?",
        "All sales for Microsoft and its account relationships",
        "All sales",
    ]

    out_file = repo_root / "chatbot_agentic_test_results.md"
    md_lines = ["# Agentic Test Results\n"]

    try:
        # Load agents (documents whose name ends with '_agent')
        all_defs = await agent_funcs_repo.list_all_functions()
        agents = [a for a in all_defs if getattr(a, "name", "").endswith("_agent")]

        # Planner tool schema: each agent is a function (include accounts_mentioned as your planner prompt requires)
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

        # Planner system prompt from Cosmos (NO FALLBACKS)
        try:
            planner_system = await prompts_repo.get_system_prompt("planner_system")
        except Exception as e:
            planner_system = None
            md_lines.append(f"**Error retrieving planner system prompt from Cosmos (lookup_key=planner_system): {e} (no fallbacks allowed). Aborting tests.**\n")

        if not planner_system:
            md_lines.append("**Planner system prompt not found in Cosmos (no fallbacks allowed). Aborting tests.**\n")
            out_file.write_text("\n".join(md_lines), encoding="utf-8")
            print("Planner system prompt missing in Cosmos. Wrote partial results and aborting.")
            return

        for q in test_queries:
            md_lines.append(f"## Query: {q}\n")

            # ── Planner call ────────────────────────────────────────────────────
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

            md_lines.append("### Planner Request\n")
            md_lines.append("```json\n" + _pretty({
                "messages": planner_messages,
                "tools": planner_tools if planner_tools else None,
                "tool_choice": "auto",
            }) + "\n```\n")

            md_lines.append("### Planner Raw Response\n")
            md_lines.append("```json\n" + _pretty(planner_resp) + "\n```\n")

            # Extract planner tool calls (we do NOT execute them here)
            planner_message = (planner_resp.get("choices") or [{}])[0].get("message", {})
            planner_calls = collect_tool_calls(planner_message)

            if planner_message.get("content"):
                md_lines.append("### Planner Assistant Answer\n")
                md_lines.append(planner_message["content"] + "\n")

            if planner_calls:
                md_lines.append("### Planner Tool Calls\n")
                for tc in planner_calls:
                    name, args_json = get_call_name_args(tc)
                    md_lines.append(f"- Tool Call → {name}\n")
                    md_lines.append(f"  Arguments: {args_json}\n\n")

            # ── For each planner-selected AGENT: call the agent and STOP after it returns tool calls ──
            for tc in planner_calls:
                if not is_agent_call(tc):
                    continue

                agent_name, tc_args_raw = get_call_name_args(tc)

                # Agent system prompt (NO FALLBACKS)
                prompt_lookup = f"{agent_name}_system"
                try:
                    agent_system = await prompts_repo.get_system_prompt(prompt_lookup)
                except Exception as e:
                    agent_system = None
                    md_lines.append(f"**Error retrieving system prompt for agent {agent_name} (lookup_key={prompt_lookup}): {e}**\n\n")

                if not agent_system:
                    md_lines.append(f"**Agent system prompt not found for {agent_name} (lookup_key={prompt_lookup}) - skipping agent.**\n\n")
                    continue

                # Agent tools: load from repo and wrap as tools (no fallbacks, no execution)
                # Use strict matching so `sql_agent` only loads functions intended
                # for that agent (e.g. `sql_agent_function`). Exclude any
                # agent documents (names that end with '_agent').
                tools_raw = await agent_funcs_repo.get_functions_by_agent(agent_name)
                # If the repo returned nothing, fall back to listing everything
                # and then filter by name/metadata heuristics.
                if not tools_raw:
                    all_funcs = await agent_funcs_repo.list_all_functions()
                    tools_raw = all_funcs

                agent_function_defs: List[Dict[str, Any]] = []

                def _matches_agent(tool, agent_name: str) -> bool:
                    name = getattr(tool, "name", "") or ""
                    # Exclude agent documents themselves
                    if name.endswith("_agent"):
                        return False
                    # Exact match
                    if name == agent_name:
                        return True
                    # Common pattern: '<agent>_function' or contains agent name
                    if agent_name in name:
                        return True
                    # Check metadata 'agents' list if present
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

                # Agent query from planner args (best-effort)
                try:
                    planner_args = json.loads(tc_args_raw or "{}")
                except Exception:
                    planner_args = {}
                agent_query = planner_args.get("query") or q

                # If planner provided accounts_mentioned, resolve them (dev-mode dummy resolver)
                accounts_mentioned = planner_args.get("accounts_mentioned")
                print(f"Accounts mentioned by planner for {agent_name}: {accounts_mentioned}")
                resolved_account_names: List[str] = []
                if accounts_mentioned:
                    try:
                        # Use the dev-mode AccountResolverService_ to map names to Account objects
                        resolved_accounts = await AccountResolverService_.resolve_account_names(accounts_mentioned, rbac_ctx)

                        def _extract_id_name(item) -> tuple:
                            # Support either pydantic Account objects or plain dicts
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

                        print(f"### Resolved Accounts for {agent_name}: {resolved_account_names}\n")
                    except Exception as e:
                        print(f"**Account resolution failed:** {e}\n")

                # If we resolved exact account ids, append them to the agent system prompt so
                # the agent has deterministic ids to work with.
                if resolved_account_names:
                    agent_system = agent_system + "\n\nExact Account id values: " + ",".join(resolved_account_names)

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

                # Log agent text (if any) and the agent's own tool calls — DO NOT EXECUTE, then STOP.
                agent_msg = (agent_resp.get("choices") or [{}])[0].get("message", {})
                if agent_msg.get("content"):
                    md_lines.append("### Agent Assistant Content\n")
                    md_lines.append(agent_msg["content"] + "\n")

                agent_calls = collect_tool_calls(agent_msg)
                if agent_calls:
                    md_lines.append("### Agent Tool Calls (not executed)\n")
                    for atc in agent_calls:
                        atc_name, atc_args = get_call_name_args(atc)
                        md_lines.append(f"- Tool Call → {atc_name}\n")
                        md_lines.append(f"  Arguments: {atc_args}\n\n")

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


if __name__ == "__main__":
    asyncio.run(run_test())

