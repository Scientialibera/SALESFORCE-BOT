"""
Repository for managing system and assistant prompts.

This module handles storage and retrieval of prompts for different
agents, scenarios, and tenant configurations.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
import structlog

from azure.cosmos import exceptions as cosmos_exceptions
from azure.cosmos.aio import CosmosClient

logger = structlog.get_logger(__name__)


class PromptsRepository:
    """Repository for managing system and assistant prompts."""
    
    def __init__(self, cosmos_client: CosmosClient, database_name: str, container_name: str):
        """
        Initialize the prompts repository.
        
        Args:
            cosmos_client: Azure Cosmos DB client
            database_name: Cosmos database name
            container_name: Container name for prompts
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
    
    async def get_system_prompt(
        self,
        agent_name: str,
        tenant_id: Optional[str] = None,
        scenario: Optional[str] = None
    ) -> Optional[str]:
        """
        Get system prompt for an agent.
        
        Args:
            agent_name: Name of the agent
            tenant_id: Tenant ID for tenant-specific prompts
            scenario: Scenario name for context-specific prompts
            
        Returns:
            System prompt text or None if not found
        """
        try:
            container = await self._get_container()
            
            # Build query to find the most specific prompt available
            # Priority: tenant+scenario > tenant > scenario > default
            queries = []
            
            if tenant_id and scenario:
                queries.append({
                    "query": "SELECT * FROM c WHERE c.agent_name = @agent_name AND c.tenant_id = @tenant_id AND c.scenario = @scenario AND c.prompt_type = 'system'",
                    "params": [
                        {"name": "@agent_name", "value": agent_name},
                        {"name": "@tenant_id", "value": tenant_id},
                        {"name": "@scenario", "value": scenario}
                    ]
                })
            
            if tenant_id:
                queries.append({
                    "query": "SELECT * FROM c WHERE c.agent_name = @agent_name AND c.tenant_id = @tenant_id AND NOT IS_DEFINED(c.scenario) AND c.prompt_type = 'system'",
                    "params": [
                        {"name": "@agent_name", "value": agent_name},
                        {"name": "@tenant_id", "value": tenant_id}
                    ]
                })
            
            if scenario:
                queries.append({
                    "query": "SELECT * FROM c WHERE c.agent_name = @agent_name AND NOT IS_DEFINED(c.tenant_id) AND c.scenario = @scenario AND c.prompt_type = 'system'",
                    "params": [
                        {"name": "@agent_name", "value": agent_name},
                        {"name": "@scenario", "value": scenario}
                    ]
                })
            
            # Default prompt
            queries.append({
                "query": "SELECT * FROM c WHERE c.agent_name = @agent_name AND NOT IS_DEFINED(c.tenant_id) AND NOT IS_DEFINED(c.scenario) AND c.prompt_type = 'system'",
                "params": [
                    {"name": "@agent_name", "value": agent_name}
                ]
            })
            
            # Try queries in order of specificity
            for query_info in queries:
                items = []
                async for item in container.query_items(
                    query=query_info["query"],
                    parameters=query_info["params"],
                    enable_cross_partition_query=True
                ):
                    items.append(item)
                
                if items:
                    prompt_data = items[0]
                    logger.info(
                        "Retrieved system prompt",
                        agent_name=agent_name,
                        tenant_id=tenant_id,
                        scenario=scenario,
                        prompt_id=prompt_data["id"]
                    )
                    return prompt_data["content"]
            
            logger.warning(
                "System prompt not found",
                agent_name=agent_name,
                tenant_id=tenant_id,
                scenario=scenario
            )
            return None
            
        except Exception as e:
            logger.error(
                "Failed to get system prompt",
                agent_name=agent_name,
                tenant_id=tenant_id,
                scenario=scenario,
                error=str(e)
            )
            raise
    
    async def get_assistant_prompt(
        self,
        agent_name: str,
        tenant_id: Optional[str] = None,
        scenario: Optional[str] = None
    ) -> Optional[str]:
        """
        Get assistant prompt for an agent.
        
        Args:
            agent_name: Name of the agent
            tenant_id: Tenant ID for tenant-specific prompts
            scenario: Scenario name for context-specific prompts
            
        Returns:
            Assistant prompt text or None if not found
        """
        try:
            container = await self._get_container()
            
            # Similar logic to system prompt but for assistant prompts
            queries = []
            
            if tenant_id and scenario:
                queries.append({
                    "query": "SELECT * FROM c WHERE c.agent_name = @agent_name AND c.tenant_id = @tenant_id AND c.scenario = @scenario AND c.prompt_type = 'assistant'",
                    "params": [
                        {"name": "@agent_name", "value": agent_name},
                        {"name": "@tenant_id", "value": tenant_id},
                        {"name": "@scenario", "value": scenario}
                    ]
                })
            
            if tenant_id:
                queries.append({
                    "query": "SELECT * FROM c WHERE c.agent_name = @agent_name AND c.tenant_id = @tenant_id AND NOT IS_DEFINED(c.scenario) AND c.prompt_type = 'assistant'",
                    "params": [
                        {"name": "@agent_name", "value": agent_name},
                        {"name": "@tenant_id", "value": tenant_id}
                    ]
                })
            
            if scenario:
                queries.append({
                    "query": "SELECT * FROM c WHERE c.agent_name = @agent_name AND NOT IS_DEFINED(c.tenant_id) AND c.scenario = @scenario AND c.prompt_type = 'assistant'",
                    "params": [
                        {"name": "@agent_name", "value": agent_name},
                        {"name": "@scenario", "value": scenario}
                    ]
                })
            
            # Default prompt
            queries.append({
                "query": "SELECT * FROM c WHERE c.agent_name = @agent_name AND NOT IS_DEFINED(c.tenant_id) AND NOT IS_DEFINED(c.scenario) AND c.prompt_type = 'assistant'",
                "params": [
                    {"name": "@agent_name", "value": agent_name}
                ]
            })
            
            # Try queries in order of specificity
            for query_info in queries:
                items = []
                async for item in container.query_items(
                    query=query_info["query"],
                    parameters=query_info["params"],
                    enable_cross_partition_query=True
                ):
                    items.append(item)
                
                if items:
                    prompt_data = items[0]
                    logger.info(
                        "Retrieved assistant prompt",
                        agent_name=agent_name,
                        tenant_id=tenant_id,
                        scenario=scenario,
                        prompt_id=prompt_data["id"]
                    )
                    return prompt_data["content"]
            
            return None
            
        except Exception as e:
            logger.error(
                "Failed to get assistant prompt",
                agent_name=agent_name,
                tenant_id=tenant_id,
                scenario=scenario,
                error=str(e)
            )
            raise
    
    async def save_prompt(
        self,
        prompt_id: str,
        agent_name: str,
        prompt_type: str,
        content: str,
        tenant_id: Optional[str] = None,
        scenario: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Save or update a prompt.
        
        Args:
            prompt_id: Unique prompt identifier
            agent_name: Name of the agent
            prompt_type: Type of prompt ('system' or 'assistant')
            content: Prompt content
            tenant_id: Optional tenant ID
            scenario: Optional scenario name
            metadata: Optional additional metadata
            
        Returns:
            Prompt ID
        """
        try:
            container = await self._get_container()
            
            prompt_data = {
                "id": prompt_id,
                "agent_name": agent_name,
                "prompt_type": prompt_type,
                "content": content,
                "metadata": metadata or {},
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }
            
            # Add optional fields only if provided
            if tenant_id:
                prompt_data["tenant_id"] = tenant_id
            if scenario:
                prompt_data["scenario"] = scenario
            
            await container.upsert_item(prompt_data)
            
            logger.info(
                "Saved prompt",
                prompt_id=prompt_id,
                agent_name=agent_name,
                prompt_type=prompt_type,
                tenant_id=tenant_id,
                scenario=scenario
            )
            
            return prompt_id
            
        except Exception as e:
            logger.error(
                "Failed to save prompt",
                prompt_id=prompt_id,
                agent_name=agent_name,
                error=str(e)
            )
            raise
    
    async def list_prompts(
        self,
        agent_name: Optional[str] = None,
        tenant_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List prompts with optional filtering.
        
        Args:
            agent_name: Optional agent name filter
            tenant_id: Optional tenant ID filter
            
        Returns:
            List of prompt metadata
        """
        try:
            container = await self._get_container()
            
            # Build query with optional filters
            where_conditions = []
            parameters = []
            
            if agent_name:
                where_conditions.append("c.agent_name = @agent_name")
                parameters.append({"name": "@agent_name", "value": agent_name})
            
            if tenant_id:
                where_conditions.append("c.tenant_id = @tenant_id")
                parameters.append({"name": "@tenant_id", "value": tenant_id})
            
            where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"
            query = f"SELECT c.id, c.agent_name, c.prompt_type, c.tenant_id, c.scenario, c.created_at, c.updated_at FROM c WHERE {where_clause}"
            
            prompts = []
            async for item in container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True
            ):
                prompts.append(item)
            
            logger.info(
                "Listed prompts",
                agent_name=agent_name,
                tenant_id=tenant_id,
                count=len(prompts)
            )
            
            return prompts
            
        except Exception as e:
            logger.error(
                "Failed to list prompts",
                agent_name=agent_name,
                tenant_id=tenant_id,
                error=str(e)
            )
            raise
    
    async def delete_prompt(self, prompt_id: str) -> bool:
        """
        Delete a prompt.
        
        Args:
            prompt_id: ID of the prompt to delete
            
        Returns:
            True if deleted successfully
        """
        try:
            container = await self._get_container()
            
            await container.delete_item(
                item=prompt_id,
                partition_key=prompt_id
            )
            
            logger.info("Deleted prompt", prompt_id=prompt_id)
            return True
            
        except cosmos_exceptions.CosmosResourceNotFoundError:
            logger.warning("Prompt not found for deletion", prompt_id=prompt_id)
            return False
        except Exception as e:
            logger.error(
                "Failed to delete prompt",
                prompt_id=prompt_id,
                error=str(e)
            )
            raise
