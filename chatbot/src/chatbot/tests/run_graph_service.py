import asyncio
import logging
import sys
from pathlib import Path

# Add chatbot/src to sys.path
file_path = Path(__file__).resolve()
repo_root = file_path.parents[4]
chatbot_src = repo_root / "chatbot" / "src"
sys.path.insert(0, str(chatbot_src))

from chatbot.config.settings import settings
from chatbot.clients.gremlin_client import GremlinClient
from chatbot.services.graph_service import GraphService
from chatbot.models.rbac import RBACContext, AccessScope


async def main():
    logging.basicConfig(level=logging.INFO)

    # Instantiate Gremlin client
    gremlin_settings = settings.gremlin
    gremlin = GremlinClient(gremlin_settings)

    # Disable RBAC for dev testing
    service = GraphService(gremlin_client=gremlin, dev_mode=True)
    resolved_name = "Microsoft Corporation"
    query = (
        "g.V().hasLabel('account').has('name',name)"
        ".both().hasLabel('account')"
        ".project('id','label','name','acct_type','tier','industry')"
        ".by(id())"
        ".by(label())"
        ".by(coalesce(values('name'), constant('')))"
        ".by(coalesce(values('type'), constant('')))"
        ".by(coalesce(values('tier'), constant('')))"
        ".by(coalesce(values('industry'), constant('')))"
    )
    bindings = {"name": resolved_name}

    # Dev-mode RBAC context
    rbac = RBACContext(
        user_id="test_user",
        email="test_user@example.com",
        tenant_id="test-tenant",
        object_id="test-object-id",
        roles=["admin"],
        permissions=set(),
        access_scope=AccessScope(),
        is_admin=True,
    )

    try:
        result = await service.execute_query(query, rbac, bindings=bindings)
        print("Query:", query.strip())
        print("Success:", result.success)

        if result.data and result.data.rows:
            print("Related Accounts:")
            for r in result.data.rows:
                def _scalar(v):
                    if isinstance(v, list) and v:
                        first = v[0]
                        if isinstance(first, dict) and "_value" in first:
                            return first.get("_value")
                        return first
                    if isinstance(v, dict) and "_value" in v:
                        return v.get("_value")
                    return v

                norm = {k: _scalar(v) for k, v in r.items()}
                print("-" * 40)
                print("ID:", norm.get("id"))
                print("Name:", norm.get("name"))
                print("Type:", norm.get("type"))
                print("Industry:", norm.get("industry"))
                print("Tier:", norm.get("tier"))
        else:
            print("No related accounts found.")
    except Exception as e:
        print("❌ Error executing graph query:", e)


if __name__ == "__main__":
    asyncio.run(main())
