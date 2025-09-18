"""
Repository for managing agent function definitions and configurations.

This module handles storage and retrieval of function definitions,
tool schemas, and agent capabilities from Cosmos DB.
"""

import json
from typing import Any, Dict, List, Optional
from datetime import datetime
import structlog

from azure.cosmos import exceptions as cosmos_exceptions
from azure.cosmos.aio import CosmosClient

from chatbot.models.result import ToolDefinition

logger = structlog.get_logger(__name__)


class AgentFunctionsRepository:
    """Repository for managing agent function definitions."""
    
    def __init__(self, cosmos_client: CosmosClient, database_name: str, container_name: str):
        """
        Initialize the agent functions repository.
        
        Args:
            cosmos_client: Azure Cosmos DB client
            database_name: Cosmos database name
            container_name: Container name for functions
        """
        self.cosmos_client = cosmos_client
        self.database_name = database_name
        self.container_name = container_name
        self._container = None
        
    async def _get_container(self):
        """Get or create the container reference."""
        if self._container is None:
            database = self.cosmos_client.get_database_client(self.database_name)
            self._container = database.get_container_client(self.container_name)
        return self._container
    
    async def get_function_definition(self, function_name: str) -> Optional[ToolDefinition]:
        """
        Get a function definition by name.
        
        Args:
            function_name: Name of the function
            
        Returns:
            Function definition or None if not found
        """
        try:
            container = await self._get_container()
            
            query = "SELECT * FROM c WHERE c.name = @function_name"
            parameters = [{"name": "@function_name", "value": function_name}]
            
            items = []
            async for item in container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True
            ):
                items.append(item)
            
            if items:
                function_data = items[0]
                return ToolDefinition(
                    name=function_data["name"],
                    description=function_data["description"],
                    parameters=function_data.get("parameters", {}),
                    metadata=function_data.get("metadata", {}),
                )
            
            return None
            
        except cosmos_exceptions.CosmosResourceNotFoundError:
            logger.warning("Function definition not found", function_name=function_name)
            return None
        except Exception as e:
            logger.error(
                "Failed to get function definition",
                function_name=function_name,
                error=str(e)
            )
            raise
    
    async def get_functions_by_agent(self, agent_name: str) -> List[ToolDefinition]:
        """
        Get all function definitions for a specific agent.
        
        Args:
            agent_name: Name of the agent
            
        Returns:
            List of function definitions
        """
        try:
            container = await self._get_container()
            
            query = "SELECT * FROM c WHERE ARRAY_CONTAINS(c.agents, @agent_name)"
            parameters = [{"name": "@agent_name", "value": agent_name}]
            
            functions = []
            async for item in container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True
            ):
                functions.append(ToolDefinition(
                    name=item["name"],
                    description=item["description"],
                    parameters=item.get("parameters", {}),
                    metadata=item.get("metadata", {}),
                ))
            
            logger.info(
                "Retrieved functions for agent",
                agent_name=agent_name,
                function_count=len(functions)
            )
            
            return functions
            
        except Exception as e:
            logger.error(
                "Failed to get functions for agent",
                agent_name=agent_name,
                error=str(e)
            )
            raise
    
    async def save_function_definition(self, function_def: ToolDefinition, agents: List[str]) -> str:
        """
        Save or update a function definition.
        
        Args:
            function_def: Function definition to save
            agents: List of agent names that can use this function
            
        Returns:
            Function ID
        """
        try:
            container = await self._get_container()
            
            function_data = {
                "id": function_def.name,
                "name": function_def.name,
                "description": function_def.description,
                "parameters": function_def.parameters,
                "metadata": function_def.metadata,
                "agents": agents,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }
            
            await container.upsert_item(function_data)
            
            logger.info(
                "Saved function definition",
                function_name=function_def.name,
                agents=agents
            )
            
            return function_def.name
            
        except Exception as e:
            logger.error(
                "Failed to save function definition",
                function_name=function_def.name,
                error=str(e)
            )
            raise
    
    async def delete_function_definition(self, function_name: str) -> bool:
        """
        Delete a function definition.
        
        Args:
            function_name: Name of the function to delete
            
        Returns:
            True if deleted successfully
        """
        try:
            container = await self._get_container()
            
            await container.delete_item(
                item=function_name,
                partition_key=function_name
            )
            
            logger.info("Deleted function definition", function_name=function_name)
            return True
            
        except cosmos_exceptions.CosmosResourceNotFoundError:
            logger.warning("Function definition not found for deletion", function_name=function_name)
            return False
        except Exception as e:
            logger.error(
                "Failed to delete function definition",
                function_name=function_name,
                error=str(e)
            )
            raise
    
    async def list_all_functions(self) -> List[ToolDefinition]:
        """
        List all available function definitions.
        
        Returns:
            List of all function definitions
        """
        try:
            container = await self._get_container()
            
            functions = []
            async for item in container.read_all_items():
                functions.append(ToolDefinition(
                    name=item["name"],
                    description=item["description"],
                    parameters=item.get("parameters", {}),
                    metadata=item.get("metadata", {}),
                ))
            
            logger.info("Retrieved all function definitions", function_count=len(functions))
            return functions
            
        except Exception as e:
            logger.error("Failed to list function definitions", error=str(e))
            raise
