"""
Upload prompts and agent function definitions into Cosmos DB using the app repositories.
This script reads files from scripts/assets/prompts and scripts/assets/functions and upserts them.
It deletes existing entries first to ensure a clean state.

Run: python scripts/upload_artifacts.py

Requirements: runs from repo root and uses the same settings as the app (reads .env)
"""
import asyncio
import json
import os
import sys
from typing import List

# ensure we can import the application packages
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'chatbot', 'src'))

from chatbot.config.settings import settings
from chatbot.clients.cosmos_client import CosmosDBClient
from chatbot.repositories.prompts_repository import PromptsRepository
from chatbot.repositories.agent_functions_repository import AgentFunctionsRepository

ASSETS_PROMPTS = os.path.join(os.path.dirname(__file__), 'assets', 'prompts')
ASSETS_FUNCTIONS = os.path.join(os.path.dirname(__file__), 'assets', 'functions')
ASSETS_FUNCTIONS_TOOLS = os.path.join(ASSETS_FUNCTIONS, 'tools')
ASSETS_FUNCTIONS_AGENTS = os.path.join(ASSETS_FUNCTIONS, 'agents')

async def upload_prompts(prompts_repo: PromptsRepository):
    print('Uploading prompts...')
    # Read all .md files
    for fname in os.listdir(ASSETS_PROMPTS):
        if not fname.endswith('.md'):
            continue
        path = os.path.join(ASSETS_PROMPTS, fname)
        agent_name = os.path.splitext(fname)[0]
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        prompt_id = f"prompt_{agent_name}"
        # Delete if exists
        try:
            await prompts_repo.delete_prompt(prompt_id)
        except Exception:
            pass
        # Save as system prompt default
        await prompts_repo.save_prompt(prompt_id=prompt_id, agent_name=agent_name, prompt_type='system', content=content)
        print('Uploaded', fname)

async def upload_functions(functions_repo: AgentFunctionsRepository):
    print('Uploading function definitions...')
    # Upload tool definitions (JSON files containing a 'functions' array)
    if os.path.isdir(ASSETS_FUNCTIONS_TOOLS):
        for fname in os.listdir(ASSETS_FUNCTIONS_TOOLS):
            if not fname.endswith('.json'):
                continue
            path = os.path.join(ASSETS_FUNCTIONS_TOOLS, fname)
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for func in data.get('functions', []):
                name = func.get('name')
                from chatbot.models.result import ToolDefinition
                td = ToolDefinition(name=name, description=func.get('description',''), parameters=func.get('parameters',{}), metadata=func.get('metadata',{}))
                try:
                    await functions_repo.delete_function_definition(name)
                except Exception:
                    pass
                # If metadata contains agents mapping use that, otherwise keep default mapping
                agents = func.get('agents') or func.get('metadata', {}).get('agents') or ['sql_agent','graph_agent']
                await functions_repo.save_function_definition(td, agents=agents)
                print('Uploaded tool function', name, 'agents=', agents)

    # Upload agent-level registrations (agent JSONs) - convert them into function-like entries so the planner can discover agents
    if os.path.isdir(ASSETS_FUNCTIONS_AGENTS):
        for fname in os.listdir(ASSETS_FUNCTIONS_AGENTS):
            if not fname.endswith('.json'):
                continue
            path = os.path.join(ASSETS_FUNCTIONS_AGENTS, fname)
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # Agent manifests may contain 'id' and 'agents' array or metadata
            agent_id = data.get('id') or data.get('name')
            agents_list = data.get('agents') or [data.get('name')]
            # Create a ToolDefinition wrapper so it lands in the same container and can be filtered by agent name
            from chatbot.models.result import ToolDefinition
            td = ToolDefinition(name=agent_id, description=data.get('description',''), parameters=data.get('parameters',{}), metadata=data.get('metadata',{}))
            try:
                await functions_repo.delete_function_definition(agent_id)
            except Exception:
                pass
            await functions_repo.save_function_definition(td, agents=agents_list)
            print('Uploaded agent registration', agent_id, 'agents=', agents_list)

    # All artifacts should be centralized under scripts/assets/functions

async def main():
    print('Connecting to Cosmos...')
    # Use CosmosDBClient wrapper to create an async CosmosClient
    cosmos_client = CosmosDBClient(endpoint=settings.cosmos_db.endpoint)
    await cosmos_client.initialize()
    # Instantiate repositories
    prompts_repo = PromptsRepository(cosmos_client.client, settings.cosmos_db.database_name, settings.cosmos_db.prompts_container)
    functions_repo = AgentFunctionsRepository(cosmos_client.client, settings.cosmos_db.database_name, settings.cosmos_db.agent_functions_container)

    # Run upload
    await upload_prompts(prompts_repo)
    await upload_functions(functions_repo)
    print('Upload complete.')

if __name__ == '__main__':
    asyncio.run(main())
