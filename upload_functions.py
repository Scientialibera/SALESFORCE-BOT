#!/usr/bin/env python3
"""Upload agent function definitions to Cosmos DB"""

import json
import os
from dotenv import load_dotenv

def upload_function_definitions():
    """Upload all function definitions from the functions folder to Cosmos DB"""
    
    load_dotenv()
    
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
        
        functions_folder = "chatbot/functions"
        json_files = [f for f in os.listdir(functions_folder) if f.endswith('.json')]
        
        print(f"Found {len(json_files)} function definition files")
        print("=" * 50)
        
        uploaded_count = 0
        
        for json_file in json_files:
            file_path = os.path.join(functions_folder, json_file)
            
            try:
                with open(file_path, 'r') as f:
                    function_def = json.load(f)
                
                # Ensure required fields
                if 'id' not in function_def:
                    function_def['id'] = function_def.get('name', json_file.replace('.json', ''))
                
                # Set partition key to match the ID for simplicity
                if 'metadata' not in function_def:
                    function_def['metadata'] = {}
                function_def['metadata']['partition_key'] = function_def['id']
                
                # Add timestamp
                from datetime import datetime
                function_def['uploaded_at'] = datetime.utcnow().isoformat()
                
                print(f"Uploading: {function_def['id']}")
                print(f"  Description: {function_def.get('description', 'No description')[:60]}...")
                
                # Upsert the function definition
                container.upsert_item(function_def)
                uploaded_count += 1
                print(f"  ✅ Success")
                
            except Exception as e:
                print(f"  ❌ Failed: {e}")
        
        print("=" * 50)
        print(f"Successfully uploaded {uploaded_count} out of {len(json_files)} functions")
        
        # Verify uploads
        print("\nVerifying uploads...")
        for json_file in json_files:
            file_path = os.path.join(functions_folder, json_file)
            with open(file_path, 'r') as f:
                function_def = json.load(f)
                function_id = function_def.get('id', function_def.get('name', json_file.replace('.json', '')))
            
            try:
                item = container.read_item(item=function_id, partition_key=function_id)
                print(f"✅ Verified: {function_id}")
            except Exception as e:
                print(f"❌ Verification failed for {function_id}: {e}")
                
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    upload_function_definitions()