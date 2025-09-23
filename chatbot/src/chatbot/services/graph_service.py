"""
Graph service for executing Gremlin queries with RBAC filtering.

This service handles graph traversal queries against the Cosmos DB Gremlin API
with role-based access control and relationship discovery. The graph data
is populated from the lakehouse by the data engineering team and contains
relationships extracted from Salesforce and SharePoint data.
"""

from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
import structlog

from chatbot.clients.gremlin_client import GremlinClient
from chatbot.clients.fabric_client import FabricLakehouseClient
from chatbot.models.rbac import RBACContext
from chatbot.models.result import QueryResult
from chatbot.services.unified_service import UnifiedDataService

logger = structlog.get_logger(__name__)


class GraphService:
    """Service for graph database operations with RBAC filtering."""
    
    def __init__(
        self,
        gremlin_client: GremlinClient,
        cache_service: UnifiedDataService,
        fabric_client: Optional[FabricLakehouseClient] = None,
        max_results: int = 100,
        max_traversal_depth: int = 5
    ):
        """
        Initialize the graph service.
        
        Args:
            gremlin_client: Gremlin client for graph operations
            cache_service: Cache service for query results
            fabric_client: Optional Fabric lakehouse client for document retrieval
            max_results: Maximum number of results to return
            max_traversal_depth: Maximum depth for graph traversals
        """
        self.gremlin_client = gremlin_client
        self.unified_data_service = cache_service
        self.fabric_client = fabric_client
        self.max_results = max_results
        self.max_traversal_depth = max_traversal_depth
    
    async def find_account_relationships(
        self,
        account_id: str,
        rbac_context: RBACContext,
        relationship_types: Optional[List[str]] = None,
        max_depth: Optional[int] = None
    ) -> QueryResult:
        """
        Find relationships for a specific account.
        
        Args:
            account_id: Account ID to find relationships for
            rbac_context: User's RBAC context for filtering
            relationship_types: Optional list of relationship types to include
            max_depth: Optional maximum traversal depth
            
        Returns:
            Query result with relationship data
        """
        try:
            start_time = datetime.utcnow()
            
            logger.info(
                "Finding account relationships",
                account_id=account_id,
                user_id=rbac_context.user_id,
                relationship_types=relationship_types
            )
            
            # Check cache first
            cache_key = f"relationships:{account_id}:{hash(str(relationship_types))}"
            cached_result = await self.unified_data_service.get_query_result(
                cache_key, rbac_context, "graph"
            )
            if cached_result:
                return QueryResult(**cached_result)
            
            # Build Gremlin query
            depth = min(max_depth or self.max_traversal_depth, self.max_traversal_depth)
            gremlin_query = self._build_relationship_query(
                account_id, relationship_types, depth, rbac_context
            )
            
            # Execute query
            result = await self.gremlin_client.execute_query(gremlin_query)
            
            # Process and format results
            formatted_result = self._format_relationship_results(result)
            
            # Cache the result
            execution_time = (datetime.utcnow() - start_time).total_seconds() * 1000
            query_result = QueryResult(
                success=True,
                data=formatted_result,
                metadata={
                    "account_id": account_id,
                    "relationship_types": relationship_types,
                    "max_depth": depth,
                    "result_count": len(formatted_result)
                },
                rows_affected=len(formatted_result),
                execution_time_ms=execution_time
            )
            
            await self.unified_data_service.set_query_result(
                cache_key, query_result.__dict__, rbac_context, "graph"
            )
            
            logger.info(
                "Account relationships found",
                account_id=account_id,
                user_id=rbac_context.user_id,
                relationship_count=len(formatted_result),
                execution_time_ms=execution_time
            )
            
            return query_result
            
        except Exception as e:
            logger.error(
                "Failed to find account relationships",
                account_id=account_id,
                user_id=rbac_context.user_id,
                error=str(e)
            )
            return QueryResult(
                success=False,
                error_message=f"Graph query failed: {str(e)}",
                data=[],
                metadata={},
                rows_affected=0,
                execution_time_ms=0
            )
    
    async def find_shortest_path(
        self,
        from_account: str,
        to_account: str,
        rbac_context: RBACContext,
        relationship_types: Optional[List[str]] = None
    ) -> QueryResult:
        """
        Find shortest path between two accounts.
        
        Args:
            from_account: Source account ID
            to_account: Target account ID
            rbac_context: User's RBAC context
            relationship_types: Optional relationship types to traverse
            
        Returns:
            Query result with path data
        """
        try:
            start_time = datetime.utcnow()
            
            logger.info(
                "Finding shortest path",
                from_account=from_account,
                to_account=to_account,
                user_id=rbac_context.user_id
            )
            
            # Build path-finding query
            gremlin_query = self._build_path_query(
                from_account, to_account, relationship_types, rbac_context
            )
            
            # Execute query
            result = await self.gremlin_client.execute_query(gremlin_query)
            
            # Format path results
            formatted_paths = self._format_path_results(result)
            
            execution_time = (datetime.utcnow() - start_time).total_seconds() * 1000
            
            return QueryResult(
                success=True,
                data=formatted_paths,
                metadata={
                    "from_account": from_account,
                    "to_account": to_account,
                    "path_count": len(formatted_paths),
                    "relationship_types": relationship_types
                },
                rows_affected=len(formatted_paths),
                execution_time_ms=execution_time
            )
            
        except Exception as e:
            logger.error(
                "Failed to find shortest path",
                from_account=from_account,
                to_account=to_account,
                user_id=rbac_context.user_id,
                error=str(e)
            )
            return QueryResult(
                success=False,
                error_message=f"Path finding failed: {str(e)}",
                data=[],
                metadata={},
                rows_affected=0,
                execution_time_ms=0
            )
    
    async def get_account_neighbors(
        self,
        account_id: str,
        rbac_context: RBACContext,
        neighbor_types: Optional[List[str]] = None
    ) -> QueryResult:
        """
        Get immediate neighbors of an account.
        
        Args:
            account_id: Account ID to get neighbors for
            rbac_context: User's RBAC context
            neighbor_types: Optional types of neighbors to include
            
        Returns:
            Query result with neighbor data
        """
        try:
            start_time = datetime.utcnow()
            
            # Build neighbor query
            gremlin_query = self._build_neighbor_query(
                account_id, neighbor_types, rbac_context
            )
            
            # Execute query
            result = await self.gremlin_client.execute_query(gremlin_query)
            
            # Format results
            neighbors = self._format_neighbor_results(result)
            
            execution_time = (datetime.utcnow() - start_time).total_seconds() * 1000
            
            return QueryResult(
                success=True,
                data=neighbors,
                metadata={
                    "account_id": account_id,
                    "neighbor_types": neighbor_types,
                    "neighbor_count": len(neighbors)
                },
                rows_affected=len(neighbors),
                execution_time_ms=execution_time
            )
            
        except Exception as e:
            logger.error(
                "Failed to get account neighbors",
                account_id=account_id,
                user_id=rbac_context.user_id,
                error=str(e)
            )
            return QueryResult(
                success=False,
                error_message=f"Neighbor query failed: {str(e)}",
                data=[],
                metadata={},
                rows_affected=0,
                execution_time_ms=0
            )
    
    def _build_relationship_query(
        self,
        account_id: str,
        relationship_types: Optional[List[str]],
        max_depth: int,
        rbac_context: RBACContext
    ) -> str:
        """
        Build Gremlin query for finding relationships.
        
        Args:
            account_id: Account ID to start from
            relationship_types: Optional relationship types
            max_depth: Maximum traversal depth
            rbac_context: User's RBAC context
            
        Returns:
            Gremlin query string
        """
        # Start with the account vertex
        query = f"g.V().has('account', 'id', '{account_id}')"
        
        # Add RBAC filtering for accessible accounts
        accessible_accounts = rbac_context.access_scope.allowed_accounts
        if accessible_accounts and "admin" not in rbac_context.roles:
            account_filter = "', '".join(accessible_accounts)
            query += f".has('account', 'id', within('{account_filter}'))"
        
        # Build traversal with depth limit
        if relationship_types:
            edge_filter = "', '".join(relationship_types)
            query += f".repeat(bothE().hasLabel(within('{edge_filter}')).bothV().simplePath())"
        else:
            query += ".repeat(bothE().bothV().simplePath())"
        
        query += f".times({max_depth}).path().limit({self.max_results})"
        
        return query
    
    def _build_path_query(
        self,
        from_account: str,
        to_account: str,
        relationship_types: Optional[List[str]],
        rbac_context: RBACContext
    ) -> str:
        """
        Build Gremlin query for finding shortest path.
        
        Args:
            from_account: Source account
            to_account: Target account
            relationship_types: Optional relationship types
            rbac_context: User's RBAC context
            
        Returns:
            Gremlin query string
        """
        query = f"g.V().has('account', 'id', '{from_account}')"
        
        # Add RBAC filtering
        accessible_accounts = rbac_context.access_scope.allowed_accounts
        if accessible_accounts and "admin" not in rbac_context.roles:
            account_filter = "', '".join(accessible_accounts)
            query += f".has('account', 'id', within('{account_filter}'))"
        
        # Build shortest path traversal
        if relationship_types:
            edge_filter = "', '".join(relationship_types)
            query += f".repeat(bothE().hasLabel(within('{edge_filter}')).bothV().simplePath())"
        else:
            query += ".repeat(bothE().bothV().simplePath())"
        
        query += f".until(has('account', 'id', '{to_account}')).path().limit(1)"
        
        return query
    
    def _build_neighbor_query(
        self,
        account_id: str,
        neighbor_types: Optional[List[str]],
        rbac_context: RBACContext
    ) -> str:
        """
        Build Gremlin query for finding immediate neighbors.
        
        Args:
            account_id: Account ID
            neighbor_types: Optional neighbor types
            rbac_context: User's RBAC context
            
        Returns:
            Gremlin query string
        """
        query = f"g.V().has('account', 'id', '{account_id}')"
        
        if neighbor_types:
            type_filter = "', '".join(neighbor_types)
            query += f".both().hasLabel(within('{type_filter}'))"
        else:
            query += ".both()"
        
        # Add RBAC filtering
        accessible_accounts = rbac_context.access_scope.allowed_accounts
        if accessible_accounts and "admin" not in rbac_context.roles:
            account_filter = "', '".join(accessible_accounts)
            query += f".has('account', 'id', within('{account_filter}'))"
        
        query += f".limit({self.max_results})"
        
        return query
    
    def _format_relationship_results(self, raw_results: List[Any]) -> List[Dict[str, Any]]:
        """
        Format raw Gremlin results into relationship data.
        
        Args:
            raw_results: Raw results from Gremlin query
            
        Returns:
            Formatted relationship data
        """
        relationships = []
        
        for result in raw_results:
            if hasattr(result, 'objects') and result.objects:
                path = result.objects
                
                # Extract vertices and edges from path
                for i in range(0, len(path) - 1, 2):
                    if i + 2 < len(path):
                        source = path[i]
                        edge = path[i + 1]
                        target = path[i + 2]
                        
                        relationships.append({
                            "source_id": getattr(source, 'id', str(source)),
                            "source_label": getattr(source, 'label', 'unknown'),
                            "edge_label": getattr(edge, 'label', 'unknown'),
                            "target_id": getattr(target, 'id', str(target)),
                            "target_label": getattr(target, 'label', 'unknown'),
                            "properties": getattr(edge, 'properties', {})
                        })
        
        return relationships
    
    def _format_path_results(self, raw_results: List[Any]) -> List[Dict[str, Any]]:
        """
        Format raw Gremlin path results.
        
        Args:
            raw_results: Raw path results from Gremlin
            
        Returns:
            Formatted path data
        """
        paths = []
        
        for result in raw_results:
            if hasattr(result, 'objects') and result.objects:
                path_data = {
                    "length": len(result.objects),
                    "vertices": [],
                    "edges": []
                }
                
                for i, obj in enumerate(result.objects):
                    if i % 2 == 0:  # Vertex
                        path_data["vertices"].append({
                            "id": getattr(obj, 'id', str(obj)),
                            "label": getattr(obj, 'label', 'unknown'),
                            "properties": getattr(obj, 'properties', {})
                        })
                    else:  # Edge
                        path_data["edges"].append({
                            "id": getattr(obj, 'id', str(obj)),
                            "label": getattr(obj, 'label', 'unknown'),
                            "properties": getattr(obj, 'properties', {})
                        })
                
                paths.append(path_data)
        
        return paths
    
    def _format_neighbor_results(self, raw_results: List[Any]) -> List[Dict[str, Any]]:
        """
        Format raw Gremlin neighbor results.
        
        Args:
            raw_results: Raw neighbor results from Gremlin
            
        Returns:
            Formatted neighbor data
        """
        neighbors = []
        
        for result in raw_results:
            neighbors.append({
                "id": getattr(result, 'id', str(result)),
                "label": getattr(result, 'label', 'unknown'),
                "properties": getattr(result, 'properties', {})
            })
        
        return neighbors
    
    async def find_relationships_with_documents(
        self,
        account_ids: List[str],
        rbac_context: RBACContext,
        relationship_types: Optional[List[str]] = None,
        max_depth: int = 2,
        include_document_content: bool = True
    ) -> Dict[str, Any]:
        """
        Find relationships and retrieve related document content from lakehouse.

        Args:
            account_ids: List of account IDs to find relationships for
            rbac_context: User's RBAC context for filtering
            relationship_types: Optional list of relationship types to include
            max_depth: Maximum traversal depth
            include_document_content: Whether to fetch document content from lakehouse

        Returns:
            Dictionary with relationships and document content
        """
        try:
            start_time = datetime.utcnow()

            logger.info(
                "Finding relationships with documents",
                account_ids=account_ids,
                user_id=rbac_context.user_id,
                include_content=include_document_content
            )

            # Step 1: Find relationships using existing method
            all_relationships = []
            document_ids = set()

            for account_id in account_ids:
                relationships_result = await self.find_relationships(
                    [account_id], rbac_context, relationship_types, max_depth
                )

                if relationships_result:
                    all_relationships.extend(relationships_result)

                    # Extract document IDs from relationships
                    for rel in relationships_result:
                        # Look for document references in relationship properties
                        if rel.get("target_label") == "document":
                            document_ids.add(rel.get("target_id"))
                        if rel.get("source_label") == "document":
                            document_ids.add(rel.get("source_id"))

                        # Also check relationship properties for document IDs
                        properties = rel.get("properties", {})
                        if "document_id" in properties:
                            document_ids.add(properties["document_id"])
                        if "file_id" in properties:
                            document_ids.add(properties["file_id"])

            # Step 2: Retrieve document content from lakehouse if requested and fabric client available
            documents_content = {}
            if include_document_content and self.fabric_client and document_ids:
                try:
                    # Filter to only accessible account documents for RBAC
                    accessible_accounts = rbac_context.access_scope.allowed_accounts

                    documents = await self.fabric_client.get_documents_by_ids(
                        list(document_ids),
                        account_id=accessible_accounts[0] if accessible_accounts else None
                    )

                    for doc in documents:
                        documents_content[doc["file_id"]] = {
                            "file_name": doc["file_name"],
                            "file_text": doc["file_text"][:2000],  # Limit text for response size
                            "file_summary": doc["file_summary"],
                            "sharepoint_url": doc["sharepoint_url"],
                            "account_id": doc["account_id"],
                            "last_modified": doc["last_modified"],
                            "content_type": doc["content_type"]
                        }

                except Exception as e:
                    logger.warning(f"Failed to retrieve document content: {e}")
                    # Continue without document content

            # Step 3: Build enriched response
            execution_time = (datetime.utcnow() - start_time).total_seconds() * 1000

            result = {
                "success": True,
                "account_ids": account_ids,
                "relationships": all_relationships,
                "documents_found": len(document_ids),
                "documents_content": documents_content,
                "metadata": {
                    "relationship_count": len(all_relationships),
                    "document_count": len(documents_content),
                    "execution_time_ms": execution_time,
                    "includes_content": include_document_content and bool(self.fabric_client)
                }
            }

            logger.info(
                "Relationships with documents completed",
                account_ids=account_ids,
                user_id=rbac_context.user_id,
                relationship_count=len(all_relationships),
                document_count=len(documents_content),
                execution_time_ms=execution_time
            )

            return result

        except Exception as e:
            logger.error(
                "Failed to find relationships with documents",
                account_ids=account_ids,
                user_id=rbac_context.user_id,
                error=str(e)
            )
            return {
                "success": False,
                "error": str(e),
                "account_ids": account_ids,
                "relationships": [],
                "documents_content": {},
                "metadata": {"execution_time_ms": 0}
            }
    
    async def find_relationships(
        self,
        account_ids: List[str],
        rbac_context: RBACContext,
        relationship_types: Optional[List[str]] = None,
        max_depth: int = 2
    ) -> List[Dict[str, Any]]:
        """
        Find relationships for multiple accounts.
        
        Args:
            account_ids: List of account IDs to find relationships for
            rbac_context: User's RBAC context for filtering
            relationship_types: Optional list of relationship types to include
            max_depth: Maximum traversal depth
            
        Returns:
            List of relationship dictionaries
        """
        try:
            all_relationships = []
            
            for account_id in account_ids:
                # Use existing account relationships method
                result = await self.find_account_relationships(
                    account_id, rbac_context, relationship_types, max_depth
                )
                
                if result.success and result.data:
                    all_relationships.extend(result.data)
            
            return all_relationships
            
        except Exception as e:
            logger.error(f"Failed to find relationships for accounts {account_ids}: {e}")
            return []
    
    async def find_neighbors(
        self,
        entity_id: str,
        rbac_context: RBACContext,
        relationship_types: Optional[List[str]] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Find immediate neighbors of an entity.
        
        Args:
            entity_id: Entity ID to find neighbors for
            rbac_context: User's RBAC context
            relationship_types: Optional relationship types to filter
            limit: Maximum number of neighbors to return
            
        Returns:
            List of neighbor dictionaries
        """
        try:
            result = await self.get_account_neighbors(
                entity_id, rbac_context, relationship_types
            )
            
            if result.success and result.data:
                return result.data[:limit]
            
            return []
            
        except Exception as e:
            logger.error(f"Failed to find neighbors for {entity_id}: {e}")
            return []
    
    async def find_shortest_path(
        self,
        from_entity: str,
        to_entity: str,
        rbac_context: RBACContext,
        max_hops: int = 6
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Find shortest path between two entities.
        
        Args:
            from_entity: Source entity ID
            to_entity: Target entity ID
            rbac_context: User's RBAC context
            max_hops: Maximum hops to search
            
        Returns:
            Path as list of nodes and edges, or None if no path found
        """
        try:
            result = await self.find_shortest_path(
                from_entity, to_entity, rbac_context, relationship_types=None
            )
            
            if result.success and result.data:
                return result.data[0] if result.data else None
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to find path from {from_entity} to {to_entity}: {e}")
            return None
