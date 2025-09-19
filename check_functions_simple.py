#!/usr/bin/env python3
"""Simple script to check agent functions in Cosmos DB using partition key"""

import sys
import os
sys.path.append('chatbot/src')

from dotenv import load_dotenv
load_dotenv()

print("Checking agent functions container...")

try:
    from azure.cosmos import CosmosClient
    from azure.identity import DefaultAzureCredential
    
    endpoint = os.getenv('COSMOS_ENDPOINT')
    credential = DefaultAzureCredential()
    client = CosmosClient(endpoint, credential)
    
    database_name = os.getenv('COSMOS_DATABASE_NAME')
    container_name = os.getenv('COSMOS_AGENT_FUNCTIONS_CONTAINER', 'agent_functions')
    
    database = client.get_database_client(database_name)
    container = database.get_container_client(container_name)
    
    # Try to get specific items by their expected IDs
    expected_functions = [
        'sql_agent', 
        'graph_agent',
        'search_sql_data',
        'search_graph_data', 
        'resolve_account',
        'execute_graph_query'
    ]
    
    print(f"Checking for expected agent functions...")
    found_functions = []
    
    for func_name in expected_functions:
        try:
            # Try to read the item directly (assumes the function name is the ID)
            item = container.read_item(item=func_name, partition_key=func_name)
            found_functions.append(item)
            print(f"✅ Found: {func_name} - {item.get('description', 'No description')[:50]}...")
        except Exception as e:
            print(f"❌ Missing: {func_name} - {str(e)[:50]}...")
    
    print(f"\nSummary:")
    print(f"Found {len(found_functions)} out of {len(expected_functions)} expected functions")
    
    if len(found_functions) == 0:
        print("\n⚠️  NO AGENT FUNCTIONS FOUND!")
        print("This explains why the SQL and Graph agents are failing.")
        print("We need to upload the function definitions to Cosmos DB.")
        
        # Check if we have function definitions in the functions folder
        functions_folder = "chatbot/functions"
        if os.path.exists(functions_folder):
            print(f"\nChecking {functions_folder} for function definitions...")
            json_files = [f for f in os.listdir(functions_folder) if f.endswith('.json')]
            print(f"Found {len(json_files)} JSON files: {json_files}")
        else:
            print(f"\n❌ Functions folder {functions_folder} doesn't exist!")
            print("We need to create function definitions for the agents.")
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()