"""Vector store service for managing embeddings and vector search."""

import asyncio
import logging
from typing import Dict, List, Optional, Any, Tuple
import json
import aiohttp
from azure.identity.aio import DefaultAzureCredential
from ..clients.aoai_client import AzureOpenAIClient
from ..models.chunk import Chunk
from ..config.settings import Settings


logger = logging.getLogger(__name__)


class VectorStoreService:
    """Service for managing vector embeddings and search operations."""
    
    def __init__(self, settings: Settings, aoai_client: AzureOpenAIClient):
        """Initialize the vector store service."""
        self.settings = settings
        self.aoai_client = aoai_client
        self.credential = DefaultAzureCredential()
        self.session: Optional[aiohttp.ClientSession] = None
        self._index_exists = False
    
    async def initialize(self):
        """Initialize the service."""
        try:
            self.session = aiohttp.ClientSession()
            
            # Ensure search index exists
            await self._ensure_search_index()
            
            logger.info("Vector store service initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize vector store service: {e}")
            raise
    
    async def close(self):
        """Close the service and clean up resources."""
        if self.session:
            await self.session.close()
        if self.credential:
            await self.credential.close()
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
    
    async def _get_search_headers(self) -> Dict[str, str]:
        """Get headers for Azure AI Search requests."""
        token_response = await self.credential.get_token("https://search.azure.com/.default")
        
        return {
            "Authorization": f"Bearer {token_response.token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
    
    async def _ensure_search_index(self):
        """Ensure the search index exists with proper schema."""
        if self._index_exists:
            return
        
        try:
            headers = await self._get_search_headers()
            
            # Check if index exists
            index_url = f"{self.settings.ai_search.endpoint}/indexes/{self.settings.ai_search.index_name}"
            
            async with self.session.get(index_url, headers=headers, params={"api-version": "2023-11-01"}) as response:
                if response.status == 200:
                    self._index_exists = True
                    logger.info(f"Search index {self.settings.ai_search.index_name} already exists")
                    return
                elif response.status != 404:
                    response.raise_for_status()
            
            # Create index if it doesn't exist
            await self._create_search_index()
            
        except Exception as e:
            logger.error(f"Failed to ensure search index: {e}")
            raise
    
    async def _create_search_index(self):
        """Create the search index with vector search configuration."""
        try:
            headers = await self._get_search_headers()
            
            # Define index schema
            index_schema = {
                "name": self.settings.ai_search.index_name,
                "fields": [
                    {"name": "id", "type": "Edm.String", "key": True, "searchable": False, "filterable": True},
                    {"name": "document_id", "type": "Edm.String", "searchable": False, "filterable": True},
                    {"name": "chunk_index", "type": "Edm.Int32", "searchable": False, "filterable": True, "sortable": True},
                    {"name": "text", "type": "Edm.String", "searchable": True, "analyzer": "standard.lucene"},
                    {"name": "title", "type": "Edm.String", "searchable": True, "filterable": True},
                    {"name": "embedding", "type": "Collection(Edm.Single)", "searchable": True, "vectorSearchDimensions": 1536, "vectorSearchProfileName": "default-vector-profile"},
                    {"name": "embedding_model", "type": "Edm.String", "searchable": False, "filterable": True},
                    {"name": "start_offset", "type": "Edm.Int32", "searchable": False, "filterable": True, "sortable": True},
                    {"name": "end_offset", "type": "Edm.Int32", "searchable": False, "filterable": True, "sortable": True},
                    {"name": "length", "type": "Edm.Int32", "searchable": False, "filterable": True, "sortable": True},
                    {"name": "tags", "type": "Collection(Edm.String)", "searchable": True, "filterable": True, "facetable": True},
                    {"name": "entities", "type": "Edm.String", "searchable": True},
                    {"name": "created_at", "type": "Edm.DateTimeOffset", "searchable": False, "filterable": True, "sortable": True},
                    {"name": "account_id", "type": "Edm.String", "searchable": False, "filterable": True, "facetable": True},
                    {"name": "owner_email", "type": "Edm.String", "searchable": False, "filterable": True, "facetable": True},
                    {"name": "department", "type": "Edm.String", "searchable": False, "filterable": True, "facetable": True},
                    {"name": "project_name", "type": "Edm.String", "searchable": False, "filterable": True, "facetable": True},
                    {"name": "content_type", "type": "Edm.String", "searchable": False, "filterable": True, "facetable": True},
                    {"name": "page_number", "type": "Edm.Int32", "searchable": False, "filterable": True, "sortable": True},
                    {"name": "section_title", "type": "Edm.String", "searchable": True, "filterable": True},
                    {"name": "confidence_score", "type": "Edm.Double", "searchable": False, "filterable": True, "sortable": True}
                ],
                "vectorSearch": {
                    "algorithms": [
                        {
                            "name": "default-algorithm",
                            "kind": "hnsw",
                            "hnswParameters": {
                                "metric": "cosine",
                                "m": 4,
                                "efConstruction": 400,
                                "efSearch": 500
                            }
                        }
                    ],
                    "profiles": [
                        {
                            "name": "default-vector-profile",
                            "algorithm": "default-algorithm"
                        }
                    ]
                }
            }
            
            # Create index
            create_url = f"{self.settings.ai_search.endpoint}/indexes"
            
            async with self.session.post(
                create_url, 
                headers=headers, 
                json=index_schema,
                params={"api-version": "2023-11-01"}
            ) as response:
                if response.status in [200, 201]:
                    self._index_exists = True
                    logger.info(f"Created search index {self.settings.ai_search.index_name}")
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to create search index: {response.status} - {error_text}")
                    response.raise_for_status()
            
        except Exception as e:
            logger.error(f"Failed to create search index: {e}")
            raise
    
    async def index_chunks(self, chunks: List[Chunk]) -> Tuple[int, int]:
        """Index chunks with embeddings into the vector store."""
        try:
            if not chunks:
                return 0, 0
            
            logger.info(f"Indexing {len(chunks)} chunks")
            
            # Generate embeddings for chunks that don't have them
            chunks_to_embed = [chunk for chunk in chunks if not chunk.embedding]
            
            if chunks_to_embed:
                await self._generate_embeddings_for_chunks(chunks_to_embed)
            
            # Convert chunks to search documents
            search_documents = []
            for chunk in chunks:
                if chunk.embedding:  # Only index chunks with embeddings
                    search_doc = chunk.to_search_document()
                    
                    # Serialize entities as JSON string
                    if chunk.entities:
                        search_doc["entities"] = json.dumps(chunk.entities)
                    else:
                        search_doc["entities"] = "[]"
                    
                    search_documents.append(search_doc)
            
            if not search_documents:
                logger.warning("No chunks with embeddings to index")
                return 0, len(chunks)
            
            # Index documents in batches
            batch_size = 100
            indexed_count = 0
            failed_count = 0
            
            for i in range(0, len(search_documents), batch_size):
                batch = search_documents[i:i + batch_size]
                
                try:
                    success = await self._index_document_batch(batch)
                    if success:
                        indexed_count += len(batch)
                    else:
                        failed_count += len(batch)
                        
                except Exception as e:
                    logger.error(f"Failed to index batch {i//batch_size + 1}: {e}")
                    failed_count += len(batch)
            
            logger.info(f"Indexed {indexed_count} chunks, {failed_count} failed")
            
            return indexed_count, failed_count
            
        except Exception as e:
            logger.error(f"Failed to index chunks: {e}")
            return 0, len(chunks)
    
    async def _generate_embeddings_for_chunks(self, chunks: List[Chunk]):
        """Generate embeddings for chunks."""
        try:
            texts = [chunk.text for chunk in chunks]
            
            # Generate embeddings
            embeddings = await self.aoai_client.generate_embeddings(
                texts=texts,
                model=self.settings.azure_openai.embedding_model
            )
            
            # Assign embeddings to chunks
            for chunk, embedding in zip(chunks, embeddings):
                chunk.set_embedding(embedding, self.settings.azure_openai.embedding_model)
            
            logger.debug(f"Generated embeddings for {len(chunks)} chunks")
            
        except Exception as e:
            logger.error(f"Failed to generate embeddings for chunks: {e}")
            raise
    
    async def _index_document_batch(self, documents: List[Dict[str, Any]]) -> bool:
        """Index a batch of documents."""
        try:
            headers = await self._get_search_headers()
            
            # Prepare batch request
            batch_request = {
                "value": [
                    {
                        "@search.action": "mergeOrUpload",
                        **doc
                    }
                    for doc in documents
                ]
            }
            
            # Submit batch
            index_url = f"{self.settings.ai_search.endpoint}/indexes/{self.settings.ai_search.index_name}/docs/index"
            
            async with self.session.post(
                index_url,
                headers=headers,
                json=batch_request,
                params={"api-version": "2023-11-01"}
            ) as response:
                if response.status in [200, 207]:  # 207 = partial success
                    result = await response.json()
                    
                    # Check for individual document errors
                    errors = [item for item in result.get("value", []) if not item.get("status")]
                    if errors:
                        logger.warning(f"Some documents failed to index: {len(errors)} errors")
                        for error in errors[:5]:  # Log first 5 errors
                            logger.warning(f"Index error: {error}")
                    
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"Batch index failed: {response.status} - {error_text}")
                    return False
                    
        except Exception as e:
            logger.error(f"Failed to index document batch: {e}")
            return False
    
    async def search_similar_chunks(self, query_text: str, 
                                  account_id: str = None,
                                  top_k: int = 10,
                                  score_threshold: float = 0.7) -> List[Dict[str, Any]]:
        """Search for similar chunks using vector similarity."""
        try:
            # Generate embedding for query
            query_embedding = await self.aoai_client.generate_single_embedding(query_text)
            
            if not query_embedding:
                logger.error("Failed to generate query embedding")
                return []
            
            return await self.search_by_vector(
                query_vector=query_embedding,
                account_id=account_id,
                top_k=top_k,
                score_threshold=score_threshold
            )
            
        except Exception as e:
            logger.error(f"Failed to search similar chunks: {e}")
            return []
    
    async def search_by_vector(self, query_vector: List[float],
                             account_id: str = None,
                             top_k: int = 10,
                             score_threshold: float = 0.7) -> List[Dict[str, Any]]:
        """Search using a pre-computed vector."""
        try:
            headers = await self._get_search_headers()
            
            # Build search request
            search_request = {
                "count": True,
                "top": top_k,
                "vectorQueries": [
                    {
                        "vector": query_vector,
                        "k": top_k,
                        "fields": "embedding"
                    }
                ],
                "select": "id,document_id,chunk_index,text,title,tags,entities,account_id,owner_email,created_at,section_title"
            }
            
            # Add account filter if specified
            if account_id:
                search_request["filter"] = f"account_id eq '{account_id}'"
            
            # Execute search
            search_url = f"{self.settings.ai_search.endpoint}/indexes/{self.settings.ai_search.index_name}/docs/search"
            
            async with self.session.post(
                search_url,
                headers=headers,
                json=search_request,
                params={"api-version": "2023-11-01"}
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    
                    # Filter by score threshold and format results
                    filtered_results = []
                    for item in result.get("value", []):
                        score = item.get("@search.score", 0)
                        if score >= score_threshold:
                            # Parse entities back from JSON
                            entities_str = item.get("entities", "[]")
                            try:
                                item["entities"] = json.loads(entities_str)
                            except:
                                item["entities"] = []
                            
                            filtered_results.append(item)
                    
                    logger.debug(f"Vector search returned {len(filtered_results)} results above threshold {score_threshold}")
                    
                    return filtered_results
                else:
                    error_text = await response.text()
                    logger.error(f"Vector search failed: {response.status} - {error_text}")
                    return []
                    
        except Exception as e:
            logger.error(f"Failed to search by vector: {e}")
            return []
    
    async def hybrid_search(self, query_text: str,
                          account_id: str = None,
                          top_k: int = 10) -> List[Dict[str, Any]]:
        """Perform hybrid search combining text and vector search."""
        try:
            # Generate embedding for vector search
            query_embedding = await self.aoai_client.generate_single_embedding(query_text)
            
            headers = await self._get_search_headers()
            
            # Build hybrid search request
            search_request = {
                "count": True,
                "top": top_k,
                "search": query_text,
                "searchFields": "text,title,tags,section_title",
                "vectorQueries": [
                    {
                        "vector": query_embedding,
                        "k": top_k,
                        "fields": "embedding"
                    }
                ] if query_embedding else [],
                "select": "id,document_id,chunk_index,text,title,tags,entities,account_id,owner_email,created_at,section_title"
            }
            
            # Add account filter if specified
            if account_id:
                search_request["filter"] = f"account_id eq '{account_id}'"
            
            # Execute search
            search_url = f"{self.settings.ai_search.endpoint}/indexes/{self.settings.ai_search.index_name}/docs/search"
            
            async with self.session.post(
                search_url,
                headers=headers,
                json=search_request,
                params={"api-version": "2023-11-01"}
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    
                    # Process results
                    processed_results = []
                    for item in result.get("value", []):
                        # Parse entities back from JSON
                        entities_str = item.get("entities", "[]")
                        try:
                            item["entities"] = json.loads(entities_str)
                        except:
                            item["entities"] = []
                        
                        processed_results.append(item)
                    
                    logger.debug(f"Hybrid search returned {len(processed_results)} results")
                    
                    return processed_results
                else:
                    error_text = await response.text()
                    logger.error(f"Hybrid search failed: {response.status} - {error_text}")
                    return []
                    
        except Exception as e:
            logger.error(f"Failed to perform hybrid search: {e}")
            return []
    
    async def delete_chunks_by_document(self, document_id: str) -> bool:
        """Delete all chunks for a specific document."""
        try:
            headers = await self._get_search_headers()
            
            # Search for chunks to delete
            search_request = {
                "search": "*",
                "filter": f"document_id eq '{document_id}'",
                "select": "id",
                "top": 1000  # Limit for safety
            }
            
            search_url = f"{self.settings.ai_search.endpoint}/indexes/{self.settings.ai_search.index_name}/docs/search"
            
            async with self.session.post(
                search_url,
                headers=headers,
                json=search_request,
                params={"api-version": "2023-11-01"}
            ) as response:
                if response.status != 200:
                    logger.error(f"Failed to find chunks for deletion: {response.status}")
                    return False
                
                result = await response.json()
                chunks_to_delete = result.get("value", [])
                
                if not chunks_to_delete:
                    logger.info(f"No chunks found for document {document_id}")
                    return True
            
            # Delete chunks in batches
            batch_request = {
                "value": [
                    {
                        "@search.action": "delete",
                        "id": chunk["id"]
                    }
                    for chunk in chunks_to_delete
                ]
            }
            
            index_url = f"{self.settings.ai_search.endpoint}/indexes/{self.settings.ai_search.index_name}/docs/index"
            
            async with self.session.post(
                index_url,
                headers=headers,
                json=batch_request,
                params={"api-version": "2023-11-01"}
            ) as response:
                if response.status in [200, 207]:
                    logger.info(f"Deleted {len(chunks_to_delete)} chunks for document {document_id}")
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to delete chunks: {response.status} - {error_text}")
                    return False
                    
        except Exception as e:
            logger.error(f"Failed to delete chunks for document {document_id}: {e}")
            return False
    
    async def get_index_statistics(self) -> Dict[str, Any]:
        """Get statistics about the search index."""
        try:
            headers = await self._get_search_headers()
            
            # Get index statistics
            stats_url = f"{self.settings.ai_search.endpoint}/indexes/{self.settings.ai_search.index_name}/stats"
            
            async with self.session.get(
                stats_url,
                headers=headers,
                params={"api-version": "2023-11-01"}
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.error(f"Failed to get index statistics: {response.status}")
                    return {}
                    
        except Exception as e:
            logger.error(f"Failed to get index statistics: {e}")
            return {}
    
    async def test_connection(self) -> bool:
        """Test the connection to the vector store."""
        try:
            headers = await self._get_search_headers()
            
            # Simple test query
            search_request = {
                "search": "*",
                "top": 1
            }
            
            search_url = f"{self.settings.ai_search.endpoint}/indexes/{self.settings.ai_search.index_name}/docs/search"
            
            async with self.session.post(
                search_url,
                headers=headers,
                json=search_request,
                params={"api-version": "2023-11-01"}
            ) as response:
                return response.status == 200
                
        except Exception as e:
            logger.error(f"Vector store connection test failed: {e}")
            return False
