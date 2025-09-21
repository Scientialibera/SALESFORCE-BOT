"""
Deterministic uploader for prompts and agent function definitions.

Loads .env, imports application settings and repository classes, and uploads
system prompts and function/agent definitions from scripts/assets.

Run this after `scripts/set_env.ps1` so .env contains the correct AOAI_* and COSMOS_* values.

Security note: this script does NOT use or recommend account keys. Management/provisioning
operations (when attempted) are performed via the Azure CLI (AAD) and require an authenticated
principal with appropriate permissions. If you lack permissions, pre-create the Cosmos resources
instead of relying on CLI provisioning.
"""

import argparse
import asyncio
import json
import os
import sys
import subprocess
import shutil
import time
import platform

# Ensure repo src is on path so we import the app consistently
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'chatbot', 'src'))

# Load .env if present so the uploader uses the same values as the app
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
if os.path.exists(env_path):
    print(f'Loading environment from {env_path}')
    with open(env_path, 'r', encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln.startswith('#'):
                continue
            if '=' in ln:
                k, v = ln.split('=', 1)
                # only set non-empty values to avoid pydantic dotenv parsing issues
                if v.strip() != '':
                    os.environ.setdefault(k.strip(), v.strip())

try:
    from chatbot.config.settings import settings
    from chatbot.clients.cosmos_client import CosmosDBClient
    from chatbot.repositories.prompts_repository import PromptsRepository
    from chatbot.repositories.agent_functions_repository import AgentFunctionsRepository
except Exception as e:
    print('\nERROR: failed to import application modules. Make sure you ran scripts/set_env.ps1 and that .env contains the required values (AOAI_*, COSMOS_*, SEARCH_*, etc).')
    print('Import error:', e)
    sys.exit(2)

ASSETS_PROMPTS = os.path.join(os.path.dirname(__file__), 'assets', 'prompts')
ASSETS_FUNCTIONS = os.path.join(os.path.dirname(__file__), 'assets', 'functions')
ASSETS_FUNCTIONS_TOOLS = os.path.join(ASSETS_FUNCTIONS, 'tools')
ASSETS_FUNCTIONS_AGENTS = os.path.join(ASSETS_FUNCTIONS, 'agents')

def provision_cosmos_via_az(endpoint: str, database: str, containers: list, dry_run: bool = False, resource_group: str | None = None):
    """Best-effort: use Azure CLI to create database and containers using AAD credentials.

    This function performs management operations through the Azure CLI and requires the
    signed-in principal to have sufficient privileges. If the CLI or permissions are not
    available, the function will skip provisioning and the uploader will fail with an
    actionable error explaining the required pre-steps.
    """
    # endpoint looks like https://<account>.documents.azure.com:443/
    try:
        parsed = endpoint.replace('https://', '').split('.')[0]
        account = parsed
    except Exception:
        print('Could not parse Cosmos account name from endpoint', endpoint)
        return

    # If a resource_group was provided, use it; otherwise try to discover via az
    rg = resource_group
    if not rg:
        try:
            rg_lookup = subprocess.run([
                'az','resource','list','--resource-type','Microsoft.DocumentDB/databaseAccounts','--query','[?contains(name, `'+account+'`)]','-o','json'
            ], capture_output=True, text=True, check=False)
            if rg_lookup.returncode == 0 and rg_lookup.stdout:
                data = json.loads(rg_lookup.stdout)
                if isinstance(data, list) and len(data) > 0:
                    rg = data[0].get('resourceGroup')
                else:
                    rg = None
            else:
                rg = None
        except Exception:
            rg = None

    if not rg:
        print('Could not detect resource group for Cosmos account', account, '— skipping az provisioning. Please create resources manually or provide --resource-group.')
        return

    print(f'Provisioning Cosmos DB {database} and containers in account {account} (resource group {rg}) using Azure CLI...')

    # Create database
    db_cmd = ['az','cosmosdb','sql','database','create','--account-name',account,'-g',rg,'--name',database]
    if dry_run:
        print('[dry-run]', ' '.join(db_cmd))
    else:
        subprocess.run(db_cmd, check=False, shell=(platform.system() == 'Windows'))

    # Create containers
    for c in containers:
        print('Ensuring container', c)
        container_cmd = [
            'az','cosmosdb','sql','container','create','--account-name',account,'-g',rg,'--database-name',database,'--name',c,'--partition-key-path','/id','--throughput','400'
        ]
        if dry_run:
            print('[dry-run]', ' '.join(container_cmd))
        else:
            subprocess.run(container_cmd, check=False, shell=(platform.system() == 'Windows'))

async def upload_prompts(prompts_repo):
    print('Uploading prompts...')
    if not os.path.isdir(ASSETS_PROMPTS):
        print('No prompts directory found at', ASSETS_PROMPTS)
        return
    for fname in os.listdir(ASSETS_PROMPTS):
        if not fname.endswith('.md'):
            continue
        path = os.path.join(ASSETS_PROMPTS, fname)
        agent_name = os.path.splitext(fname)[0]
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        prompt_id = f'prompt_{agent_name}'
        try:
            await prompts_repo.delete_prompt(prompt_id)
        except Exception:
            pass
        await prompts_repo.save_prompt(prompt_id=prompt_id, agent_name=agent_name, prompt_type='system', content=content)
        print('Uploaded', fname)

async def upload_functions(functions_repo):
    print('Uploading function definitions...')
    
    # Upload tools
    if os.path.isdir(ASSETS_FUNCTIONS_TOOLS):
        for fname in os.listdir(ASSETS_FUNCTIONS_TOOLS):
            if not fname.endswith('.json'):
                continue
            path = os.path.join(ASSETS_FUNCTIONS_TOOLS, fname)
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for func in data.get('functions', []):
                name = func.get('name')
                try:
                    from chatbot.models.result import ToolDefinition
                    td = ToolDefinition(
                        name=name, 
                        description=func.get('description', ''), 
                        parameters=func.get('parameters', {}), 
                        metadata=func.get('metadata', {})
                    )
                    try:
                        await functions_repo.delete_function_definition(name)
                    except Exception:
                        pass
                    agents = func.get('agents') or func.get('metadata', {}).get('agents') or ['sql_agent', 'graph_agent']
                    await functions_repo.save_function_definition(td, agents=agents)
                    print('Uploaded tool function', name, 'agents=', agents)
                except Exception as e:
                    print('Failed to upload tool function', name, 'error:', e)

    # Upload agents
    if os.path.isdir(ASSETS_FUNCTIONS_AGENTS):
        for fname in os.listdir(ASSETS_FUNCTIONS_AGENTS):
            if not fname.endswith('.json'):
                continue
            path = os.path.join(ASSETS_FUNCTIONS_AGENTS, fname)
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            agent_id = data.get('id') or data.get('name')
            agents_list = data.get('agents') or [data.get('name')]
            try:
                from chatbot.models.result import ToolDefinition
                td = ToolDefinition(
                    name=agent_id, 
                    description=data.get('description', ''), 
                    parameters=data.get('parameters', {}), 
                    metadata=data.get('metadata', {})
                )
                try:
                    await functions_repo.delete_function_definition(agent_id)
                except Exception:
                    pass
                await functions_repo.save_function_definition(td, agents=agents_list)
                print('Uploaded agent registration', agent_id, 'agents=', agents_list)
            except Exception as e:
                print('Failed to upload agent registration', agent_id, 'error:', e)

async def main():
    print('Connecting to Cosmos using application settings...')
    cosmos_conf = settings.cosmos_db
    # Provision Cosmos resources via Azure CLI using AAD (no account keys are used)
    # Note: helper is defined at module scope so it can be invoked from both main() and __main__.
    
    
    # ...existing code...

    # Gather list of containers we will need
    containers_to_ensure = [
        cosmos_conf.chat_container,
        cosmos_conf.cache_container,
        cosmos_conf.prompts_container,
        cosmos_conf.agent_functions_container,
        cosmos_conf.sql_schema_container,
        cosmos_conf.contracts_text_container,
        cosmos_conf.processed_files_container,
        cosmos_conf.account_resolver_container,
        cosmos_conf.feedback_container,
    ]
    provision_cosmos_via_az(cosmos_conf.endpoint, cosmos_conf.database_name, containers_to_ensure)

    client = CosmosDBClient(cosmos_conf)
    try:
        await client._get_client()
    except Exception as e:
        print('\nERROR: failed to initialize Cosmos client. This is likely an authentication/permission error or network issue.')
        print('Exception:', e)
        print('\nIf you are using AAD tokens, ensure the signed-in principal has data-plane RBAC (Cosmos DB Built-in Data Contributor) or pre-create the database/containers before running this script.')
        sys.exit(3)

    prompts_repo = PromptsRepository(client, cosmos_conf.database_name, cosmos_conf.prompts_container)
    functions_repo = AgentFunctionsRepository(client, cosmos_conf.database_name, cosmos_conf.agent_functions_container)

    await upload_prompts(prompts_repo)
    await upload_functions(functions_repo)

    print('Upload complete.')

def parse_args():
    p = argparse.ArgumentParser(description='Upload prompts and functions, with optional Cosmos provisioning (AAD/az).')
    p.add_argument('--provision-only', action='store_true', help='Only run Cosmos provisioning then exit.')
    p.add_argument('--dry-run', action='store_true', help='Show az commands without executing them.')
    p.add_argument('--yes', '-y', action='store_true', help='Assume yes for confirmation prompts.')
    p.add_argument('--resource-group', '-g', dest='resource_group', help='Resource group for the Cosmos account (optional).')
    return p.parse_args()


if __name__ == '__main__':
    args = parse_args()

    # Allow admins to run provisioning without performing the upload
    if args.provision_only:
        print('Running provisioning only (no uploads).')
        cosmos_conf = settings.cosmos_db
        containers_to_ensure = [
            cosmos_conf.chat_container,
            cosmos_conf.cache_container,
            cosmos_conf.prompts_container,
            cosmos_conf.agent_functions_container,
            cosmos_conf.sql_schema_container,
            cosmos_conf.contracts_text_container,
            cosmos_conf.processed_files_container,
            cosmos_conf.account_resolver_container,
            cosmos_conf.feedback_container,
        ]
        if not args.yes:
            resp = input('Proceed to provision Cosmos DB resources using Azure CLI? (y/N): ')
            if resp.strip().lower() not in ('y', 'yes'):
                print('Aborting.')
                sys.exit(0)
        # prefer explicit CLI resource-group, then fallback to environment var CONTAINER_APP_RESOURCE_GROUP
        rg = args.resource_group or os.environ.get('CONTAINER_APP_RESOURCE_GROUP')
        provision_cosmos_via_az(cosmos_conf.endpoint, cosmos_conf.database_name, containers_to_ensure, dry_run=args.dry_run, resource_group=rg)
        print('Provisioning step complete.')
        sys.exit(0)

    # Default behavior: run uploads (will also attempt best-effort provisioning)
    if args.dry_run:
        print('Dry-run: provisioning commands will be printed but not executed.')
    # If a resource group was provided on the CLI, expose it via env for main()
    if args.resource_group:
        os.environ.setdefault('CONTAINER_APP_RESOURCE_GROUP', args.resource_group)
    asyncio.run(main())