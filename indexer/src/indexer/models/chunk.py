"""Chunk model for document segments."""

from datetime import datetime
from typing import Dict, List, Optional, Any
from uuid import uuid4
from pydantic import BaseModel, Field, ConfigDict


class ChunkMetadata(BaseModel):
    """Metadata for document chunks."""
    model_config = ConfigDict(extra="allow")
    
    # Document source information
    document_id: str
    page_number: Optional[int] = None
    section_title: Optional[str] = None
    paragraph_index: Optional[int] = None
    
    # Content characteristics
    content_type: str = "text"  # text, table, image, header, footer
    language: Optional[str] = None
    confidence_score: Optional[float] = None
    
    # Business context
    account_id: Optional[str] = None
    owner_email: Optional[str] = None
    department: Optional[str] = None
    project_name: Optional[str] = None
    
    # Processing metadata
    extraction_method: str = "document_intelligence"
    processing_timestamp: datetime = Field(default_factory=datetime.utcnow)
    chunk_strategy: str = "paragraph"  # paragraph, sentence, fixed_size, semantic


class Chunk(BaseModel):
    """Represents a chunk of content from a document for vector search."""
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        str_strip_whitespace=True
    )
    
    # Primary identifiers
    id: str = Field(default_factory=lambda: str(uuid4()))
    document_id: str
    chunk_index: int
    
    # Content
    text: str = Field(min_length=1, max_length=8000)
    title: Optional[str] = None
    
    # Vector embedding
    embedding: Optional[List[float]] = None
    embedding_model: Optional[str] = None
    
    # Position information
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)
    
    # Metadata
    metadata: ChunkMetadata
    
    # Additional context
    tags: List[str] = Field(default_factory=list)
    entities: List[Dict[str, Any]] = Field(default_factory=list)
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    
    def __init__(self, **data):
        super().__init__(**data)
        if self.end_offset < self.start_offset:
            raise ValueError("end_offset must be greater than or equal to start_offset")
    
    @property
    def length(self) -> int:
        """Get the length of the chunk text."""
        return len(self.text)
    
    @property
    def char_count(self) -> int:
        """Get character count of the chunk."""
        return self.end_offset - self.start_offset
    
    def add_entity(self, entity_type: str, entity_text: str, confidence: float = None) -> None:
        """Add a named entity to the chunk."""
        entity = {
            "type": entity_type,
            "text": entity_text,
            "start": self.text.lower().find(entity_text.lower()),
            "end": self.text.lower().find(entity_text.lower()) + len(entity_text)
        }
        if confidence is not None:
            entity["confidence"] = confidence
        
        self.entities.append(entity)
        self.updated_at = datetime.utcnow()
    
    def add_tag(self, tag: str) -> None:
        """Add a tag to the chunk."""
        if tag not in self.tags:
            self.tags.append(tag)
            self.updated_at = datetime.utcnow()
    
    def set_embedding(self, embedding: List[float], model: str) -> None:
        """Set the vector embedding for the chunk."""
        self.embedding = embedding
        self.embedding_model = model
        self.updated_at = datetime.utcnow()
    
    def to_search_document(self) -> Dict[str, Any]:
        """Convert chunk to Azure AI Search document format."""
        doc = {
            "id": self.id,
            "document_id": self.document_id,
            "chunk_index": self.chunk_index,
            "text": self.text,
            "title": self.title,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "length": self.length,
            "tags": self.tags,
            "created_at": self.created_at.isoformat(),
            **self.metadata.model_dump()
        }
        
        if self.embedding:
            doc["embedding"] = self.embedding
            doc["embedding_model"] = self.embedding_model
        
        if self.entities:
            doc["entities"] = self.entities
        
        return doc
    
    def to_graph_vertex(self) -> Dict[str, Any]:
        """Convert chunk to Gremlin graph vertex format."""
        properties = {
            "label": "chunk",
            "document_id": self.document_id,
            "chunk_index": self.chunk_index,
            "text": self.text[:1000],  # Truncate for graph storage
            "title": self.title,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "length": self.length,
            "content_type": self.metadata.content_type,
            "page_number": self.metadata.page_number,
            "created_at": self.created_at.isoformat()
        }
        
        # Add business context if available
        if self.metadata.account_id:
            properties["account_id"] = self.metadata.account_id
        if self.metadata.owner_email:
            properties["owner_email"] = self.metadata.owner_email
        if self.metadata.department:
            properties["department"] = self.metadata.department
        
        return {
            "id": self.id,
            "properties": properties
        }
    
    @classmethod
    def from_search_document(cls, doc: Dict[str, Any]) -> "Chunk":
        """Create chunk from Azure AI Search document."""
        metadata_fields = {
            "document_id", "page_number", "section_title", "paragraph_index",
            "content_type", "language", "confidence_score", "account_id",
            "owner_email", "department", "project_name", "extraction_method",
            "processing_timestamp", "chunk_strategy"
        }
        
        metadata_data = {k: v for k, v in doc.items() if k in metadata_fields}
        chunk_data = {k: v for k, v in doc.items() if k not in metadata_fields}
        
        # Handle datetime conversion
        if "created_at" in chunk_data and isinstance(chunk_data["created_at"], str):
            chunk_data["created_at"] = datetime.fromisoformat(chunk_data["created_at"])
        
        chunk_data["metadata"] = ChunkMetadata(**metadata_data)
        return cls(**chunk_data)
