#!/usr/bin/env python3
"""
Data initialization script for Salesforce Q&A Bot.

This script uploads prompts, functions, and dummy data to prepare
the system for testing and development.
"""

import asyncio
import json
import sys
import os
from pathlib import Path
from typing import Dict, List, Any
import shutil
# This initializer will use the `az` CLI exclusively for resource provisioning.
# Do NOT attempt to use management SDKs or any key-based fallbacks. The
# environment must have Azure CLI installed and the user must be authenticated
# (e.g. `az login`) with a principal that has permission to create Cosmos DB
# resources in the target subscription/resource group.

# Add the src directory to Python path
current_dir = Path(__file__).parent
# Go up to project root, then into chatbot/src
project_root = current_dir.parent.parent
src_dir = project_root / "chatbot" / "src"
sys.path.insert(0, str(src_dir))
# Ensure working directory is repository root so .env is discovered by pydantic
# Ensure working directory is repository root so .env is discovered by pydantic
os.chdir(project_root)

# Load repo-root .env into environment to ensure CONTAINER_APP_RESOURCE_GROUP and other
# variables are available even when running this script from other shells.
env_path = project_root / '.env'
if env_path.exists():
    try:
        with open(env_path, 'r', encoding='utf-8') as ef:
            for ln in ef:
                ln = ln.strip()
                if not ln or ln.startswith('#'):
                    continue
                if '=' not in ln:
                    continue
                k, v = ln.split('=', 1)
                # Only set if not already in environment to allow overrides
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        # Non-fatal; settings will still try to read env via pydantic
        pass

# --- Debug: print key env settings (masked) to help diagnose credential issues ---
def _mask(val: str) -> str:
    if not val:
        return '<missing>'
    if len(val) <= 8:
        return val[0] + '***'
    return val[:4] + '...' + val[-4:]

print('\n[init_data] Effective environment:')
print('  CONTAINER_APP_RESOURCE_GROUP =', os.environ.get('CONTAINER_APP_RESOURCE_GROUP') or os.environ.get('CONTAINER_APP_RESOURCEGROUP'))
print('  COSMOS_ENDPOINT =', os.environ.get('COSMOS_ENDPOINT') or os.environ.get('AZURE_COSMOS_GREMLIN_ENDPOINT'))
print('  AZURE_COSMOS_GREMLIN_ENDPOINT =', os.environ.get('AZURE_COSMOS_GREMLIN_ENDPOINT'))
print('  AZURE_COSMOS_GREMLIN_DATABASE =', os.environ.get('AZURE_COSMOS_GREMLIN_DATABASE'))
print('  AZURE_COSMOS_GREMLIN_GRAPH =', os.environ.get('AZURE_COSMOS_GREMLIN_GRAPH'))
print('  MOCK_EMBEDDINGS =', os.environ.get('MOCK_EMBEDDINGS'))
print()
# ---------------------------------------------------------------

from chatbot.config.settings import settings
from chatbot.clients.cosmos_client import CosmosDBClient
from chatbot.clients.gremlin_client import GremlinClient
from gremlin_python.driver.protocol import GremlinServerError
from tenacity import RetryError
import subprocess
import platform
import json
import time

# Asset paths used by the uploader logic (previously in upload_artifacts.py)
ASSETS_PROMPTS = project_root / 'scripts' / 'assets' / 'prompts'
ASSETS_FUNCTIONS = project_root / 'scripts' / 'assets' / 'functions'
ASSETS_FUNCTIONS_TOOLS = ASSETS_FUNCTIONS / 'tools'
ASSETS_FUNCTIONS_AGENTS = ASSETS_FUNCTIONS / 'agents'


class DataInitializer:
    """Handles initialization of all system data."""
    
    def __init__(self):
        """Initialize the data initializer with Azure clients."""
        self.cosmos_client = CosmosDBClient(settings.cosmos_db)
        self.gremlin_client = GremlinClient(settings.gremlin)
        
    async def initialize_all(self):
        """Run complete data initialization."""
        print("🚀 Starting data initialization for Salesforce Q&A Bot...")
        
        try:
            # Ensure required Cosmos containers exist (best-effort via az CLI)
            await self.ensure_cosmos_containers()
            # Ensure Gremlin graph exists (best-effort via az CLI). This will
            # attempt to create the Gremlin database and graph when the
            # CONTAINER_APP_RESOURCE_GROUP env var is set and the caller has
            # sufficient rights.
            await self.ensure_gremlin_graph()
            # Initialize prompts/functions/agents using the uploader helper
            # This will provision required Cosmos DB database/containers via the
            # Azure CLI (AAD) and upload prompts and function/agent definitions
            # from `scripts/assets` in the repository. If the uploader helper is
            # unavailable we fall back to the local upload implementations.
            await self.upload_artifacts()
            
            # Initialize dummy graph data
            await self.upload_dummy_graph_data()
            
            print("✅ Data initialization completed successfully!")
            
        except Exception as e:
            print(f"❌ Data initialization failed: {e}")
            raise
        finally:
            # Cleanup connections
            if hasattr(self.cosmos_client, 'close'):
                await self.cosmos_client.close()
            if hasattr(self.gremlin_client, 'close'):
                await self.gremlin_client.close()
    
    async def upload_prompts(self):
        """Upload system prompts to Cosmos DB."""
        print("📝 Uploading system prompts...")
        
        # Load prompts from prompts/ folder. Fallback to repository assets if present.
        prompts_dir = Path(__file__).parent / "prompts"
        if not prompts_dir.exists():
            # fallback to scripts/assets/prompts
            alt = project_root / "scripts" / "assets" / "prompts"
            if alt.exists():
                prompts_dir = alt
            else:
                print("⚠️  Prompts directory not found, skipping prompt upload")
                return
        
        for prompt_file in prompts_dir.glob("*.json"):
            try:
                with open(prompt_file, 'r') as f:
                    prompt_data = json.load(f)
                
                # Upload to prompts container
                await self.cosmos_client.upsert_item(
                    container_name=settings.cosmos_db.prompts_container,
                    item=prompt_data
                )
                
                print(f"  ✓ Uploaded prompt: {prompt_data['id']}")
                
            except Exception as e:
                print(f"  ❌ Failed to upload {prompt_file.name}: {e}")
    
    async def upload_functions(self):
        """Upload function definitions to Cosmos DB."""
        print("🔧 Uploading function definitions...")
        
        # Load functions from functions/ folder. Fallback to repository assets if present.
        functions_dir = Path(__file__).parent / "functions"
        if not functions_dir.exists():
            alt = project_root / "scripts" / "assets" / "functions"
            if alt.exists():
                functions_dir = alt
            else:
                print("⚠️  Functions directory not found, skipping function upload")
                return
        
        for function_file in functions_dir.glob("*.json"):
            try:
                with open(function_file, 'r') as f:
                    function_data = json.load(f)
                
                # Upload to agent_functions container
                await self.cosmos_client.upsert_item(
                    container_name=settings.cosmos_db.agent_functions_container,
                    item=function_data
                )
                
                print(f"  ✓ Uploaded functions: {function_data['id']}")
                
            except Exception as e:
                print(f"  ❌ Failed to upload {function_file.name}: {e}")

    async def upload_artifacts(self):
        """Use the repository uploader script to provision Cosmos and upload artifacts.

        Consolidated uploader: previously this delegated to
        `scripts/test_env/upload_artifacts.py`. That module has been removed
        and its provisioning/upload logic is embedded here to ensure a single
        entrypoint and remove duplication.
        """
        print("🔁 Uploading prompts and functions via repository uploader...")
        # Essential containers for simplified architecture
        containers = [
            settings.cosmos_db.chat_container,        # Unified session/message/feedback storage
            settings.cosmos_db.prompts_container,     # System prompts
            settings.cosmos_db.agent_functions_container,  # Function definitions
            settings.cosmos_db.sql_schema_container,  # Schema metadata
        ]

        # Provision Cosmos resources using az CLI (best-effort)
        try:
            self._provision_cosmos_via_az(settings.cosmos_db.endpoint, settings.cosmos_db.database_name, containers)
        except Exception as e:
            print(f"  ⚠️ Provisioning step failed or skipped: {e}")

        # Run uploader logic: upload prompts and functions from scripts/assets
        try:
            # instantiate repo classes
            from chatbot.repositories.prompts_repository import PromptsRepository
            from chatbot.repositories.agent_functions_repository import AgentFunctionsRepository

            prompts_repo = PromptsRepository(self.cosmos_client, settings.cosmos_db.database_name, settings.cosmos_db.prompts_container)
            functions_repo = AgentFunctionsRepository(self.cosmos_client, settings.cosmos_db.database_name, settings.cosmos_db.agent_functions_container)

            await self._uploader_upload_prompts(prompts_repo)
            await self._uploader_upload_functions(functions_repo)
            print("  ✓ Uploader completed prompts and functions upload.")
            return
        except Exception as e:
            print(f"  ⚠️ Uploader failed during upload steps: {e}")
            print("  → Falling back to built-in upload implementations.")

        # Fallback behavior — should rarely be needed now
        await self.upload_prompts()
        await self.upload_functions()

    def _provision_cosmos_via_az(self, endpoint: str, database: str, containers: list, resource_group: str | None = None):
        """Best-effort: use Azure CLI to create database and containers using AAD credentials.

        This mirrors the behavior previously implemented in
        `scripts/test_env/upload_artifacts.py`. It requires `az` in PATH and an
        authenticated principal. It will print actionable errors if CLI is
        missing or permissions are insufficient.
        """
        # endpoint looks like https://<account>.documents.azure.com
        try:
            account = endpoint.replace('https://', '').split('.')[0]
        except Exception:
            print('Could not parse Cosmos account name from endpoint', endpoint)
            return

        rg = resource_group or os.environ.get('CONTAINER_APP_RESOURCE_GROUP') or os.environ.get('CONTAINER_APP_RESOURCEGROUP')
        if not rg:
            # try to discover via az
            try:
                res = subprocess.run(['az','resource','list','--resource-type','Microsoft.DocumentDB/databaseAccounts','--query','[?contains(name, `'+account+'`)]','-o','json'], capture_output=True, text=True, check=False)
                if res.returncode == 0 and res.stdout:
                    data = json.loads(res.stdout)
                    if isinstance(data, list) and len(data) > 0:
                        rg = data[0].get('resourceGroup')
            except Exception:
                rg = None

        if not rg:
            print('Could not detect resource group for Cosmos account', account, '— skipping az provisioning. Provide CONTAINER_APP_RESOURCE_GROUP to enable provisioning.')
            return

        if not shutil.which('az'):
            print("ERROR: Azure CLI ('az') was not found in PATH. Skipping provisioning.")
            return

        az_exe = shutil.which('az')

        def run_az(cmd: List[str], timeout: int = 30):
            cmd0 = list(cmd)
            cmd0[0] = az_exe
            try:
                res = subprocess.run(cmd0, check=False, capture_output=True, text=True, timeout=timeout)
                return res.returncode, res.stdout, res.stderr
            except subprocess.TimeoutExpired as e:
                return -1, '', f'Timeout after {timeout}s: {e}'

        # Ensure database exists
        rc, out, err = run_az([az_exe, 'cosmosdb', 'sql', 'database', 'show', '--account-name', account, '--resource-group', rg, '--name', database], timeout=20)
        if rc == 0:
            print(f"  ✓ Cosmos SQL database '{database}' already exists.")
        else:
            print(f"  ➤ Creating Cosmos SQL database '{database}' (account={account}, rg={rg})")
            rc, out, err = run_az([az_exe, 'cosmosdb', 'sql', 'database', 'create', '--account-name', account, '--resource-group', rg, '--name', database], timeout=60)
            if rc != 0:
                print(f"    ERROR creating database: rc={rc}\nstdout={out}\nstderr={err}")
            else:
                print(f"    ✓ Created database '{database}'.")

        # Ensure containers
        for c in containers:
            if not c:
                continue
            print(f"  ➤ Ensuring container '{c}' in DB '{database}'...")
            rc, out, err = run_az([az_exe, 'cosmosdb', 'sql', 'container', 'show', '--account-name', account, '--resource-group', rg, '--database-name', database, '--name', c], timeout=20)
            if rc == 0:
                print(f"    ✓ Cosmos container '{c}' already exists in DB '{database}'.")
                continue
            print(f"    ➤ Creating Cosmos container '{c}' in DB '{database}'")
            rc, out, err = run_az([az_exe, 'cosmosdb', 'sql', 'container', 'create', '--account-name', account, '--resource-group', rg, '--database-name', database, '--name', c, '--partition-key-path', '/id', '--throughput', '400'], timeout=60)
            if rc != 0:
                print(f"      ERROR creating container '{c}': rc={rc}\nstdout={out}\nstderr={err}")
            else:
                print(f"      ✓ Created container '{c}'.")

    async def _uploader_upload_prompts(self, prompts_repo):
        """Upload prompts from `scripts/assets/prompts` (mirror of upload_artifacts.upload_prompts)."""
        print('Uploading prompts from assets...')
        if not ASSETS_PROMPTS.exists():
            print('  ⚠️ No prompts assets directory found at', ASSETS_PROMPTS)
            return
        for fname in os.listdir(ASSETS_PROMPTS):
            if not str(fname).endswith('.md') and not str(fname).endswith('.json'):
                continue
            path = ASSETS_PROMPTS / fname
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                # If JSON, parse and upload as object; if MD, upload as system prompt
                if fname.endswith('.json'):
                    data = json.loads(content)
                    await prompts_repo.delete_prompt(data.get('id', ''))
                    await prompts_repo.save_prompt(prompt_id=data.get('id'), agent_name=data.get('agent_name') or data.get('id'), prompt_type=data.get('type') or 'system', content=json.dumps(data))
                    print('  ✓ Uploaded prompt (json):', fname)
                else:
                    agent_name = Path(fname).stem
                    prompt_id = f'{agent_name}'
                    try:
                        await prompts_repo.delete_prompt(prompt_id)
                    except Exception:
                        pass
                    await prompts_repo.save_prompt(prompt_id=prompt_id, agent_name=agent_name, prompt_type='system', content=content)
                    print('  ✓ Uploaded prompt (md):', fname)
            except Exception as e:
                print('  ❌ Failed to upload prompt', fname, 'error:', e)

    async def _uploader_upload_functions(self, functions_repo):
        """Upload function/tool/agent definitions from `scripts/assets/functions` (one JSON = one function/agent)."""
        print('Uploading function definitions from assets...')
        # Tools
        if ASSETS_FUNCTIONS_TOOLS.exists():
            for fname in os.listdir(ASSETS_FUNCTIONS_TOOLS):
                if not str(fname).endswith('.json'):
                    continue
                path = ASSETS_FUNCTIONS_TOOLS / fname
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    name = data.get('name')
                    if not name:
                        print(f'  ❌ Tool file {fname} missing "name" field, skipping')
                        continue
                    from chatbot.models.result import ToolDefinition
                    td = ToolDefinition(name=name, description=data.get('description', ''), parameters=data.get('parameters', {}), metadata=data.get('metadata', {}))
                    try:
                        await functions_repo.delete_function_definition(name)
                    except Exception:
                        pass
                    agents = data.get('agents') or data.get('metadata', {}).get('agents') or ['sql_agent', 'graph_agent']
                    await functions_repo.save_function_definition(td, agents=agents)
                    print('  ✓ Uploaded tool function', name, 'agents=', agents)
                except Exception as e:
                    print('  ❌ Failed to upload tool file', fname, 'error:', e)

        # Agents
        if ASSETS_FUNCTIONS_AGENTS.exists():
            for fname in os.listdir(ASSETS_FUNCTIONS_AGENTS):
                if not str(fname).endswith('.json'):
                    continue
                path = ASSETS_FUNCTIONS_AGENTS / fname
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    agent_id = data.get('id') or data.get('name')
                    if not agent_id:
                        print(f'  ❌ Agent file {fname} missing "id" or "name" field, skipping')
                        continue
                    from chatbot.models.result import ToolDefinition
                    td = ToolDefinition(name=agent_id, description=data.get('description', ''), parameters=data.get('parameters', {}), metadata=data.get('metadata', {}))
                    try:
                        await functions_repo.delete_function_definition(agent_id)
                    except Exception:
                        pass
                    agents_list = data.get('agents') or [data.get('name')]
                    await functions_repo.save_function_definition(td, agents=agents_list)
                    print('  ✓ Uploaded agent registration', agent_id, 'agents=', agents_list)
                except Exception as e:
                    print('  ❌ Failed to upload agent file', fname, 'error:', e)
    
    async def upload_dummy_graph_data(self):
        """Upload dummy account and relationship data to Gremlin graph."""
        print("🕸️  Uploading dummy graph data...")
        # Quick availability probe: try a lightweight query and gracefully
        # skip graph upload if the Gremlin graph/collection is not provisioned.
        try:
            await self.gremlin_client.execute_query("g.V().limit(1)")
        except (RetryError, GremlinServerError, Exception) as e:
            # tenacity wraps the final exception in RetryError; unwrap if possible
            inner = e
            if isinstance(e, RetryError) and hasattr(e, 'last_attempt'):
                try:
                    inner = e.last_attempt.exception()
                except Exception:
                    inner = e

            msg = str(inner)
            # Detect common auth/credential misconfiguration messages and give actionable guidance
            if "DefaultAzureCredential failed" in msg or "Unable to get authority configuration" in msg or 'credential' in msg.lower():
                print("⚠️  Gremlin authentication failed (DefaultAzureCredential). Skipping graph upload.")
                print("   -> Ensure you're logged in (az login) or running with a managed identity that has data-plane access to Cosmos DB.")
                # The project enforces AAD-based auth (DefaultAzureCredential / Managed Identity).
                # Do NOT enable or rely on key-based credentials. Remove any AZURE_COSMOS_GREMLIN_PASSWORD or other secrets from your .env.
                return
            if "NotFound" in msg or "404" in msg:
                print("⚠️  Gremlin graph or collection not found. Skipping graph upload.")
                print("   -> Create the Gremlin graph (relationships) or run scripts/infra/deploy.ps1 and re-run this initializer.")
                return
            else:
                print(f"⚠️  Gremlin check failed: {inner}")
                # Treat as non-fatal but stop graph upload
                return

        try:
            # Optionally clear existing graph data. By default we clear so
            # the graph contains only the nodes/edges created by this initializer.
            # Set the environment variable INIT_DATA_CLEAR_GRAPH to 'false' to
            # preserve existing data.
            init_clear = os.environ.get('INIT_DATA_CLEAR_GRAPH', 'true').lower() in ('1', 'true', 'yes')
            if init_clear:
                print("  🧹 Clearing existing graph data (INIT_DATA_CLEAR_GRAPH=true)...")
                await self.gremlin_client.execute_query("g.E().drop()")
                await self.gremlin_client.execute_query("g.V().drop()")

            # Add account vertices with sales-relevant properties
            accounts = [
                {
                    "id": "acc_salesforce", 
                    "name": "Salesforce Inc", 
                    "type": "CRM", 
                    "tier": "Enterprise",
                    "industry": "Technology",
                    "revenue": "34.1B",
                    "employees": "79000",
                    "status": "Active Customer",
                    "contract_value": "2.5M",
                    "renewal_date": "2025-03-15"
                },
                {
                    "id": "acc_microsoft", 
                    "name": "Microsoft Corporation", 
                    "type": "Enterprise Software", 
                    "tier": "Strategic",
                    "industry": "Technology",
                    "revenue": "245.1B",
                    "employees": "221000",
                    "status": "Prospect",
                    "contract_value": "0",
                    "renewal_date": None
                },
                {
                    "id": "acc_oracle", 
                    "name": "Oracle Corporation", 
                    "type": "Database", 
                    "tier": "Enterprise",
                    "industry": "Technology",
                    "revenue": "52.9B",
                    "employees": "164000",
                    "status": "Active Customer",
                    "contract_value": "1.8M",
                    "renewal_date": "2024-11-30"
                },
                {
                    "id": "acc_aws", 
                    "name": "Amazon Web Services", 
                    "type": "Cloud Infrastructure", 
                    "tier": "Competitor",
                    "industry": "Cloud Computing",
                    "revenue": "90.0B",
                    "employees": "1600000",
                    "status": "Competitor",
                    "contract_value": "0",
                    "renewal_date": None
                },
                {
                    "id": "acc_google", 
                    "name": "Google LLC", 
                    "type": "Cloud Services", 
                    "tier": "Competitor",
                    "industry": "Technology",
                    "revenue": "307.4B",
                    "employees": "190000",
                    "status": "Competitor",
                    "contract_value": "0",
                    "renewal_date": None
                },
                {
                    "id": "acc_sap", 
                    "name": "SAP SE", 
                    "type": "ERP", 
                    "tier": "Enterprise",
                    "industry": "Enterprise Software",
                    "revenue": "33.8B",
                    "employees": "111000",
                    "status": "Prospect",
                    "contract_value": "0",
                    "renewal_date": None
                }
            ]
            
            for account in accounts:
                query = f"""
                g.addV('account')
                 .property('id', '{account["id"]}')
                 .property('partitionKey', '{account["id"]}')
                 .property('name', '{account["name"]}')
                 .property('type', '{account["type"]}')
                 .property('tier', '{account["tier"]}')
                 .property('industry', '{account["industry"]}')
                 .property('revenue', '{account["revenue"]}')
                 .property('employees', {account["employees"]})
                 .property('status', '{account["status"]}')
                 .property('contract_value', '{account["contract_value"]}')
                 .property('renewal_date', '{account["renewal_date"] or ""}')
                """
                await self.gremlin_client.execute_query(query)
                print(f"  ✓ Added account: {account['name']} ({account['status']})")
            
            # Add account-account relationships only if explicitly enabled.
            # To skip adding these legacy/extra relationships set
            # INIT_DATA_KEEP_ACCOUNT_RELATIONSHIPS=false (default).
            keep_rels = os.environ.get('INIT_DATA_KEEP_ACCOUNT_RELATIONSHIPS', 'false').lower() in ('1', 'true', 'yes')
            if keep_rels:
                relationships = [
                    # Current customer relationships
                    {"from": "acc_salesforce", "to": "acc_microsoft", "type": "integrates_with", "strength": 0.9, "description": "Salesforce integrates with Microsoft 365"},
                    {"from": "acc_salesforce", "to": "acc_aws", "type": "hosted_on", "strength": 0.8, "description": "Salesforce CRM hosted on AWS"},
                    {"from": "acc_oracle", "to": "acc_aws", "type": "migrating_to", "strength": 0.7, "description": "Oracle considering AWS migration"},
                    
                    # Competitive relationships
                    {"from": "acc_microsoft", "to": "acc_google", "type": "competes_with", "strength": 0.8, "description": "Direct competition in cloud services"},
                    {"from": "acc_aws", "to": "acc_google", "type": "competes_with", "strength": 0.9, "description": "Direct competition in cloud infrastructure"},
                    {"from": "acc_microsoft", "to": "acc_aws", "type": "competes_with", "strength": 0.7, "description": "Competition in enterprise cloud"},
                    
                    # Partnership opportunities
                    {"from": "acc_salesforce", "to": "acc_sap", "type": "potential_partnership", "strength": 0.6, "description": "SAP-Salesforce integration opportunity"},
                    {"from": "acc_oracle", "to": "acc_sap", "type": "competes_with", "strength": 0.8, "description": "Direct competition in ERP space"},
                    
                    # Cross-sell opportunities
                    {"from": "acc_salesforce", "to": "acc_oracle", "type": "potential_integration", "strength": 0.5, "description": "Salesforce + Oracle database integration"},
                    {"from": "acc_microsoft", "to": "acc_sap", "type": "integrates_with", "strength": 0.7, "description": "Microsoft-SAP partnership"}
                ]

                for rel in relationships:
                    query = f"""
                    g.V('{rel["from"]}')
                     .addE('{rel["type"]}')
                     .to(g.V('{rel["to"]}'))
                     .property('strength', {rel["strength"]})
                     .property('description', '{rel["description"]}')
                    """
                    await self.gremlin_client.execute_query(query)
                    print(f"  ✓ Added relationship: {rel['from']} -{rel['type']}-> {rel['to']} ({rel['description']})")

            # --- New: Add Statements of Work (SOW) connected to accounts ---
            # We intentionally do NOT create 'offering' vertices by default so the
            # graph contains only 'account' and 'sow' vertices and their edges.
            print("  ➤ Adding sample Statements of Work (SOWs)...")

            # Sample SOWs (work done for accounts). Each SOW stores its offering
            # as a property rather than a separate vertex to keep the graph
            # limited to accounts and sows.
            sows = [
                # --- AI Chatbots (now across multiple accounts) ---
                {"id": "sow_msft_ai_chatbot_2023",      "account": "acc_microsoft",  "title": "Microsoft AI Chatbot PoC",              "offering": "ai_chatbot",        "year": 2023, "value": "250000"},
                {"id": "sow_salesforce_ai_chatbot_2023","account": "acc_salesforce",  "title": "Salesforce Service Chatbot Rollout",    "offering": "ai_chatbot",        "year": 2023, "value": "300000"},
                {"id": "sow_google_ai_chatbot_2024",    "account": "acc_google",      "title": "Google Customer Support Chatbot",       "offering": "ai_chatbot",        "year": 2024, "value": "410000"},
                {"id": "sow_aws_ai_chatbot_2022",       "account": "acc_aws",         "title": "AWS Internal Helpdesk Bot",             "offering": "ai_chatbot",        "year": 2022, "value": "150000"},
                {"id": "sow_sap_ai_chatbot_2023",       "account": "acc_sap",         "title": "SAP Field Service Chatbot",             "offering": "ai_chatbot",        "year": 2023, "value": "210000"},

                # --- Existing non-chatbot samples you already had ---
                {"id": "sow_msft_fabric_2024",          "account": "acc_microsoft",   "title": "Microsoft Fabric Deployment",           "offering": "fabric_deployment", "year": 2024, "value": "560000"},
                {"id": "sow_salesforce_dynamics_2022",  "account": "acc_salesforce",   "title": "Salesforce Dynamics Integration",       "offering": "dynamics",          "year": 2022, "value": "180000"},
                {"id": "sow_oracle_migration_2024",     "account": "acc_oracle",       "title": "Oracle Data Migration",                 "offering": "data_migration",    "year": 2024, "value": "320000"},
                {"id": "sow_sap_fabric_2023",           "account": "acc_sap",          "title": "SAP Fabric Proof of Value",             "offering": "fabric_deployment", "year": 2023, "value": "120000"},
            ]

            for sow in sows:
                q = f"""
                g.addV('sow')
                 .property('id', '{sow['id']}')
                 .property('partitionKey', '{sow['id']}')
                 .property('title', "{sow['title']}")
                 .property('offering', '{sow['offering']}')
                 .property('year', {sow['year']})
                 .property('value', '{sow['value']}')
                """
                await self.gremlin_client.execute_query(q)
                # Link account -> sow
                link_q = f"""
                g.V('{sow['account']}')
                 .addE('has_sow')
                 .to(g.V('{sow['id']}'))
                 .property('role', 'contract')
                """
                await self.gremlin_client.execute_query(link_q)
                print(f"    ✓ Added SOW: {sow['id']} (account={sow['account']}, offering={sow['offering']})")

            # Similarity / related work edges between SOWs to help find similar engagements
            # e.g., MSFT AI Chatbot SOW is similar to Salesforce Dynamics integration (if both are conversational projects)
            sow_similarities = [
                # --- AI chatbot clusters (more edges = more matches) ---
                {"a": "sow_msft_ai_chatbot_2023",       "b": "sow_salesforce_ai_chatbot_2023", "score": 0.85, "note": "enterprise support chatbots"},
                {"a": "sow_msft_ai_chatbot_2023",       "b": "sow_google_ai_chatbot_2024",     "score": 0.80, "note": "customer service chatbots"},
                {"a": "sow_salesforce_ai_chatbot_2023", "b": "sow_aws_ai_chatbot_2022",        "score": 0.70, "note": "IT/helpdesk assistant use cases"},
                {"a": "sow_google_ai_chatbot_2024",     "b": "sow_sap_ai_chatbot_2023",        "score": 0.65, "note": "multilingual bot UX"},
                {"a": "sow_aws_ai_chatbot_2022",        "b": "sow_sap_ai_chatbot_2023",        "score": 0.60, "note": "FAQ intent modeling overlap"},

                # --- Keep/extend your original non-chatbot links ---
                {"a": "sow_msft_ai_chatbot_2023",       "b": "sow_salesforce_dynamics_2022",   "score": 0.60, "note": "both involve conversational integration"},
                {"a": "sow_msft_fabric_2024",           "b": "sow_sap_fabric_2023",            "score": 0.80, "note": "both are Fabric deployments"},
                {"a": "sow_oracle_migration_2024",      "b": "sow_salesforce_dynamics_2022",   "score": 0.40, "note": "data migration aspects overlap"},
            ]

            for sim in sow_similarities:
                q = f"""
                g.V('{sim['a']}')
                 .addE('similar_to')
                 .to(g.V('{sim['b']}'))
                 .property('score', {sim['score']})
                 .property('note', "{sim['note']}")
                """
                await self.gremlin_client.execute_query(q)
                print(f"    ✓ Linked similar SOWs: {sim['a']} ~ {sim['b']} (score={sim['score']})")
            
            print("  ✅ Graph data upload completed")

        except (RetryError, GremlinServerError) as e:
            # Unwrap RetryError if needed for nicer messaging
            inner = e
            if isinstance(e, RetryError) and hasattr(e, 'last_attempt'):
                try:
                    inner = e.last_attempt.exception()
                except Exception:
                    inner = e

            print(f"  ⚠️  Gremlin server error while uploading graph data: {inner}")
            print("   -> If this is a NotFound error, ensure the Gremlin graph/collection exists. See scripts/infra/deploy.ps1.")
            # Do not raise - treat as non-fatal for init
            return

        except Exception as e:
            print(f"  ❌ Failed to upload graph data: {e}")
            # Preserve original behavior for unexpected errors
            raise

    async def ensure_cosmos_containers(self):
        """Best-effort creation of Cosmos DB SQL containers using az CLI.

        This uses the `az` CLI with AAD credentials. If the current principal
        lacks the necessary management permissions this will warn and continue.
        We create the chat history container here so init_data can be used to
        fully prepare a dev environment.
        """
        rg = os.environ.get('CONTAINER_APP_RESOURCE_GROUP') or os.environ.get('CONTAINER_APP_RESOURCEGROUP')
        if not rg:
            print("⚠️  CONTAINER_APP_RESOURCE_GROUP not set in environment; skipping Cosmos container provisioning.")
            return

        cos_end = settings.cosmos_db.endpoint
        if not cos_end:
            print("⚠️  COSMOS_ENDPOINT not configured in settings; skipping container creation.")
            return

        # Extract account name from endpoint (https://{account}.documents.azure.com)
        acct = cos_end.replace('https://', '').split('.')[0]
        db_name = settings.cosmos_db.database_name
        # Essential containers for unified Cosmos DB storage
        container_fields = [
            'chat_container',  # Unified container for sessions, messages, cache, feedback
            'agent_functions_container',  # Agent and tool function definitions
            'prompts_container',  # System prompts
            'sql_schema_container',  # Database schema information
        ]
        containers = []
        for f in container_fields:
            val = getattr(settings.cosmos_db, f, None)
            if val:
                containers.append(val)

        if not acct or not db_name or not containers:
            print("⚠️  Insufficient Cosmos settings to create container; skipping.")
            return

        print(f"🔧 Ensuring Cosmos containers exist in DB '{db_name}' on account '{acct}' (rg: {rg}) using Azure CLI (required)")

        import subprocess
        import shutil

        if not shutil.which("az"):
            print("\nERROR: Azure CLI ('az') was not found in PATH. This initializer requires the Azure CLI for provisioning and will not attempt any SDK or key-based fallbacks.")
            print("Please install Azure CLI: https://learn.microsoft.com/cli/azure/install-azure-cli and then authenticate with an account that has permissions to create Cosmos resources:")
            print("  1) Open a terminal and run: az login")
            print("  2) Optionally set the subscription: az account set --subscription <SUBSCRIPTION_ID>")
            print("  3) Re-run this script: python ./scripts/test_env/init_data.py\n")
            # Exit cleanly with non-zero status so CI/automation can detect failure without a stacktrace
            sys.exit(2)

        az_exe = shutil.which("az")
        if not az_exe:
            print("\nERROR: Azure CLI ('az') was not found in PATH. This initializer requires the Azure CLI for provisioning and will not attempt any SDK or key-based fallbacks.")
            print("Please install Azure CLI: https://learn.microsoft.com/cli/azure/install-azure-cli and then authenticate with an account that has permissions to create Cosmos resources:")
            print("  1) Open a terminal and run: az login")
            print("  2) Optionally set the subscription: az account set --subscription <SUBSCRIPTION_ID>")
            print("  3) Re-run this script: python ./scripts/test_env/init_data.py\n")
            sys.exit(2)

        def run_az_command(cmd: List[str], timeout: int = 30):
            """Run az command using absolute az executable, return (rc, stdout, stderr).

            We use a small timeout to avoid hangs; caller should handle non-zero rc.
            """
            cmd0 = list(cmd)
            cmd0[0] = az_exe
            try:
                res = subprocess.run(cmd0, check=False, capture_output=True, text=True, timeout=timeout)
                return res.returncode, res.stdout, res.stderr
            except subprocess.TimeoutExpired as e:
                return -1, "", f"Timeout after {timeout}s: {e}"

        # Check if database exists first
        show_db_cmd = [
            "az", "cosmosdb", "sql", "database", "show",
            "--account-name", acct,
            "--resource-group", rg,
            "--name", db_name,
        ]
        rc, out, err = run_az_command(show_db_cmd, timeout=20)
        if rc == 0:
            print(f"  ✓ Cosmos SQL database '{db_name}' already exists.")
        else:
            print(f"  ➤ Creating Cosmos SQL database '{db_name}' (account={acct}, rg={rg})")
            create_db_cmd = [
                "az", "cosmosdb", "sql", "database", "create",
                "--account-name", acct,
                "--resource-group", rg,
                "--name", db_name,
            ]
            rc, out, err = run_az_command(create_db_cmd, timeout=60)
            if rc != 0:
                print(f"    ERROR creating database: rc={rc}\nstdout={out}\nstderr={err}")
            else:
                print(f"    ✓ Created database '{db_name}'.")

        # Iterate through configured containers and ensure each exists
        for container_name in containers:
            print(f"  ➤ Ensuring container '{container_name}' in DB '{db_name}'...")
            show_cont_cmd = [
                "az", "cosmosdb", "sql", "container", "show",
                "--account-name", acct,
                "--resource-group", rg,
                "--database-name", db_name,
                "--name", container_name,
            ]
            rc, out, err = run_az_command(show_cont_cmd, timeout=20)
            if rc == 0:
                print(f"    ✓ Cosmos container '{container_name}' already exists in DB '{db_name}'.")
                continue

            print(f"    ➤ Creating Cosmos container '{container_name}' in DB '{db_name}'")
            create_cont_cmd = [
                "az", "cosmosdb", "sql", "container", "create",
                "--account-name", acct,
                "--resource-group", rg,
                "--database-name", db_name,
                "--name", container_name,
                "--partition-key-path", "/id",
                "--throughput", "400",
            ]
            rc, out, err = run_az_command(create_cont_cmd, timeout=60)
            if rc != 0:
                print(f"      ERROR creating container '{container_name}': rc={rc}\nstdout={out}\nstderr={err}")
            else:
                print(f"      ✓ Created container '{container_name}'.")

    async def ensure_gremlin_graph(self):
        """Best-effort creation of Gremlin database and graph using az CLI.

        This follows the same pattern as `ensure_cosmos_containers` and will
        quietly continue if the environment lacks the resource group var or
        if the az CLI call fails due to permissions.
        """
        rg = os.environ.get('CONTAINER_APP_RESOURCE_GROUP') or os.environ.get('CONTAINER_APP_RESOURCEGROUP')
        if not rg:
            print("⚠️  CONTAINER_APP_RESOURCE_GROUP not set in environment; skipping Gremlin provisioning.")
            return

        gremlin_endpoint = os.environ.get('AZURE_COSMOS_GREMLIN_ENDPOINT') or settings.gremlin.endpoint
        gremlin_db = os.environ.get('AZURE_COSMOS_GREMLIN_DATABASE') or getattr(settings.gremlin, 'database', None) or getattr(settings.gremlin, 'database_name', None)
        gremlin_graph = os.environ.get('AZURE_COSMOS_GREMLIN_GRAPH') or getattr(settings.gremlin, 'graph', None) or getattr(settings.gremlin, 'graph_name', None)

        # If the configured graph name is the legacy or incorrect 'relationships',
        # prefer the known graph/container name 'account_graph' and prefer the
        # Gremlin database named 'graphdb' which is used in our deployments.
        if gremlin_graph and gremlin_graph.lower().startswith('relationship'):
            print(f"  ⚠️ Found legacy Gremlin graph name '{gremlin_graph}'; preferring 'account_graph' as the graph name.")
            gremlin_graph = 'account_graph'

        if not gremlin_endpoint or not gremlin_db or not gremlin_graph:
            print("⚠️  Insufficient Gremlin settings to create graph; skipping.")
            return

        # Extract account name from endpoint
        acct = gremlin_endpoint.replace('https://', '').split('.')[0]

        print(f"🔧 Creating Gremlin database '{gremlin_db}' and graph '{gremlin_graph}' on account '{acct}' (rg: {rg}) using Azure CLI (required)")

        import subprocess
        import shutil

        if not shutil.which("az"):
            print("\nERROR: Azure CLI ('az') was not found in PATH. This initializer requires the Azure CLI for provisioning and will not attempt any SDK or key-based fallbacks.")
            print("Please install Azure CLI: https://learn.microsoft.com/cli/azure/install-azure-cli and then authenticate with an account that has permissions to create Cosmos resources:")
            print("  1) Open a terminal and run: az login")
            print("  2) Optionally set the subscription: az account set --subscription <SUBSCRIPTION_ID>")
            print("  3) Re-run this script: python ./scripts/test_env/init_data.py\n")
            sys.exit(2)

        az_exe = shutil.which("az")
        if not az_exe:
            print("\nERROR: Azure CLI ('az') was not found in PATH. This initializer requires the Azure CLI for provisioning and will not attempt any SDK or key-based fallbacks.")
            print("Please install Azure CLI: https://learn.microsoft.com/cli/azure/install-azure-cli and then authenticate with an account that has permissions to create Cosmos resources:")
            print("  1) Open a terminal and run: az login")
            print("  2) Optionally set the subscription: az account set --subscription <SUBSCRIPTION_ID>")
            print("  3) Re-run this script: python ./scripts/test_env/init_data.py\n")
            sys.exit(2)

        def run_az_command(cmd: List[str], timeout: int = 30):
            cmd0 = list(cmd)
            cmd0[0] = az_exe
            try:
                res = subprocess.run(cmd0, check=False, capture_output=True, text=True, timeout=timeout)
                return res.returncode, res.stdout, res.stderr
            except subprocess.TimeoutExpired as e:
                return -1, "", f"Timeout after {timeout}s: {e}"

        # Check if gremlin database exists (use gremlin subcommand)
        show_db_cmd = [
            "az", "cosmosdb", "gremlin", "database", "show",
            "--account-name", acct,
            "--resource-group", rg,
            "--name", gremlin_db,
        ]
        rc, out, err = run_az_command(show_db_cmd, timeout=20)
        if rc == 0:
            print(f"  ✓ Gremlin database '{gremlin_db}' already exists.")
        else:
            print(f"  ➤ Creating Gremlin database '{gremlin_db}' (account={acct}, rg={rg})")
            create_db_cmd = [
                "az", "cosmosdb", "gremlin", "database", "create",
                "--account-name", acct,
                "--resource-group", rg,
                "--name", gremlin_db,
            ]
            rc, out, err = run_az_command(create_db_cmd, timeout=60)
            if rc != 0:
                print(f"    ERROR creating gremlin database: rc={rc}\nstdout={out}\nstderr={err}")
            else:
                print(f"    ✓ Created gremlin database '{gremlin_db}'.")

        # Check if graph exists
        show_graph_cmd = [
            "az", "cosmosdb", "gremlin", "graph", "show",
            "--account-name", acct,
            "--resource-group", rg,
            "--database-name", gremlin_db,
            "--name", gremlin_graph,
        ]
        rc, out, err = run_az_command(show_graph_cmd, timeout=20)
        if rc == 0:
            print(f"  ✓ Gremlin graph '{gremlin_graph}' already exists in DB '{gremlin_db}'.")
        else:
            # The configured graph was not found. Try a small set of sensible
            # existing names to handle common naming mismatches (e.g. using
            # `account_graph` instead of `relationships`). This is conservative
            # and only tries explicit alternatives rather than broad heuristics.
            print(f"  ⚠️ Gremlin graph '{gremlin_graph}' not found in DB '{gremlin_db}' (rc={rc}). Checking common alternatives...")
            tried = []
            # Try common alternative database/graph name pairs. We prefer
            # ('graphdb', 'account_graph') because our infra uses `graphdb`
            # as the Gremlin database and `account_graph` as the graph/collection.
            alternatives = [
                (gremlin_db, 'account_graph'),
                ('graphdb', 'account_graph'),
                ('account_graph', gremlin_graph),
                ('account_graph', 'account_graph'),
            ]
            found = False
            for alt_db, alt_graph in alternatives:
                if (alt_db, alt_graph) in tried:
                    continue
                tried.append((alt_db, alt_graph))
                alt_show = [
                    "az", "cosmosdb", "gremlin", "graph", "show",
                    "--account-name", acct,
                    "--resource-group", rg,
                    "--database-name", alt_db,
                    "--name", alt_graph,
                ]
                rc2, out2, err2 = run_az_command(alt_show, timeout=20)
                if rc2 == 0:
                    print(f"    ✓ Found existing Gremlin graph '{alt_graph}' in DB '{alt_db}'. Using that.")
                    # adopt the alternative names for the rest of the run
                    gremlin_db = alt_db
                    gremlin_graph = alt_graph
                    found = True
                    break

            if not found:
                print("    No common alternative Gremlin graph found. Attempting to create the configured graph.")
                create_graph_cmd = [
                    "az", "cosmosdb", "gremlin", "graph", "create",
                    "--account-name", acct,
                    "--resource-group", rg,
                    "--database-name", gremlin_db,
                    "--name", gremlin_graph,
                    "--throughput", "400",
                ]
                rc, out, err = run_az_command(create_graph_cmd, timeout=60)
                if rc != 0:
                    print(f"    ERROR creating gremlin graph: rc={rc}\nstdout={out}\nstderr={err}")
                else:
                    print(f"    ✓ Created gremlin graph '{gremlin_graph}'.")

        # After creation, poll briefly for availability via a small Gremlin probe
        import time
        for i in range(6):
            try:
                await self.gremlin_client.execute_query('g.V().limit(1)')
                print("  ✓ Gremlin graph is available.")
                return
            except Exception:
                time.sleep(2)

        print("  ⚠️ Gremlin graph did not become available after provisioning attempt. It may still be initializing or permissions prevent data-plane access.")


async def main():
    """Main entry point for data initialization."""
    initializer = DataInitializer()
    await initializer.initialize_all()


if __name__ == "__main__":
    asyncio.run(main())