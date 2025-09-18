"""
Document model for SharePoint document metadata and processing state.

This model represents a document in the system including its metadata,
processing status, and relationship information.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DocumentStatus(str, Enum):
    """Document processing status."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class DocumentType(str, Enum):
    """Document type classification."""
    CONTRACT = "contract"
    PROPOSAL = "proposal"
    INVOICE = "invoice"
    REPORT = "report"
    PRESENTATION = "presentation"
    EMAIL = "email"
    OTHER = "other"


class Document(BaseModel):
    """
    Document model representing a file from SharePoint.
    
    This model tracks document metadata, processing status,
    and relationships to accounts and other entities.
    """
    
    # Identity and source
    id: str = Field(..., description="Unique document identifier")
    file_name: str = Field(..., description="Original file name")
    file_path: str = Field(..., description="SharePoint file path")
    sharepoint_url: str = Field(..., description="Direct SharePoint URL")
    site_url: str = Field(..., description="SharePoint site URL")
    library_name: str = Field(..., description="SharePoint library name")
    
    # Metadata
    file_size: int = Field(..., description="File size in bytes")
    file_extension: str = Field(..., description="File extension (e.g., .pdf)")
    mime_type: str = Field(..., description="MIME type")
    document_type: DocumentType = Field(default=DocumentType.OTHER, description="Classification of document type")
    
    # SharePoint metadata
    etag: Optional[str] = Field(None, description="SharePoint ETag for change detection")
    version: Optional[str] = Field(None, description="Document version")
    created_by: Optional[str] = Field(None, description="Created by user")
    modified_by: Optional[str] = Field(None, description="Last modified by user")
    created_at: datetime = Field(..., description="Creation timestamp")
    modified_at: datetime = Field(..., description="Last modification timestamp")
    
    # Business context
    account_id: Optional[str] = Field(None, description="Associated account ID")
    account_name: Optional[str] = Field(None, description="Associated account name")
    owner_email: Optional[str] = Field(None, description="Document owner email")
    tags: List[str] = Field(default_factory=list, description="Document tags")
    
    # Processing status
    status: DocumentStatus = Field(default=DocumentStatus.PENDING, description="Processing status")
    processed_at: Optional[datetime] = Field(None, description="When processing completed")
    processing_duration_seconds: Optional[float] = Field(None, description="Processing duration")
    error_message: Optional[str] = Field(None, description="Error message if processing failed")
    retry_count: int = Field(default=0, description="Number of processing retries")
    
    # Content analysis
    language: Optional[str] = Field(None, description="Detected language code")
    page_count: Optional[int] = Field(None, description="Number of pages")
    word_count: Optional[int] = Field(None, description="Estimated word count")
    has_tables: bool = Field(default=False, description="Whether document contains tables")
    has_images: bool = Field(default=False, description="Whether document contains images")
    
    # Extraction results
    text_content: Optional[str] = Field(None, description="Extracted text content")
    structured_content: Optional[Dict[str, Any]] = Field(None, description="Structured content (tables, etc.)")
    summary: Optional[str] = Field(None, description="AI-generated summary")
    key_phrases: List[str] = Field(default_factory=list, description="Extracted key phrases")
    entities: List[Dict[str, Any]] = Field(default_factory=list, description="Named entities")
    
    # Chunking information
    chunk_count: int = Field(default=0, description="Number of chunks created")
    chunk_ids: List[str] = Field(default_factory=list, description="List of chunk IDs")
    
    # Vector search metadata
    indexed_at: Optional[datetime] = Field(None, description="When indexed in vector store")
    vector_index_id: Optional[str] = Field(None, description="Vector store index ID")
    
    # System metadata
    indexer_version: Optional[str] = Field(None, description="Version of indexer that processed this")
    processing_metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional processing metadata")
    
    class Config:
        """Pydantic configuration."""
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
    
    def is_processable(self) -> bool:
        """Check if document can be processed."""
        return self.status in [DocumentStatus.PENDING, DocumentStatus.FAILED]
    
    def is_completed(self) -> bool:
        """Check if document processing is completed."""
        return self.status == DocumentStatus.COMPLETED
    
    def mark_processing(self) -> None:
        """Mark document as being processed."""
        self.status = DocumentStatus.PROCESSING
    
    def mark_completed(self, processing_duration: Optional[float] = None) -> None:
        """Mark document as completed."""
        self.status = DocumentStatus.COMPLETED
        self.processed_at = datetime.utcnow()
        if processing_duration:
            self.processing_duration_seconds = processing_duration
    
    def mark_failed(self, error_message: str) -> None:
        """Mark document as failed."""
        self.status = DocumentStatus.FAILED
        self.error_message = error_message
        self.retry_count += 1
    
    def should_retry(self, max_retries: int = 3) -> bool:
        """Check if document should be retried."""
        return self.status == DocumentStatus.FAILED and self.retry_count < max_retries
    
    def get_display_name(self) -> str:
        """Get a human-readable display name."""
        if self.account_name:
            return f"{self.file_name} ({self.account_name})"
        return self.file_name
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return self.model_dump(mode='json', exclude_none=True)
