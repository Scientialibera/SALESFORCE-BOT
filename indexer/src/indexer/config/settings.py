"""
Configuration settings for the document indexer.

This module handles all environment variable configuration
for Azure services, SharePoint, processing parameters, etc.
"""

import os
from typing import List, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AzureSettings(BaseSettings):
    """Azure service configuration.

    Authentication MUST use DefaultAzureCredential (az login for local dev,
    or managed identity in Azure). Client id/secret/tenant env vars are not
    supported in this repository.
    """


class AzureOpenAISettings(BaseSettings):
    """Azure OpenAI configuration."""
    
    endpoint: str = Field(alias="AOAI_ENDPOINT")
    api_version: str = Field(alias="AOAI_API_VERSION")
    chat_deployment: str = Field(alias="AOAI_CHAT_DEPLOYMENT")
    embedding_deployment: str = Field(alias="AOAI_EMBEDDING_DEPLOYMENT")
    embedding_dimensions: int = Field(alias="AOAI_EMBEDDING_DIMENSIONS")
    
    class Config:
        env_file = "../.env"
        extra = "ignore"


class DocumentIntelligenceSettings(BaseSettings):
    """Azure Document Intelligence configuration."""
    
    endpoint: Optional[str] = Field(default=None, alias="AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT")
    api_version: str = Field(alias="AZURE_DOCUMENT_INTELLIGENCE_API_VERSION")
    
    class Config:
        env_file = "../.env"
        extra = "ignore"


class SearchSettings(BaseSettings):
    """Azure AI Search configuration."""
    
    endpoint: str = Field(alias="AZURE_SEARCH_ENDPOINT")
    index_name: str = Field(alias="AZURE_SEARCH_INDEX")
    api_version: str = Field(alias="AZURE_SEARCH_API_VERSION")
    
    class Config:
        env_file = "../.env"
        extra = "ignore"


class CosmosSettings(BaseSettings):
    """Azure Cosmos DB configuration."""
    
    endpoint: str = Field(alias="COSMOS_ENDPOINT")
    database: str = Field(alias="COSMOS_DATABASE_NAME")
    processed_files_container: str = Field(alias="AZURE_COSMOS_PROCESSED_FILES_CONTAINER")
    jobs_container: str = Field(alias="AZURE_COSMOS_JOBS_CONTAINER")
    contracts_container: str = Field(alias="AZURE_COSMOS_CONTRACTS_CONTAINER")
    
    class Config:
        env_file = "../.env"
        extra = "ignore"


class GremlinSettings(BaseSettings):
    """Azure Cosmos DB Gremlin configuration."""
    
    endpoint: str = Field(alias="AZURE_COSMOS_GREMLIN_ENDPOINT")
    port: int = Field(alias="AZURE_COSMOS_GREMLIN_PORT")
    database: str = Field(alias="AZURE_COSMOS_GREMLIN_DATABASE")
    graph: str = Field(alias="AZURE_COSMOS_GREMLIN_GRAPH")
    username: Optional[str] = Field(default=None, alias="AZURE_COSMOS_GREMLIN_USERNAME")
    password: Optional[str] = Field(default=None, alias="AZURE_COSMOS_GREMLIN_PASSWORD")
    
    class Config:
        env_file = "../.env"
        extra = "ignore"


class FabricSettings(BaseSettings):
    """Microsoft Fabric configuration."""
    
    workspace_id: Optional[str] = Field(default=None, alias="FABRIC_WORKSPACE_ID")
    lakehouse_id: Optional[str] = Field(default=None, alias="FABRIC_LAKEHOUSE_ID")
    sql_endpoint: Optional[str] = Field(default=None, alias="FABRIC_SQL_ENDPOINT")
    sql_database: Optional[str] = Field(default=None, alias="FABRIC_SQL_DATABASE")
    
    class Config:
        env_file = "../.env"
        extra = "ignore"


class SharePointSettings(BaseSettings):
    """SharePoint Online configuration."""
    
    site_url: str = Field(alias="SHAREPOINT_SITE_URL")
    library_name: str = Field(alias="SHAREPOINT_LIBRARY_NAME")
    username: Optional[str] = Field(default=None, alias="SHAREPOINT_USERNAME")
    password: Optional[str] = Field(default=None, alias="SHAREPOINT_PASSWORD")
    client_id: Optional[str] = Field(default=None, alias="SHAREPOINT_CLIENT_ID")
    client_secret: Optional[str] = Field(default=None, alias="SHAREPOINT_CLIENT_SECRET")


class StorageSettings(BaseSettings):
    """Azure Storage configuration."""
    
    account_name: str = Field(alias="AZURE_STORAGE_ACCOUNT_NAME")
    container_name: str = Field(alias="AZURE_STORAGE_CONTAINER_NAME")
    cache_container: str = Field(alias="AZURE_STORAGE_CACHE_CONTAINER")


class ProcessingSettings(BaseSettings):
    """Document processing configuration."""
    
    batch_size: int = Field(alias="BATCH_SIZE")
    max_concurrent_requests: int = Field(alias="MAX_CONCURRENT_REQUESTS")
    chunk_size: int = Field(alias="CHUNK_SIZE")
    chunk_overlap: int = Field(alias="CHUNK_OVERLAP")
    max_file_size_mb: int = Field(alias="MAX_FILE_SIZE_MB")
    supported_file_types: List[str] = Field(alias="SUPPORTED_FILE_TYPES")
    
    # Document Intelligence options
    extract_tables: bool = Field(alias="EXTRACT_TABLES")
    extract_images: bool = Field(alias="EXTRACT_IMAGES")
    ocr_enabled: bool = Field(alias="OCR_ENABLED")
    language_detection: bool = Field(alias="LANGUAGE_DETECTION")
    supported_languages: List[str] = Field(alias="SUPPORTED_LANGUAGES")


class EmbeddingSettings(BaseSettings):
    """Embedding generation configuration."""
    
    batch_size: int = Field(alias="EMBEDDING_BATCH_SIZE")
    max_retries: int = Field(alias="EMBEDDING_MAX_RETRIES")
    retry_delay_seconds: int = Field(alias="EMBEDDING_RETRY_DELAY_SECONDS")


class ChangeDetectionSettings(BaseSettings):
    """Change detection configuration."""
    
    check_interval_minutes: int = Field(alias="CHECK_INTERVAL_MINUTES")
    etag_cache_ttl_hours: int = Field(alias="ETAG_CACHE_TTL_HOURS")
    delta_processing_enabled: bool = Field(alias="DELTA_PROCESSING_ENABLED")


class VectorSearchSettings(BaseSettings):
    """Vector search configuration."""
    
    dimensions: int = Field(alias="VECTOR_DIMENSIONS")
    similarity_algorithm: str = Field(alias="SIMILARITY_ALGORITHM")
    index_refresh_interval_seconds: int = Field(alias="INDEX_REFRESH_INTERVAL_SECONDS")


class GraphSettings(BaseSettings):
    """Graph database configuration."""
    
    batch_size: int = Field(alias="GRAPH_BATCH_SIZE")
    max_retries: int = Field(alias="GRAPH_MAX_RETRIES")
    relationship_types: List[str] = Field(alias="RELATIONSHIP_TYPES")


class RateLimitSettings(BaseSettings):
    """Rate limiting configuration."""
    
    sharepoint_requests_per_minute: int = Field(alias="SHAREPOINT_REQUESTS_PER_MINUTE")
    document_intelligence_requests_per_minute: int = Field(alias="DOCUMENT_INTELLIGENCE_REQUESTS_PER_MINUTE")
    openai_requests_per_minute: int = Field(alias="OPENAI_REQUESTS_PER_MINUTE")


class CacheSettings(BaseSettings):
    """Cache configuration."""
    
    ttl_hours: int = Field(alias="CACHE_TTL_HOURS")
    metadata_cache_ttl_hours: int = Field(alias="METADATA_CACHE_TTL_HOURS")
    embedding_cache_ttl_days: int = Field(alias="EMBEDDING_CACHE_TTL_DAYS")


class RetrySettings(BaseSettings):
    """Retry configuration."""
    
    max_retries: int = Field(default=3, alias="MAX_RETRIES")
    backoff_factor: float = Field(default=2.0, alias="RETRY_BACKOFF_FACTOR")
    max_wait_seconds: int = Field(default=60, alias="RETRY_MAX_WAIT_SECONDS")


class SecuritySettings(BaseSettings):
    """Security configuration."""
    
    enable_data_encryption: bool = Field(default=True, alias="ENABLE_DATA_ENCRYPTION")
    sanitize_content: bool = Field(default=True, alias="SANITIZE_CONTENT")
    remove_pii: bool = Field(default=True, alias="REMOVE_PII")
    content_filter_enabled: bool = Field(default=True, alias="CONTENT_FILTER_ENABLED")


class DevelopmentSettings(BaseSettings):
    """Development and testing configuration."""
    
    mock_sharepoint: bool = Field(default=False, alias="MOCK_SHAREPOINT")
    mock_document_intelligence: bool = Field(default=False, alias="MOCK_DOCUMENT_INTELLIGENCE")
    mock_embeddings: bool = Field(default=False, alias="MOCK_EMBEDDINGS")
    test_data_path: str = Field(default="./test_data", alias="TEST_DATA_PATH")
    sample_processing_only: bool = Field(default=False, alias="SAMPLE_PROCESSING_ONLY")


class Settings(BaseSettings):
    """Main application settings."""
    
    model_config = SettingsConfigDict(
        env_file="../.env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # Core application
    app_name: str = Field(default="salesforce-document-indexer", alias="APP_NAME")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    debug: bool = Field(default=False, alias="DEBUG")
    
    # Application Insights
    applicationinsights_connection_string: Optional[str] = Field(
        default=None, 
        alias="APPLICATIONINSIGHTS_CONNECTION_STRING"
    )
    
    # Health check
    health_check_interval_seconds: int = Field(default=30, alias="HEALTH_CHECK_INTERVAL_SECONDS")
    dependency_timeout_seconds: int = Field(default=10, alias="DEPENDENCY_TIMEOUT_SECONDS")
    
    # Nested settings
    azure: AzureSettings = Field(default_factory=AzureSettings)
    azure_openai: AzureOpenAISettings = Field(default_factory=AzureOpenAISettings)
    document_intelligence: DocumentIntelligenceSettings = Field(default_factory=DocumentIntelligenceSettings)
    search: SearchSettings = Field(default_factory=SearchSettings)
    cosmos: CosmosSettings = Field(default_factory=CosmosSettings)
    gremlin: GremlinSettings = Field(default_factory=GremlinSettings)
    fabric: FabricSettings = Field(default_factory=FabricSettings)
    sharepoint: SharePointSettings = Field(default_factory=SharePointSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    processing: ProcessingSettings = Field(default_factory=ProcessingSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    change_detection: ChangeDetectionSettings = Field(default_factory=ChangeDetectionSettings)
    vector_search: VectorSearchSettings = Field(default_factory=VectorSearchSettings)
    graph: GraphSettings = Field(default_factory=GraphSettings)
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    retry: RetrySettings = Field(default_factory=RetrySettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    development: DevelopmentSettings = Field(default_factory=DevelopmentSettings)
    
    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.environment.lower() in ("development", "dev", "local")
    
    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment.lower() in ("production", "prod")
    
    def get_supported_file_extensions(self) -> List[str]:
        """Get list of supported file extensions with dots."""
        return [f".{ext}" for ext in self.processing.supported_file_types]


# Global settings instance
settings = Settings()
