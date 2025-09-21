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
try:
    # Management SDKs for RBAC-based provisioning
    from azure.identity import DefaultAzureCredential as MgmtDefaultAzureCredential
    from azure.mgmt.cosmosdb import CosmosDBManagementClient
    from azure.mgmt.resource import SubscriptionClient
    MGMT_SDK_AVAILABLE = True
except Exception:
    MGMT_SDK_AVAILABLE = False

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

print('\n[init_data] Effective environment (masked):')
print('  CONTAINER_APP_RESOURCE_GROUP =', _mask(os.environ.get('CONTAINER_APP_RESOURCE_GROUP') or os.environ.get('CONTAINER_APP_RESOURCEGROUP')))
print('  COSMOS_ENDPOINT =', _mask(os.environ.get('COSMOS_ENDPOINT') or os.environ.get('AZURE_COSMOS_GREMLIN_ENDPOINT')))
print('  AZURE_COSMOS_GREMLIN_ENDPOINT =', _mask(os.environ.get('AZURE_COSMOS_GREMLIN_ENDPOINT')))
print('  AZURE_COSMOS_GREMLIN_DATABASE =', _mask(os.environ.get('AZURE_COSMOS_GREMLIN_DATABASE')))
print('  AZURE_COSMOS_GREMLIN_GRAPH =', _mask(os.environ.get('AZURE_COSMOS_GREMLIN_GRAPH')))
print('  MOCK_EMBEDDINGS =', os.environ.get('MOCK_EMBEDDINGS'))
print('  CONTAINER_APP_RESOURCE_GROUP =', _mask(os.environ.get('CONTAINER_APP_RESOURCE_GROUP') or os.environ.get('CONTAINER_APP_RESOURCEGROUP')))
print('  COSMOS_ENDPOINT =', _mask(os.environ.get('COSMOS_ENDPOINT') or os.environ.get('AZURE_COSMOS_GREMLIN_ENDPOINT')))
print('  AZURE_COSMOS_GREMLIN_ENDPOINT =', _mask(os.environ.get('AZURE_COSMOS_GREMLIN_ENDPOINT')))
print('  AZURE_COSMOS_GREMLIN_DATABASE =', _mask(os.environ.get('AZURE_COSMOS_GREMLIN_DATABASE')))
print('  AZURE_COSMOS_GREMLIN_GRAPH =', _mask(os.environ.get('AZURE_COSMOS_GREMLIN_GRAPH')))
print('  MOCK_EMBEDDINGS =', os.environ.get('MOCK_EMBEDDINGS'))
print()
# ---------------------------------------------------------------

from chatbot.config.settings import settings
from chatbot.clients.cosmos_client import CosmosDBClient
from chatbot.clients.gremlin_client import GremlinClient
from gremlin_python.driver.protocol import GremlinServerError
from tenacity import RetryError


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

            # Initialize prompts
            await self.upload_prompts()
            
            # Initialize function definitions
            await self.upload_functions()
            
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
        
        # Load prompts from prompts/ folder
        prompts_dir = Path(__file__).parent / "prompts"
        
        if not prompts_dir.exists():
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
        
        # Load functions from functions/ folder
        functions_dir = Path(__file__).parent / "functions"
        
        if not functions_dir.exists():
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
                print("   -> If you need to use key auth temporarily for local debugging set AZURE_COSMOS_GREMLIN_PASSWORD in your .env (not recommended for normal usage).")
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
            # Clear existing data in dev mode
            if settings.dev_mode:
                print("  🧹 Clearing existing graph data...")
                await self.gremlin_client.execute_query("g.V().drop()")
                await self.gremlin_client.execute_query("g.E().drop()")

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
            
            # Add relationships relevant for sales planning
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
        try:
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
            chat_container = settings.cosmos_db.chat_container

            if not acct or not db_name or not chat_container:
                print("⚠️  Insufficient Cosmos settings to create container; skipping.")
                return

            print(f"🔧 Attempting to create Cosmos container '{chat_container}' in DB '{db_name}' on account '{acct}' (rg: {rg}) using RBAC via management SDK")

            if not MGMT_SDK_AVAILABLE:
                print("  ❌ Azure management SDKs not installed (azure-mgmt-cosmosdb / azure-mgmt-resource).\n     Install them or pre-create the container manually. Skipping provisioning.")
                return

            # Use DefaultAzureCredential for RBAC
            try:
                cred = MgmtDefaultAzureCredential()
                sub_client = SubscriptionClient(cred)
                subs = list(sub_client.subscriptions.list())
                if not subs:
                    print("  ❌ No subscriptions found for the current principal. Ensure you're logged in with 'az login' or running with a managed identity that has a subscription.")
                    return
                # Prefer provided subscription id from env if present
                subscription_id = os.environ.get('CONTAINER_APP_SUBSCRIPTION_ID') or subs[0].subscription_id

                mgmt = CosmosDBManagementClient(cred, subscription_id)

                # Ensure database exists
                try:
                    mgmt.cassandra_resources.get_keyspace(rg, acct, db_name)
                except Exception:
                    # Cosmos management SDK has different resource calls; use Databases -> Gremlin/Cosmos SQL DB APIs
                    pass

                # Create or update SQL container (using the SQL API through management client)
                try:
                    params = {
                        'resource': {
                            'id': chat_container,
                            'partitionKey': {'paths': ['/id'], 'kind': 'Hash'},
                        },
                        'options': {'throughput': 400}
                    }
                    mgmt.sql_resources.create_update_sql_container(rg, acct, db_name, chat_container, params)
                    print(f"  ✓ Container '{chat_container}' created or already exists (via management SDK).")
                except Exception as ex:
                    print(f"  ⚠️ Management SDK returned an error while creating container: {ex}")
                    print("  ⚠️ Ensure your principal has Cosmos DB Contributor or appropriate management role. You can also pre-create the container manually.")

            except Exception as e:
                print(f"  ❌ Error while attempting RBAC provisioning for Cosmos container: {e}")
                print("   -> Ensure you're authenticated (az login) or running in an environment with a managed identity that has subscription access.")
                return

        except Exception as e:
            print(f"  ❌ Error while attempting to create Cosmos container: {e}")
            # Do not raise; init should continue even if provisioning fails
            return

    async def ensure_gremlin_graph(self):
        """Best-effort creation of Gremlin database and graph using az CLI.

        This follows the same pattern as `ensure_cosmos_containers` and will
        quietly continue if the environment lacks the resource group var or
        if the az CLI call fails due to permissions.
        """
        try:
            rg = os.environ.get('CONTAINER_APP_RESOURCE_GROUP') or os.environ.get('CONTAINER_APP_RESOURCEGROUP')
            if not rg:
                print("⚠️  CONTAINER_APP_RESOURCE_GROUP not set in environment; skipping Gremlin provisioning.")
                return

            gremlin_endpoint = os.environ.get('AZURE_COSMOS_GREMLIN_ENDPOINT') or settings.gremlin.endpoint
            gremlin_db = os.environ.get('AZURE_COSMOS_GREMLIN_DATABASE') or settings.gremlin.database
            gremlin_graph = os.environ.get('AZURE_COSMOS_GREMLIN_GRAPH') or settings.gremlin.graph

            if not gremlin_endpoint or not gremlin_db or not gremlin_graph:
                print("⚠️  Insufficient Gremlin settings to create graph; skipping.")
                return

            # Extract account name from endpoint
            acct = gremlin_endpoint.replace('https://', '').split('.')[0]

            print(f"🔧 Attempting to create Gremlin database '{gremlin_db}' and graph '{gremlin_graph}' on account '{acct}' (rg: {rg}) using RBAC via management SDK")

            if not MGMT_SDK_AVAILABLE:
                print("  ❌ Azure management SDKs not installed (azure-mgmt-cosmosdb / azure-mgmt-resource).\n     Install them or pre-create the Gremlin graph manually. Skipping provisioning.")
                return

            try:
                cred = MgmtDefaultAzureCredential()
                sub_client = SubscriptionClient(cred)
                subs = list(sub_client.subscriptions.list())
                if not subs:
                    print("  ❌ No subscriptions found for the current principal. Ensure you're logged in with 'az login' or running with a managed identity that has a subscription.")
                    return
                subscription_id = os.environ.get('CONTAINER_APP_SUBSCRIPTION_ID') or subs[0].subscription_id

                mgmt = CosmosDBManagementClient(cred, subscription_id)

                # Create Gremlin database
                try:
                    mgmt.gremlin_resources.create_update_gremlin_database(rg, acct, gremlin_db, {'resource': {'id': gremlin_db}})
                    print(f"  ✓ Gremlin database '{gremlin_db}' created or already exists (via management SDK).")
                except Exception as ex:
                    print(f"  ⚠️ Management SDK returned an error while creating gremlin database: {ex}")

                # Create Gremlin graph
                try:
                    params = {
                        'resource': {
                            'id': gremlin_graph,
                            'partitionKey': {'paths': ['/partitionKey'], 'kind': 'Hash'}
                        },
                        'options': {'throughput': 400}
                    }
                    mgmt.gremlin_resources.create_update_gremlin_graph(rg, acct, gremlin_db, gremlin_graph, params)
                    print(f"  ✓ Gremlin graph '{gremlin_graph}' created or already exists (via management SDK).")
                except Exception as ex:
                    print(f"  ⚠️ Management SDK returned an error while creating gremlin graph: {ex}")
                    print("  ⚠️ Ensure your principal has Cosmos DB Contributor or appropriate management role. You can also pre-create the graph manually.")

                # Poll briefly to allow the graph to become available
                import time
                for i in range(6):
                    try:
                        # A tiny probe using the Gremlin client
                        await self.gremlin_client.execute_query('g.V().limit(1)')
                        print("  ✓ Gremlin graph is available.")
                        return
                    except Exception:
                        time.sleep(2)
                print("  ⚠️ Gremlin graph did not become available after provisioning attempt. It may still be initializing.")

            except Exception as e:
                print(f"  ❌ Error while attempting RBAC provisioning for Gremlin graph: {e}")
                print("   -> Ensure you're authenticated (az login) or running in an environment with a managed identity that has subscription access.")
                return

        except Exception as e:
            print(f"  ❌ Error while attempting to create Gremlin graph: {e}")
            # Do not raise; init should continue even if provisioning fails
            return


async def main():
    """Main entry point for data initialization."""
    initializer = DataInitializer()
    await initializer.initialize_all()


if __name__ == "__main__":
    asyncio.run(main())