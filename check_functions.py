#!/usr/bin/env python3
"""Check what agent functions are stored in Cosmos DB"""

import asyncio
import os
from dotenv import load_dotenv
from chatbot.clients.cosmos_client import CosmosDBClient
from chatbot.repositories.agent_functions_repository import AgentFunctionsRepository
from chatbot.config.settings import settings

async def check_agent_functions():
    """Check what agent functions are in Cosmos DB"""
    
    # Load environment
    load_dotenv()
    
    # Initialize clients
    cosmos_client = CosmosDBClient(settings.cosmos_db)
    functions_repo = AgentFunctionsRepository(
        cosmos_client,
        settings.cosmos_db.database_name,
        settings.cosmos_db.agent_functions_container
    )
    
    print("Checking agent functions in Cosmos DB...")
    print("=" * 60)
    
    try:
        # List all functions
        all_functions = await functions_repo.list_functions()
        print(f"Total functions found: {len(all_functions)}")
        print()
        
        for func in all_functions:
            print(f"Function: {func.name}")
            print(f"Description: {func.description}")
            print(f"Parameters: {func.parameters}")
            print(f"Metadata: {func.metadata}")
            print("-" * 40)
        
        # Check specific agents
        print("\nChecking functions for specific agents:")
        print("=" * 60)
        
        agents = ["sql_agent", "graph_agent"]
        
        for agent in agents:
            print(f"\nFunctions for {agent}:")
            agent_functions = await functions_repo.get_functions_for_agent(agent)
            print(f"Found {len(agent_functions)} functions")
            
            for func in agent_functions:
                print(f"  - {func.name}: {func.description}")
        
        # Check if specific function exists
        print("\nChecking if 'sql_agent' function exists:")
        sql_func = await functions_repo.get_function("sql_agent")
        if sql_func:
            print(f"✅ Found sql_agent function: {sql_func.description}")
        else:
            print("❌ sql_agent function not found")
            
        print("\nChecking if 'graph_agent' function exists:")
        graph_func = await functions_repo.get_function("graph_agent")
        if graph_func:
            print(f"✅ Found graph_agent function: {graph_func.description}")
        else:
            print("❌ graph_agent function not found")
            
    except Exception as e:
        print(f"Error checking functions: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(check_agent_functions())