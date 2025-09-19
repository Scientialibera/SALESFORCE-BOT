"""
Graph agent for relationship-based queries using Cosmos DB.

This agent specializes in querying the Cosmos DB graph database to find relationships,
patterns, and connections between entities in the Salesforce and SharePoint data.
The graph data is populated from the data lakehouse by the data engineering team.
It always resolves account names first before executing graph queries.
"""

import json
from typing import Any, Dict, List, Optional
import structlog

from semantic_kernel import Kernel
from semantic_kernel.functions import KernelPlugin
from semantic_kernel.functions import KernelFunction, kernel_function

from chatbot.services.graph_service import GraphService
from chatbot.services.account_resolver_service import AccountResolverService
from chatbot.services.rbac_service import RBACService
from chatbot.services.telemetry_service import TelemetryService
from chatbot.models.rbac import RBACContext

logger = structlog.get_logger(__name__)


class GraphAgent:
    """Semantic Kernel agent for graph-based queries with account resolution."""
    
    def __init__(
        self,
        kernel: Kernel,
        graph_service: GraphService,
        account_resolver_service: AccountResolverService,
        rbac_service: RBACService,
        telemetry_service: TelemetryService
    ):
        """
        Initialize the graph agent.
        
        Args:
            kernel: Semantic Kernel instance
            graph_service: Service for graph operations
            account_resolver_service: Service for entity resolution
            rbac_service: Service for RBAC validation
            telemetry_service: Service for telemetry tracking
        """
        self.kernel = kernel
        self.graph_service = graph_service
        self.account_resolver_service = account_resolver_service
        self.rbac_service = rbac_service
        self.telemetry_service = telemetry_service
        
        # Register plugin with kernel
        self._register_plugin()
    
    def _register_plugin(self):
        """Register the graph agent as a Semantic Kernel plugin."""
        # TODO: Update to use current Semantic Kernel plugin API
        # The KernelPlugin API has changed - need to update this implementation
        logger.info("Graph agent plugin registration skipped - using basic functionality")
    
    @kernel_function(
        description="Find relationships for accounts mentioned in user query",
        name="find_account_relationships"
    )
    async def find_account_relationships(
        self,
        user_query: str,
        relationship_types: str = "",
        max_depth: str = "2",
        rbac_context: RBACContext = None
    ) -> str:
        """
        Find relationships for accounts mentioned in user query.
        First resolves account names, then finds their relationships.
        
        Args:
            user_query: User's natural language query containing account names
            relationship_types: Optional comma-separated list of relationship types to filter
            max_depth: Maximum depth to search (default: 2)
            rbac_context: User's RBAC context
            
        Returns:
            JSON string containing relationship information
        """
        try:
            tracking_id = await self.telemetry_service.start_performance_tracking(
                "graph_agent_find_account_relationships",
                rbac_context
            )
            
            logger.info(
                "Finding account relationships from query",
                user_query=user_query,
                relationship_types=relationship_types,
                max_depth=max_depth,
                user_id=rbac_context.user_id if rbac_context else None
            )
            
            # Step 1: Resolve accounts from the user query
            resolved_accounts = await self.account_resolver_service.resolve_entities(
                user_query, rbac_context, confidence_threshold=0.7
            )
            
            if not resolved_accounts:
                return json.dumps({
                    "success": False,
                    "error": "No accounts could be resolved from the query",
                    "user_query": user_query,
                    "suggestion": "Please mention specific account names in your query"
                })
            
            # Parse parameters
            rel_types = [rt.strip() for rt in relationship_types.split(",")] if relationship_types else []
            depth = int(max_depth)
            
            # Step 2: Find relationships for resolved accounts
            account_ids = [account["id"] for account in resolved_accounts]
            relationships = await self.graph_service.find_relationships(
                account_ids,
                rbac_context,
                relationship_types=rel_types,
                max_depth=depth
            )
            
            # Step 3: Format response with account names
            result = {
                "success": True,
                "user_query": user_query,
                "resolved_accounts": [
                    {
                        "name": acc["name"],
                        "id": acc["id"],
                        "confidence": acc["confidence"]
                    } for acc in resolved_accounts
                ],
                "relationships": relationships,
                "total_relationships": len(relationships),
                "relationship_types_found": list(set(r.get("type", "") for r in relationships)),
                "analysis": {
                    "accounts_analyzed": len(resolved_accounts),
                    "total_connections": len(relationships),
                    "most_connected_account": self._find_most_connected_account(resolved_accounts, relationships)
                }
            }
            
            await self.telemetry_service.end_performance_tracking(
                tracking_id,
                success=True,
                metrics={
                    "accounts_resolved": len(resolved_accounts),
                    "relationships_found": len(relationships)
                }
            )
            
            return json.dumps(result, indent=2)
            
        except Exception as e:
            await self.telemetry_service.end_performance_tracking(
                tracking_id,
                success=False,
                error_details={"error": str(e)}
            )
            
            logger.error(
                "Failed to find account relationships",
                user_query=user_query,
                error=str(e)
            )
            
            return json.dumps({
                "success": False,
                "error": str(e),
                "user_query": user_query
            })
    
    @kernel_function(
        description="Find entities connected to accounts mentioned in user query",
        name="find_account_connections"
    )
    async def find_account_connections(
        self,
        user_query: str,
        connection_types: str = "",
        max_results: str = "20",
        rbac_context: RBACContext = None
    ) -> str:
        """
        Find entities connected to accounts mentioned in user query.
        
        Args:
            user_query: User's natural language query containing account names
            connection_types: Optional comma-separated list of connection types
            max_results: Maximum number of results to return (default: 20)
            rbac_context: User's RBAC context
            
        Returns:
            JSON string containing connected entities
        """
        try:
            tracking_id = await self.telemetry_service.start_performance_tracking(
                "graph_agent_find_account_connections",
                rbac_context
            )
            
            logger.info(
                "Finding account connections from query",
                user_query=user_query,
                connection_types=connection_types,
                max_results=max_results
            )
            
            # Step 1: Resolve accounts from the user query
            resolved_accounts = await self.account_resolver_service.resolve_entities(
                user_query, rbac_context, confidence_threshold=0.7
            )
            
            if not resolved_accounts:
                return json.dumps({
                    "success": False,
                    "error": "No accounts could be resolved from the query",
                    "user_query": user_query,
                    "suggestion": "Please mention specific account names in your query"
                })
            
            # Parse parameters
            conn_types = [ct.strip() for ct in connection_types.split(",")] if connection_types else []
            max_res = int(max_results)
            
            # Step 2: Find connections for each resolved account
            all_connections = {}
            for account in resolved_accounts:
                connections = await self.graph_service.find_neighbors(
                    account["id"],
                    rbac_context,
                    relationship_types=conn_types,
                    limit=max_res
                )
                all_connections[account["name"]] = {
                    "account_info": account,
                    "connections": connections,
                    "connection_count": len(connections)
                }
            
            # Step 3: Aggregate and analyze connections
            all_unique_connections = []
            connection_type_counts = {}
            
            for account_name, data in all_connections.items():
                for connection in data["connections"]:
                    # Track connection types
                    conn_type = connection.get("relationship_type", "unknown")
                    connection_type_counts[conn_type] = connection_type_counts.get(conn_type, 0) + 1
                    
                    # Add source account info
                    connection["source_account"] = account_name
                    all_unique_connections.append(connection)
            
            # Remove duplicates and sort by relevance
            unique_connections = []
            seen_ids = set()
            for conn in all_unique_connections:
                if conn["id"] not in seen_ids:
                    seen_ids.add(conn["id"])
                    unique_connections.append(conn)
            
            # Sort by connection strength or type priority
            unique_connections.sort(key=lambda x: (
                x.get("weight", 0), 
                x.get("relationship_type", "").lower()
            ), reverse=True)
            
            # Limit results
            unique_connections = unique_connections[:max_res]
            
            result = {
                "success": True,
                "user_query": user_query,
                "resolved_accounts": [
                    {
                        "name": acc["name"],
                        "id": acc["id"],
                        "confidence": acc["confidence"]
                    } for acc in resolved_accounts
                ],
                "account_connections": all_connections,
                "unique_connections": unique_connections,
                "analysis": {
                    "total_accounts": len(resolved_accounts),
                    "total_unique_connections": len(unique_connections),
                    "connection_type_distribution": connection_type_counts,
                    "most_connected_account": max(
                        all_connections.items(), 
                        key=lambda x: x[1]["connection_count"]
                    )[0] if all_connections else None
                }
            }
            
            await self.telemetry_service.end_performance_tracking(
                tracking_id,
                success=True,
                metrics={
                    "accounts_resolved": len(resolved_accounts),
                    "connections_found": len(unique_connections)
                }
            )
            
            return json.dumps(result, indent=2)
            
        except Exception as e:
            await self.telemetry_service.end_performance_tracking(
                tracking_id,
                success=False,
                error_details={"error": str(e)}
            )
            
            logger.error(
                "Failed to find account connections",
                user_query=user_query,
                error=str(e)
            )
            
            return json.dumps({
                "success": False,
                "error": str(e),
                "user_query": user_query
            })
    
    @kernel_function(
        description="Find the shortest path between accounts mentioned in user query",
        name="find_path_between_accounts"
    )
    async def find_path_between_accounts(
        self,
        user_query: str,
        max_hops: str = "6",
        rbac_context: RBACContext = None
    ) -> str:
        """
        Find the shortest path between accounts mentioned in user query.
        
        Args:
            user_query: User's natural language query containing account names
            max_hops: Maximum number of hops to search (default: 6)
            rbac_context: User's RBAC context
            
        Returns:
            JSON string containing path information
        """
        try:
            tracking_id = await self.telemetry_service.start_performance_tracking(
                "graph_agent_find_path_between_accounts",
                rbac_context
            )
            
            logger.info(
                "Finding path between accounts from query",
                user_query=user_query,
                max_hops=max_hops
            )
            
            # Step 1: Resolve accounts from the user query
            resolved_accounts = await self.account_resolver_service.resolve_entities(
                user_query, rbac_context, confidence_threshold=0.7
            )
            
            if len(resolved_accounts) < 2:
                return json.dumps({
                    "success": False,
                    "error": "Need at least 2 accounts to find a path between them",
                    "user_query": user_query,
                    "resolved_accounts": len(resolved_accounts),
                    "suggestion": "Please mention at least two account names in your query"
                })
            
            max_h = int(max_hops)
            
            # Step 2: Find paths between all pairs of accounts
            paths_found = []
            for i, source_account in enumerate(resolved_accounts):
                for j, target_account in enumerate(resolved_accounts):
                    if i < j:  # Avoid duplicate pairs
                        path = await self.graph_service.find_shortest_path(
                            source_account["id"],
                            target_account["id"],
                            rbac_context,
                            max_hops=max_h
                        )
                        
                        paths_found.append({
                            "source_account": {
                                "name": source_account["name"],
                                "id": source_account["id"]
                            },
                            "target_account": {
                                "name": target_account["name"],
                                "id": target_account["id"]
                            },
                            "path": path,
                            "path_length": len(path) - 1 if path else None,
                            "path_exists": bool(path)
                        })
            
            # Step 3: Analyze paths
            connected_pairs = [p for p in paths_found if p["path_exists"]]
            shortest_path = min(connected_pairs, key=lambda x: x["path_length"]) if connected_pairs else None
            
            result = {
                "success": True,
                "user_query": user_query,
                "resolved_accounts": [
                    {
                        "name": acc["name"],
                        "id": acc["id"],
                        "confidence": acc["confidence"]
                    } for acc in resolved_accounts
                ],
                "all_paths": paths_found,
                "analysis": {
                    "total_account_pairs": len(paths_found),
                    "connected_pairs": len(connected_pairs),
                    "disconnected_pairs": len(paths_found) - len(connected_pairs),
                    "shortest_path": shortest_path,
                    "average_path_length": sum(
                        p["path_length"] for p in connected_pairs
                    ) / len(connected_pairs) if connected_pairs else 0
                }
            }
            
            await self.telemetry_service.end_performance_tracking(
                tracking_id,
                success=True,
                metrics={
                    "accounts_resolved": len(resolved_accounts),
                    "paths_analyzed": len(paths_found),
                    "connected_pairs": len(connected_pairs)
                }
            )
            
            return json.dumps(result, indent=2)
            
        except Exception as e:
            await self.telemetry_service.end_performance_tracking(
                tracking_id,
                success=False,
                error_details={"error": str(e)}
            )
            
            logger.error(
                "Failed to find path between accounts",
                user_query=user_query,
                error=str(e)
            )
            
            return json.dumps({
                "success": False,
                "error": str(e),
                "user_query": user_query
            })
    
    @kernel_function(
        description="Analyze the network around accounts mentioned in user query",
        name="analyze_account_network"
    )
    async def analyze_account_network(
        self,
        user_query: str,
        analysis_depth: str = "2",
        rbac_context: RBACContext = None
    ) -> str:
        """
        Analyze the network around accounts mentioned in user query.
        
        Args:
            user_query: User's natural language query containing account names
            analysis_depth: Depth of analysis (default: 2)
            rbac_context: User's RBAC context
            
        Returns:
            JSON string containing network analysis
        """
        try:
            tracking_id = await self.telemetry_service.start_performance_tracking(
                "graph_agent_analyze_account_network",
                rbac_context
            )
            
            logger.info(
                "Analyzing account network from query",
                user_query=user_query,
                analysis_depth=analysis_depth
            )
            
            # Step 1: Resolve accounts from the user query
            resolved_accounts = await self.account_resolver_service.resolve_entities(
                user_query, rbac_context, confidence_threshold=0.7
            )
            
            if not resolved_accounts:
                return json.dumps({
                    "success": False,
                    "error": "No accounts could be resolved from the query",
                    "user_query": user_query,
                    "suggestion": "Please mention specific account names in your query"
                })
            
            depth = int(analysis_depth)
            
            # Step 2: Analyze network for each account
            account_analyses = {}
            all_connections = set()
            
            for account in resolved_accounts:
                # Get neighbors for this account
                neighbors = await self.graph_service.find_neighbors(
                    account["id"], rbac_context, limit=100
                )
                
                # Analyze connection types
                connection_types = {}
                for neighbor in neighbors:
                    rel_type = neighbor.get("relationship_type", "unknown")
                    connection_types[rel_type] = connection_types.get(rel_type, 0) + 1
                    all_connections.add(neighbor["id"])
                
                # Calculate metrics
                network_strength = min(len(neighbors) / 10, 1.0)  # Normalize to 0-1
                
                account_analyses[account["name"]] = {
                    "account_info": account,
                    "total_connections": len(neighbors),
                    "connection_types": connection_types,
                    "network_strength": network_strength,
                    "top_connections": neighbors[:5]  # Top 5 connections
                }
            
            # Step 3: Overall network analysis
            total_unique_connections = len(all_connections)
            most_connected_account = max(
                account_analyses.items(),
                key=lambda x: x[1]["total_connections"]
            ) if account_analyses else None
            
            # Calculate network density
            max_possible_connections = len(resolved_accounts) * (len(resolved_accounts) - 1) / 2
            network_density = total_unique_connections / max_possible_connections if max_possible_connections > 0 else 0
            
            result = {
                "success": True,
                "user_query": user_query,
                "resolved_accounts": [
                    {
                        "name": acc["name"],
                        "id": acc["id"],
                        "confidence": acc["confidence"]
                    } for acc in resolved_accounts
                ],
                "account_analyses": account_analyses,
                "network_overview": {
                    "total_accounts_analyzed": len(resolved_accounts),
                    "total_unique_connections": total_unique_connections,
                    "network_density": network_density,
                    "most_connected_account": most_connected_account[0] if most_connected_account else None,
                    "average_connections_per_account": sum(
                        analysis["total_connections"] for analysis in account_analyses.values()
                    ) / len(account_analyses) if account_analyses else 0
                }
            }
            
            await self.telemetry_service.end_performance_tracking(
                tracking_id,
                success=True,
                metrics={
                    "accounts_analyzed": len(resolved_accounts),
                    "total_connections": total_unique_connections,
                    "network_density": network_density
                }
            )
            
            return json.dumps(result, indent=2)
            
        except Exception as e:
            await self.telemetry_service.end_performance_tracking(
                tracking_id,
                success=False,
                error_details={"error": str(e)}
            )
            
            logger.error(
                "Failed to analyze account network",
                user_query=user_query,
                error=str(e)
            )
            
            return json.dumps({
                "success": False,
                "error": str(e),
                "user_query": user_query
            })
    
    @kernel_function(
        description="Find relationships and retrieve related document content for accounts mentioned in user query",
        name="find_relationships_with_documents"
    )
    async def find_relationships_with_documents(
        self,
        user_query: str,
        relationship_types: str = "",
        max_depth: str = "2",
        include_content: str = "true",
        rbac_context: RBACContext = None
    ) -> str:
        """
        Find relationships and retrieve document content for accounts mentioned in user query.
        First resolves account names, then finds their relationships and retrieves document text from lakehouse.
        
        Args:
            user_query: User's natural language query containing account names
            relationship_types: Optional comma-separated list of relationship types
            max_depth: Maximum depth to search (default: 2)
            include_content: Whether to include document content (default: true)
            rbac_context: User's RBAC context
            
        Returns:
            JSON string containing relationship and document data
        """
        try:
            tracking_id = await self.telemetry_service.start_performance_tracking(
                "graph_agent_find_relationships_with_documents",
                rbac_context
            )
            
            logger.info(
                "Finding relationships with documents from query",
                user_query=user_query,
                relationship_types=relationship_types,
                max_depth=max_depth,
                include_content=include_content,
                user_id=rbac_context.user_id if rbac_context else None
            )
            
            # Step 1: Resolve accounts from the user query
            resolved_accounts = await self.account_resolver_service.resolve_entities(
                user_query, rbac_context, confidence_threshold=0.7
            )
            
            if not resolved_accounts:
                return json.dumps({
                    "success": False,
                    "error": "No accounts could be resolved from the query",
                    "user_query": user_query,
                    "suggestion": "Please mention specific account names in your query"
                })
            
            # Parse parameters
            rel_types = [rt.strip() for rt in relationship_types.split(",")] if relationship_types else None
            depth = int(max_depth)
            include_doc_content = include_content.lower() == "true"
            
            # Step 2: Find relationships and documents using enhanced graph service
            account_ids = [account["id"] for account in resolved_accounts]
            result = await self.graph_service.find_relationships_with_documents(
                account_ids=account_ids,
                rbac_context=rbac_context,
                relationship_types=rel_types,
                max_depth=depth,
                include_document_content=include_doc_content
            )
            
            # Step 3: Enhance result with account information
            enhanced_result = {
                "success": result["success"],
                "user_query": user_query,
                "resolved_accounts": [
                    {
                        "name": acc["name"],
                        "id": acc["id"],
                        "confidence": acc["confidence"]
                    } for acc in resolved_accounts
                ],
                "relationships": result["relationships"],
                "documents_found": result["documents_found"],
                "documents_content": result["documents_content"],
                "analysis": {
                    "total_relationships": len(result["relationships"]),
                    "total_documents": len(result["documents_content"]),
                    "accounts_analyzed": len(resolved_accounts),
                    "relationship_types_found": list(set(
                        rel.get("edge_label", "") for rel in result["relationships"]
                    )),
                    "document_accounts": list(set(
                        doc.get("account_id", "") for doc in result["documents_content"].values()
                    ))
                },
                "metadata": result["metadata"]
            }
            
            # Step 4: Add document summaries for better context
            if result["documents_content"]:
                document_summaries = []
                for doc_id, doc_content in result["documents_content"].items():
                    document_summaries.append({
                        "document_id": doc_id,
                        "file_name": doc_content["file_name"],
                        "summary": doc_content["file_summary"],
                        "account_id": doc_content["account_id"],
                        "url": doc_content["sharepoint_url"],
                        "content_preview": doc_content["file_text"][:300] + "..." if len(doc_content["file_text"]) > 300 else doc_content["file_text"]
                    })
                enhanced_result["document_summaries"] = document_summaries
            
            await self.telemetry_service.end_performance_tracking(
                tracking_id,
                success=True,
                metrics={
                    "accounts_resolved": len(resolved_accounts),
                    "relationships_found": len(result["relationships"]),
                    "documents_found": len(result["documents_content"])
                }
            )
            
            logger.info(
                "Relationships with documents found",
                user_query=user_query,
                user_id=rbac_context.user_id if rbac_context else None,
                relationships_count=len(result["relationships"]),
                documents_count=len(result["documents_content"])
            )
            
            return json.dumps(enhanced_result, indent=2)
            
        except Exception as e:
            await self.telemetry_service.end_performance_tracking(
                tracking_id,
                success=False,
                error_details={"error": str(e)}
            )
            
            logger.error(
                "Failed to find relationships with documents",
                user_query=user_query,
                error=str(e)
            )
            
            return json.dumps({
                "success": False,
                "error": str(e),
                "user_query": user_query
            })
    
    def _find_most_connected_account(
        self, 
        accounts: List[Dict[str, Any]], 
        relationships: List[Dict[str, Any]]
    ) -> Optional[str]:
        """
        Find the account with the most relationships.
        
        Args:
            accounts: List of resolved accounts
            relationships: List of relationships
            
        Returns:
            Name of the most connected account
        """
        if not accounts or not relationships:
            return None
        
        account_counts = {}
        for account in accounts:
            account_counts[account["name"]] = 0
        
        for relationship in relationships:
            source_id = relationship.get("source_id")
            target_id = relationship.get("target_id")
            
            for account in accounts:
                if account["id"] in [source_id, target_id]:
                    account_counts[account["name"]] += 1
        
        if not account_counts:
            return None
        
        return max(account_counts.items(), key=lambda x: x[1])[0]
