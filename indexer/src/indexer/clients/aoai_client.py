"""Azure OpenAI client for embeddings and language model operations."""

import asyncio
import logging
from typing import List, Optional, Dict, Any
from azure.identity.aio import DefaultAzureCredential
from openai import AsyncAzureOpenAI
from openai.types import CreateEmbeddingResponse
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from ..config.settings import Settings


logger = logging.getLogger(__name__)


class AzureOpenAIClient:
    """Client for Azure OpenAI services."""
    
    def __init__(self, settings: Settings):
        """Initialize the Azure OpenAI client."""
        self.settings = settings
        self.credential = DefaultAzureCredential()
        self.client: Optional[AsyncAzureOpenAI] = None
        self._initialized = False
    
    async def initialize(self):
        """Initialize the async client."""
        if self._initialized:
            return
        
        try:
            # Get access token for Azure OpenAI
            token_response = await self.credential.get_token("https://cognitiveservices.azure.com/.default")
            
            self.client = AsyncAzureOpenAI(
                azure_endpoint=self.settings.azure_openai.endpoint,
                api_version=self.settings.azure_openai.api_version,
                azure_ad_token=token_response.token
            )
            
            self._initialized = True
            logger.info("Azure OpenAI client initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Azure OpenAI client: {e}")
            raise
    
    async def close(self):
        """Close the client and clean up resources."""
        if self.client:
            await self.client.close()
        if self.credential:
            await self.credential.close()
        self._initialized = False
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((Exception,))
    )
    async def generate_embeddings(self, texts: List[str], model: str = None) -> List[List[float]]:
        """Generate embeddings for a list of texts."""
        if not self._initialized:
            await self.initialize()
        
        if not texts:
            return []
        
        model = model or self.settings.azure_openai.embedding_model
        
        try:
            # Split large batches to respect API limits
            batch_size = 16  # Azure OpenAI embedding batch limit
            all_embeddings = []
            
            for i in range(0, len(texts), batch_size):
                batch = texts[i:i + batch_size]
                
                # Clean and validate texts
                cleaned_batch = []
                for text in batch:
                    if text and text.strip():
                        # Truncate to max tokens (8191 for text-embedding-3-small)
                        cleaned_text = text.strip()[:8000]  # Conservative limit
                        cleaned_batch.append(cleaned_text)
                    else:
                        cleaned_batch.append("empty content")
                
                logger.debug(f"Generating embeddings for batch of {len(cleaned_batch)} texts")
                
                response: CreateEmbeddingResponse = await self.client.embeddings.create(
                    input=cleaned_batch,
                    model=model
                )
                
                batch_embeddings = [data.embedding for data in response.data]
                all_embeddings.extend(batch_embeddings)
                
                # Brief pause between batches to respect rate limits
                if i + batch_size < len(texts):
                    await asyncio.sleep(0.1)
            
            logger.info(f"Generated {len(all_embeddings)} embeddings using model {model}")
            return all_embeddings
            
        except Exception as e:
            logger.error(f"Failed to generate embeddings: {e}")
            raise
    
    async def generate_single_embedding(self, text: str, model: str = None) -> List[float]:
        """Generate embedding for a single text."""
        embeddings = await self.generate_embeddings([text], model)
        return embeddings[0] if embeddings else []
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((Exception,))
    )
    async def extract_entities(self, text: str, max_tokens: int = 500) -> List[Dict[str, Any]]:
        """Extract named entities from text using LLM."""
        if not self._initialized:
            await self.initialize()
        
        if not text or not text.strip():
            return []
        
        try:
            system_prompt = """
You are an expert at extracting named entities from business documents.
Extract entities like: PERSON, ORGANIZATION, LOCATION, PRODUCT, PROJECT, DATE, MONEY, TECHNOLOGY.

Return a JSON array of entities with this format:
[{"type": "PERSON", "text": "John Smith", "confidence": 0.95}]

Only return valid JSON, no other text.
"""
            
            user_prompt = f"Extract entities from this text:\n\n{text[:2000]}"  # Limit input size
            
            response = await self.client.chat.completions.create(
                model=self.settings.azure_openai.chat_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=max_tokens,
                temperature=0.1
            )
            
            result_text = response.choices[0].message.content.strip()
            
            # Try to parse JSON
            import json
            try:
                entities = json.loads(result_text)
                if isinstance(entities, list):
                    return entities
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse entity extraction JSON: {result_text}")
            
            return []
            
        except Exception as e:
            logger.error(f"Failed to extract entities: {e}")
            return []
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((Exception,))
    )
    async def summarize_document(self, text: str, max_tokens: int = 200) -> str:
        """Generate a summary of document content."""
        if not self._initialized:
            await self.initialize()
        
        if not text or not text.strip():
            return ""
        
        try:
            system_prompt = """
You are an expert at summarizing business documents.
Create a concise summary that captures the key points, purpose, and main topics.
Focus on business-relevant information like projects, decisions, processes, and outcomes.
Keep the summary under 150 words.
"""
            
            user_prompt = f"Summarize this document:\n\n{text[:4000]}"  # Limit input size
            
            response = await self.client.chat.completions.create(
                model=self.settings.azure_openai.chat_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=max_tokens,
                temperature=0.3
            )
            
            summary = response.choices[0].message.content.strip()
            logger.debug(f"Generated summary: {summary[:100]}...")
            
            return summary
            
        except Exception as e:
            logger.error(f"Failed to generate summary: {e}")
            return ""
    
    async def test_connection(self) -> bool:
        """Test the connection to Azure OpenAI."""
        try:
            await self.initialize()
            
            # Test with a simple embedding
            embeddings = await self.generate_embeddings(["test connection"])
            
            return len(embeddings) > 0 and len(embeddings[0]) > 0
            
        except Exception as e:
            logger.error(f"Azure OpenAI connection test failed: {e}")
            return False
    
    def get_embedding_dimension(self, model: str = None) -> int:
        """Get the dimension size for the embedding model."""
        model = model or self.settings.azure_openai.embedding_model
        
        # Common Azure OpenAI embedding model dimensions
        model_dimensions = {
            "text-embedding-ada-002": 1536,
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072
        }
        
        return model_dimensions.get(model, 1536)  # Default to ada-002 dimension
