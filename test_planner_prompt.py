"""
Test script to check planner and prompt loading functionality.

This script tests if the planner service can properly load and use system prompts.
"""

import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Add the chatbot src to path
current_dir = os.path.dirname(__file__)
project_root = os.path.dirname(current_dir)
sys.path.insert(0, os.path.join(project_root, 'chatbot', 'src'))

from chatbot.config.settings import settings
from chatbot.clients.cosmos_client import CosmosDBClient
from chatbot.repositories.prompts_repository import PromptsRepository
from chatbot.repositories.agent_functions_repository import AgentFunctionsRepository
from chatbot.services.rbac_service import RBACService
from chatbot.services.planner_service import PlannerService
from chatbot.models.rbac import RBACContext
from semantic_kernel import Kernel

async def test_planner_and_prompt():
    """Test planner service initialization and prompt loading."""

    print("=== Testing Planner and Prompt Loading ===\n")

    # Initialize Cosmos client
    print("1. Initializing Cosmos DB client...")
    try:
        cosmos_client = CosmosDBClient(
            endpoint=settings.cosmos_endpoint,
            database_name=settings.cosmos_database,
            container_names=settings.cosmos_containers
        )
        await cosmos_client.initialize()
        print("✓ Cosmos DB client initialized")
    except Exception as e:
        print(f"✗ Failed to initialize Cosmos DB client: {e}")
        return

    # Initialize repositories
    print("\n2. Initializing repositories...")
    try:
        prompts_repo = PromptsRepository(
            cosmos_client=cosmos_client.cosmos_client,
            database_name=settings.cosmos_database,
            container_name="prompts"
        )
        print("✓ Prompts repository initialized")

        agent_functions_repo = AgentFunctionsRepository(
            cosmos_client=cosmos_client.cosmos_client,
            database_name=settings.cosmos_database,
            container_name="agent_functions"
        )
        print("✓ Agent functions repository initialized")
    except Exception as e:
        print(f"✗ Failed to initialize repositories: {e}")
        return

    # Test prompt retrieval
    print("\n3. Testing prompt retrieval...")
    try:
        prompt = await prompts_repo.get_system_prompt(
            agent_name="planner_system",
            tenant_id="74c77be6-1ad3-4957-a4f2-94028372d7d6",
            scenario="general"
        )
        if prompt:
            print("✓ Planner system prompt retrieved successfully")
            print(f"   Prompt length: {len(prompt)} characters")
            print(f"   First 200 chars: {prompt[:200]}...")
        else:
            print("✗ No planner system prompt found")
    except Exception as e:
        print(f"✗ Failed to retrieve prompt: {e}")
        return

    # Initialize RBAC service
    print("\n4. Initializing RBAC service...")
    try:
        rbac_service = RBACService()
        print("✓ RBAC service initialized")
    except Exception as e:
        print(f"✗ Failed to initialize RBAC service: {e}")
        return

    # Initialize Semantic Kernel
    print("\n5. Initializing Semantic Kernel...")
    try:
        kernel = Kernel()
        print("✓ Semantic Kernel initialized")
    except Exception as e:
        print(f"✗ Failed to initialize Semantic Kernel: {e}")
        return

    # Initialize planner service
    print("\n6. Initializing planner service...")
    try:
        planner_service = PlannerService(
            kernel=kernel,
            agent_functions_repo=agent_functions_repo,
            prompts_repo=prompts_repo,
            rbac_service=rbac_service
        )
        print("✓ Planner service initialized")
    except Exception as e:
        print(f"✗ Failed to initialize planner service: {e}")
        return

    # Test plan creation
    print("\n7. Testing plan creation...")
    try:
        rbac_context = RBACContext(
            user_id="test-user",
            tenant_id="74c77be6-1ad3-4957-a4f2-94028372d7d6",
            email="test@example.com",
            roles=[],
            permissions=["read:sales", "read:contacts"],
            is_admin=False
        )

        plan = await planner_service.create_plan(
            user_request="What are Salesforce's relationships?",
            rbac_context=rbac_context
        )

        print("✓ Plan created successfully")
        print(f"   Plan ID: {plan.id}")
        print(f"   Plan type: {plan.plan_type}")
        print(f"   Steps: {len(plan.steps)}")
        for i, step in enumerate(plan.steps):
            print(f"   Step {i+1}: {step.tool_decision.tool_name}")

    except Exception as e:
        print(f"✗ Failed to create plan: {e}")
        import traceback
        traceback.print_exc()
        return

    print("\n=== Test completed successfully ===")

if __name__ == "__main__":
    asyncio.run(test_planner_and_prompt())