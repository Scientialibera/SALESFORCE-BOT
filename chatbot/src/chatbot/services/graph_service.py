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
from chatbot.models.rbac import RBACContext
from chatbot.models.result import QueryResult
from chatbot.services.cache_service import CacheService

logger = structlog.get_logger(__name__)


class GraphService:
    """Service for graph database operations with RBAC filtering."""
    
    def __init__(
        self,
        gremlin_client: GremlinClient,
        cache_service: CacheService,
        max_results: int = 100,
        max_traversal_depth: int = 5
    ):
        """
        Initialize the graph service.
        
        Args:
            gremlin_client: Gremlin client for graph operations
            cache_service: Cache service for query results
            max_results: Maximum number of results to return
            max_traversal_depth: Maximum depth for graph traversals
        """
        self.gremlin_client = gremlin_client
        self.cache_service = cache_service
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
            cached_result = await self.cache_service.get_query_result(
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
            
            await self.cache_service.set_query_result(
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
