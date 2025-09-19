"""
Upload dummy graph data to Cosmos DB Gremlin API for testing.

This script creates sample account relationships and hierarchies
for testing the Graph agent functionality.
"""

import asyncio
import sys
import os
from typing import Dict, Any, List
import structlog

# Add the source directory to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", "chatbot", "src"))

from chatbot.clients.gremlin_client import GremlinClient
from chatbot.config.settings import settings

logger = structlog.get_logger(__name__)


class DummyGraphDataUploader:
    """Upload dummy graph data for testing."""
    
    def __init__(self):
        """Initialize the uploader with Gremlin client."""
        self.gremlin_client = GremlinClient(
            endpoint=settings.gremlin.endpoint,
            database=settings.gremlin.database,
            graph=settings.gremlin.graph,
            username=settings.gremlin.username,
            password=settings.gremlin.password
        )
    
    async def upload_dummy_data(self):
        """Upload all dummy data to the graph database."""
        try:
            logger.info("Starting dummy graph data upload")
            
            # Clear existing data first
            await self.clear_existing_data()
            
            # Upload vertices (accounts)
            await self.upload_accounts()
            
            # Upload edges (relationships)
            await self.upload_relationships()
            
            logger.info("Dummy graph data upload completed successfully")
            
        except Exception as e:
            logger.error("Failed to upload dummy graph data", error=str(e))
            raise
    
    async def clear_existing_data(self):
        """Clear existing data from the graph."""
        logger.info("Clearing existing graph data")
        
        # Drop all edges first, then vertices
        await self.gremlin_client.execute_query("g.E().drop()")
        await self.gremlin_client.execute_query("g.V().drop()")
        
        logger.info("Existing graph data cleared")
    
    async def upload_accounts(self):
        """Upload sample account vertices."""
        logger.info("Uploading account vertices")
        
        accounts = [
            {
                "id": "acc_001",
                "name": "TechCorp Industries",
                "industry": "Technology",
                "revenue": 50000000,
                "employees": 500,
                "location": "San Francisco, CA",
                "account_type": "Enterprise"
            },
            {
                "id": "acc_002", 
                "name": "Global Manufacturing Ltd",
                "industry": "Manufacturing",
                "revenue": 120000000,
                "employees": 1200,
                "location": "Detroit, MI",
                "account_type": "Enterprise"
            },
            {
                "id": "acc_003",
                "name": "TechCorp Solutions",
                "industry": "Technology", 
                "revenue": 25000000,
                "employees": 250,
                "location": "Austin, TX",
                "account_type": "Mid-Market"
            },
            {
                "id": "acc_004",
                "name": "Retail Giant Corp",
                "industry": "Retail",
                "revenue": 300000000,
                "employees": 5000,
                "location": "New York, NY",
                "account_type": "Enterprise"
            },
            {
                "id": "acc_005",
                "name": "FinanceFirst Bank",
                "industry": "Financial Services",
                "revenue": 75000000,
                "employees": 800,
                "location": "Chicago, IL",
                "account_type": "Enterprise"
            },
            {
                "id": "acc_006",
                "name": "MedDevice Innovations",
                "industry": "Healthcare",
                "revenue": 40000000,
                "employees": 300,
                "location": "Boston, MA",
                "account_type": "Mid-Market"
            },
            {
                "id": "acc_007",
                "name": "CloudTech Partners",
                "industry": "Technology",
                "revenue": 15000000,
                "employees": 150,
                "location": "Seattle, WA",
                "account_type": "SMB"
            },
            {
                "id": "acc_008",
                "name": "Energy Solutions Inc",
                "industry": "Energy",
                "revenue": 90000000,
                "employees": 600,
                "location": "Houston, TX",
                "account_type": "Enterprise"
            }
        ]
        
        for account in accounts:
            query = f"""
            g.addV('account')
             .property('id', '{account["id"]}')
             .property('name', '{account["name"]}')
             .property('industry', '{account["industry"]}')
             .property('revenue', {account["revenue"]})
             .property('employees', {account["employees"]})
             .property('location', '{account["location"]}')
             .property('account_type', '{account["account_type"]}')
            """
            await self.gremlin_client.execute_query(query)
            logger.info(f"Added account: {account['name']}")
    
    async def upload_relationships(self):
        """Upload sample relationship edges."""
        logger.info("Uploading relationship edges")
        
        relationships = [
            # Parent-child relationships
            {
                "from_id": "acc_001",
                "to_id": "acc_003", 
                "relationship": "parent_company",
                "strength": 1.0,
                "since": "2020-01-01"
            },
            # Partnership relationships
            {
                "from_id": "acc_001",
                "to_id": "acc_007",
                "relationship": "technology_partner", 
                "strength": 0.8,
                "since": "2022-06-15"
            },
            {
                "from_id": "acc_002",
                "to_id": "acc_008",
                "relationship": "supplier",
                "strength": 0.7,
                "since": "2021-03-10"
            },
            # Customer relationships
            {
                "from_id": "acc_004",
                "to_id": "acc_001",
                "relationship": "customer",
                "strength": 0.9,
                "since": "2019-08-20"
            },
            {
                "from_id": "acc_005",
                "to_id": "acc_006",
                "relationship": "customer",
                "strength": 0.6,
                "since": "2023-01-15"
            },
            # Competitor relationships
            {
                "from_id": "acc_001",
                "to_id": "acc_007",
                "relationship": "competitor",
                "strength": 0.5,
                "since": "2020-01-01"
            },
            # Vendor relationships
            {
                "from_id": "acc_006",
                "to_id": "acc_002",
                "relationship": "vendor",
                "strength": 0.7,
                "since": "2022-02-28"
            },
            # Industry connections
            {
                "from_id": "acc_005",
                "to_id": "acc_004",
                "relationship": "financial_services",
                "strength": 0.6,
                "since": "2021-11-01"
            }
        ]
        
        for rel in relationships:
            query = f"""
            g.V().has('id', '{rel["from_id"]}')
             .addE('{rel["relationship"]}')
             .to(g.V().has('id', '{rel["to_id"]}'))
             .property('strength', {rel["strength"]})
             .property('since', '{rel["since"]}')
            """
            await self.gremlin_client.execute_query(query)
            logger.info(f"Added relationship: {rel['from_id']} -> {rel['to_id']} ({rel['relationship']})")


async def main():
    """Main function to upload dummy graph data."""
    uploader = DummyGraphDataUploader()
    await uploader.upload_dummy_data()


if __name__ == "__main__":
    asyncio.run(main())