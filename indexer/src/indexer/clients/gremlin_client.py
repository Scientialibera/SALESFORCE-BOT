"""Cosmos DB Gremlin client for graph operations."""

import asyncio
import logging
from typing import Dict, List, Optional, Any, Union
from gremlin_python.driver import client, serializer
from gremlin_python.driver.protocol import GremlinServerError
from gremlin_python.process.anonymous_traversal import traversal
from gremlin_python.process.graph_traversal import __
from gremlin_python.process.traversal import T, P, Order
from gremlin_python.structure.graph import Graph
from azure.identity import DefaultAzureCredential
import ssl
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from ..config.settings import Settings


logger = logging.getLogger(__name__)


class GremlinClient:
    """Client for Azure Cosmos DB Gremlin API."""
    
    def __init__(self, settings: Settings):
        """Initialize the Gremlin client."""
        self.settings = settings
        self.credential = DefaultAzureCredential()
        self.client: Optional[client.Client] = None
        self._initialized = False
    
    async def initialize(self):
        """Initialize the Gremlin client."""
        if self._initialized:
            return
        
        try:
            # Get access token for Cosmos DB
            token_response = self.credential.get_token("https://cosmos.azure.com/.default")
            
            # Parse Gremlin endpoint
            endpoint_parts = self.settings.gremlin.endpoint.replace("wss://", "").replace("https://", "").split(":")
            hostname = endpoint_parts[0]
            port = int(endpoint_parts[1].split("/")[0]) if len(endpoint_parts) > 1 else 443
            
            # Configure client
            self.client = client.Client(
                url=f"wss://{hostname}:{port}/gremlin",
                traversal_source="g",
                username=f"/dbs/{self.settings.gremlin.database}/colls/{self.settings.gremlin.collection}",
                password=token_response.token,
                message_serializer=serializer.GraphSONSerializersV2d0()
            )
            
            self._initialized = True
            logger.info("Gremlin client initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Gremlin client: {e}")
            raise
    
    def close(self):
        """Close the client and clean up resources."""
        if self.client:
            self.client.close()
        self._initialized = False
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((GremlinServerError,))
    )
    def execute_query(self, query: str, bindings: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """Execute a Gremlin query."""
        if not self._initialized:
            asyncio.create_task(self.initialize())
        
        try:
            logger.debug(f"Executing Gremlin query: {query}")
            
            result_set = self.client.submit(query, bindings or {})
            results = result_set.all().result()
            
            logger.debug(f"Query returned {len(results)} results")
            return results
            
        except GremlinServerError as e:
            logger.error(f"Gremlin server error: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to execute Gremlin query: {e}")
            raise
    
    def add_vertex(self, label: str, properties: Dict[str, Any], vertex_id: str = None) -> Dict[str, Any]:
        """Add a vertex to the graph."""
        # Build the query
        query_parts = [f"g.addV('{label}')"]
        bindings = {}
        
        if vertex_id:
            query_parts.append("property(id, vertex_id)")
            bindings["vertex_id"] = vertex_id
        
        # Add properties
        for key, value in properties.items():
            if value is not None:
                param_name = f"prop_{key}"
                query_parts.append(f"property('{key}', {param_name})")
                bindings[param_name] = value
        
        query = ".".join(query_parts)
        
        try:
            results = self.execute_query(query, bindings)
            logger.debug(f"Added vertex with label {label}")
            return results[0] if results else {}
            
        except Exception as e:
            logger.error(f"Failed to add vertex: {e}")
            raise
    
    def add_edge(self, from_vertex_id: str, to_vertex_id: str, label: str, 
                 properties: Dict[str, Any] = None) -> Dict[str, Any]:
        """Add an edge between two vertices."""
        query = (
            f"g.V(from_id).addE('{label}').to(g.V(to_id))"
        )
        
        bindings = {
            "from_id": from_vertex_id,
            "to_id": to_vertex_id
        }
        
        # Add edge properties
        if properties:
            property_parts = []
            for key, value in properties.items():
                if value is not None:
                    param_name = f"prop_{key}"
                    property_parts.append(f"property('{key}', {param_name})")
                    bindings[param_name] = value
            
            if property_parts:
                query += "." + ".".join(property_parts)
        
        try:
            results = self.execute_query(query, bindings)
            logger.debug(f"Added edge {label} from {from_vertex_id} to {to_vertex_id}")
            return results[0] if results else {}
            
        except Exception as e:
            logger.error(f"Failed to add edge: {e}")
            raise
    
    def get_vertex(self, vertex_id: str) -> Optional[Dict[str, Any]]:
        """Get a vertex by ID."""
        query = "g.V(vertex_id).valueMap(true)"
        bindings = {"vertex_id": vertex_id}
        
        try:
            results = self.execute_query(query, bindings)
            return results[0] if results else None
            
        except Exception as e:
            logger.error(f"Failed to get vertex {vertex_id}: {e}")
            return None
    
    def get_vertices_by_label(self, label: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get vertices by label."""
        query = f"g.V().hasLabel('{label}').limit(limit_count).valueMap(true)"
        bindings = {"limit_count": limit}
        
        try:
            results = self.execute_query(query, bindings)
            return results
            
        except Exception as e:
            logger.error(f"Failed to get vertices with label {label}: {e}")
            return []
    
    def get_vertex_edges(self, vertex_id: str, direction: str = "both") -> List[Dict[str, Any]]:
        """Get edges connected to a vertex."""
        direction_map = {
            "in": "inE()",
            "out": "outE()",
            "both": "bothE()"
        }
        
        direction_query = direction_map.get(direction, "bothE()")
        query = f"g.V(vertex_id).{direction_query}.valueMap(true)"
        bindings = {"vertex_id": vertex_id}
        
        try:
            results = self.execute_query(query, bindings)
            return results
            
        except Exception as e:
            logger.error(f"Failed to get edges for vertex {vertex_id}: {e}")
            return []
    
    def find_related_vertices(self, vertex_id: str, edge_label: str = None, 
                             max_depth: int = 2) -> List[Dict[str, Any]]:
        """Find vertices related to a given vertex."""
        if edge_label:
            query = f"g.V(vertex_id).repeat(out('{edge_label}')).times(max_depth).dedup().valueMap(true)"
        else:
            query = f"g.V(vertex_id).repeat(out()).times(max_depth).dedup().valueMap(true)"
        
        bindings = {
            "vertex_id": vertex_id,
            "max_depth": max_depth
        }
        
        try:
            results = self.execute_query(query, bindings)
            return results
            
        except Exception as e:
            logger.error(f"Failed to find related vertices for {vertex_id}: {e}")
            return []
    
    def search_vertices_by_property(self, property_name: str, property_value: Any, 
                                   label: str = None) -> List[Dict[str, Any]]:
        """Search vertices by property value."""
        if label:
            query = f"g.V().hasLabel('{label}').has(property_name, property_value).valueMap(true)"
        else:
            query = "g.V().has(property_name, property_value).valueMap(true)"
        
        bindings = {
            "property_name": property_name,
            "property_value": property_value
        }
        
        try:
            results = self.execute_query(query, bindings)
            return results
            
        except Exception as e:
            logger.error(f"Failed to search vertices by {property_name}={property_value}: {e}")
            return []
    
    def delete_vertex(self, vertex_id: str) -> bool:
        """Delete a vertex and all its edges."""
        query = "g.V(vertex_id).drop()"
        bindings = {"vertex_id": vertex_id}
        
        try:
            self.execute_query(query, bindings)
            logger.debug(f"Deleted vertex {vertex_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete vertex {vertex_id}: {e}")
            return False
    
    def delete_edge(self, edge_id: str) -> bool:
        """Delete an edge by ID."""
        query = "g.E(edge_id).drop()"
        bindings = {"edge_id": edge_id}
        
        try:
            self.execute_query(query, bindings)
            logger.debug(f"Deleted edge {edge_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete edge {edge_id}: {e}")
            return False
    
    def update_vertex_property(self, vertex_id: str, property_name: str, 
                              property_value: Any) -> bool:
        """Update a vertex property."""
        query = "g.V(vertex_id).property(property_name, property_value)"
        bindings = {
            "vertex_id": vertex_id,
            "property_name": property_name,
            "property_value": property_value
        }
        
        try:
            self.execute_query(query, bindings)
            logger.debug(f"Updated vertex {vertex_id} property {property_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update vertex property: {e}")
            return False
    
    def get_graph_statistics(self) -> Dict[str, Any]:
        """Get basic statistics about the graph."""
        try:
            vertex_count_query = "g.V().count()"
            edge_count_query = "g.E().count()"
            
            vertex_count = self.execute_query(vertex_count_query)[0]
            edge_count = self.execute_query(edge_count_query)[0]
            
            # Get label distribution
            label_query = "g.V().groupCount().by(label)"
            label_distribution = self.execute_query(label_query)[0]
            
            return {
                "vertex_count": vertex_count,
                "edge_count": edge_count,
                "label_distribution": label_distribution
            }
            
        except Exception as e:
            logger.error(f"Failed to get graph statistics: {e}")
            return {}
    
    def create_document_relationships(self, document_id: str, chunk_ids: List[str], 
                                    account_id: str = None, owner_email: str = None) -> bool:
        """Create relationships for a document and its chunks."""
        try:
            # Add document vertex if it doesn't exist
            doc_properties = {
                "type": "document",
                "document_id": document_id
            }
            
            if account_id:
                doc_properties["account_id"] = account_id
            if owner_email:
                doc_properties["owner_email"] = owner_email
            
            self.add_vertex("document", doc_properties, document_id)
            
            # Add chunk vertices and relationships
            for chunk_id in chunk_ids:
                chunk_properties = {
                    "type": "chunk",
                    "document_id": document_id
                }
                
                self.add_vertex("chunk", chunk_properties, chunk_id)
                
                # Add document -> chunk relationship
                self.add_edge(document_id, chunk_id, "contains", {
                    "relationship_type": "document_chunk"
                })
            
            # If account_id provided, create account relationship
            if account_id:
                account_properties = {
                    "type": "account",
                    "account_id": account_id
                }
                self.add_vertex("account", account_properties, account_id)
                self.add_edge(account_id, document_id, "owns", {
                    "relationship_type": "account_document"
                })
            
            logger.info(f"Created graph relationships for document {document_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create document relationships: {e}")
            return False
    
    def find_related_documents(self, document_id: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """Find documents related to a given document through shared entities or accounts."""
        query = """
        g.V(document_id)
          .out('contains').in('contains')
          .where(neq(document_id))
          .dedup()
          .limit(max_results)
          .valueMap(true)
        """
        
        bindings = {
            "document_id": document_id,
            "max_results": max_results
        }
        
        try:
            results = self.execute_query(query, bindings)
            return results
            
        except Exception as e:
            logger.error(f"Failed to find related documents for {document_id}: {e}")
            return []
    
    def test_connection(self) -> bool:
        """Test the connection to Gremlin."""
        try:
            if not self._initialized:
                asyncio.create_task(self.initialize())
            
            # Simple query to test connection
            results = self.execute_query("g.V().limit(1).count()")
            return len(results) >= 0
            
        except Exception as e:
            logger.error(f"Gremlin connection test failed: {e}")
            return False
