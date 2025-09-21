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

# Add the src directory to Python path
current_dir = Path(__file__).parent
# Go up to project root, then into chatbot/src
project_root = current_dir.parent.parent
src_dir = project_root / "chatbot" / "src"
sys.path.insert(0, str(src_dir))

from chatbot.config.settings import settings
from chatbot.clients.cosmos_client import CosmosDBClient
from chatbot.clients.gremlin_client import GremlinClient


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
            
        except Exception as e:
            print(f"  ❌ Failed to upload graph data: {e}")
            raise


async def main():
    """Main entry point for data initialization."""
    initializer = DataInitializer()
    await initializer.initialize_all()


if __name__ == "__main__":
    asyncio.run(main())