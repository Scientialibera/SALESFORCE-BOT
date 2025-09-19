"""Utils: embeddings (description only).

- Compute vector for strings; cosine similarity helpers.
- Thresholding and tie-breaking for account resolution.
"""

import numpy as np
from typing import List
import asyncio
from openai import AsyncAzureOpenAI
from chatbot.config.settings import settings


async def get_embedding(text: str, client: AsyncAzureOpenAI = None) -> List[float]:
    """
    Get embedding for text using Azure OpenAI.
    
    Args:
        text: Text to embed
        client: Azure OpenAI client (optional)
        
    Returns:
        Embedding vector
    """
    if client is None:
        from chatbot.clients.aoai_client import AOAIClient
        aoai_client = AOAIClient()
        client = aoai_client.client
    
    try:
        response = await client.embeddings.create(
            input=text,
            model=settings.azure_openai.embedding_deployment
        )
        return response.data[0].embedding
    except Exception as e:
        # Return a zero vector if embedding fails
        return [0.0] * 1536  # Default dimension for text-embedding-3-small


def compute_cosine_similarity(embedding1: List[float], embedding2: List[float]) -> float:
    """
    Compute cosine similarity between two embeddings.
    
    Args:
        embedding1: First embedding vector
        embedding2: Second embedding vector
        
    Returns:
        Cosine similarity score (0-1)
    """
    if not embedding1 or not embedding2:
        return 0.0
    
    try:
        # Convert to numpy arrays
        vec1 = np.array(embedding1)
        vec2 = np.array(embedding2)
        
        # Compute cosine similarity
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
            
        return dot_product / (norm1 * norm2)
    except Exception:
        return 0.0


class EmbeddingUtils:
    """Utility class for embedding operations."""
    
    def __init__(self):
        """Initialize embedding utilities."""
        pass
    
    async def get_embedding(self, text: str, client: AsyncAzureOpenAI = None) -> List[float]:
        """Get embedding for text."""
        return await get_embedding(text, client)
    
    def compute_cosine_similarity(self, embedding1: List[float], embedding2: List[float]) -> float:
        """Compute cosine similarity between embeddings."""
        return compute_cosine_similarity(embedding1, embedding2)
