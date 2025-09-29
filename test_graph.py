import json, sys, os
from urllib.parse import urlparse
from gremlin_python.driver import client, serializer

try:
    # Prefer managed identity / default credentials for local dev
    from azure.identity import DefaultAzureCredential
    print("Optional: <mode> to specify diagnostic mode (e.g. 'sows_by_offering' or 'account_sows')")
except Exception:
    DefaultAzureCredential = None

if len(sys.argv) < 6:
    print("Usage: python test_graph.py <host_or_endpoint> <db> <graph> <name> <offering>")
    sys.exit(2)

mode = sys.argv[6] if len(sys.argv) > 6 else None

host_arg = sys.argv[1]        # host or full endpoint (e.g. salesforcebot-cosmos-graph.gremlin.cosmos.azure.com or https://...)
db = sys.argv[2]              # database name (graphdb)
graph = sys.argv[3]           # graph/container name (account_graph)
name = sys.argv[4]            # binding 'name'
offering = sys.argv[5]        # binding 'offering'

# Acquire AAD token using DefaultAzureCredential (same audience used in gremlin_client)
token = None
if DefaultAzureCredential is not None:
    try:
        cred = DefaultAzureCredential()
        tk = cred.get_token("https://cosmos.azure.com/.default")
        token = tk.token
    except Exception:
        token = None

if not token:
    token = os.environ.get('AZURE_ACCESS_TOKEN') or os.environ.get('ACCESS_TOKEN')
    if not token:
        print(json.dumps({"error": "No AAD token available. Ensure azure-identity is installed and you are logged in (az login), or set AZURE_ACCESS_TOKEN."}))
        sys.exit(3)

# Parse host and port from host_arg (accept either bare host or full https:// endpoint)
parsed = urlparse(host_arg) if (host_arg.startswith('http://') or host_arg.startswith('https://')) else None
if parsed and parsed.hostname:
    host = parsed.hostname
    port = parsed.port or 443
else:
    host = host_arg
    port = 443


# Corrected Gremlin query (Cosmos-compatible: use in(...) instead of in_(...))
query = (
  "g.V().has('account','name',name).as('src')"
  ".out('has_sow').has('offering', offering).as('seed')"
  ".bothE('similar_to').as('e').otherV().as('sim')"
  ".in('has_sow').hasLabel('account').where(neq('src')).dedup()"
  ".project('id','name','seedSow','similarSow','similarityScore','similarityNote')"
  ".by(id)"
  ".by(values('name'))"
  ".by(select('seed').id())"
  ".by(select('sim').id())"
  ".by(select('e').values('score'))"
  ".by(select('e').values('note'))"
)

bindings = {"name": name, "offering": offering}

# Create a Gremlin client and submit the query using the AAD token as the password
uri = f"wss://{host}:{port}/gremlin"
username = f"/dbs/{db}/colls/{graph}"
def _mask(tok: str) -> str:
    if not tok:
        return '<missing>'
    if len(tok) <= 8:
        return tok[0] + '***'
    return tok[:4] + '...' + tok[-4:]

print(json.dumps({
    "debug": True,
    "host": host,
    "port": port,
    "username": username,
    "token_preview": _mask(token),
    "query": query,
    "bindings": bindings,
}))

c = client.Client(uri, "g", username=username, password=token, message_serializer=serializer.GraphSONSerializersV2d0())
# Diagnostic simple queries
sows_by_offering_q = "g.V().hasLabel('sow').has('offering', offering).valueMap(true).limit(10)"
account_sows_q = "g.V().has('account','name',name).out('has_sow').valueMap(true).limit(10)"

if mode == 'sows_by_offering':
    query = sows_by_offering_q
elif mode == 'account_sows':
    query = account_sows_q
else:
    query = default_query

try:
    # Submit with bindings
    rs = c.submit(message=query, bindings=bindings)
    results = rs.all().result()
    print(json.dumps({"results": results}, indent=2))
except Exception as e:
    import traceback
    tb = traceback.format_exc()
    print(json.dumps({"error": str(e), "traceback": tb}, indent=2))
finally:
    try:
        c.close()
    except:
        pass