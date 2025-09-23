"""
Configuration settings for the Account Q&A Bot.

This module defines the application settings using Pydantic Settings with
support for environment variables and Azure services configuration.
All Azure services use DefaultAzureCredential for authentication.
"""

import os
from typing import Optional, List, Dict
from pydantic import Field, validator
from pydantic_settings import BaseSettings


class AzureOpenAISettings(BaseSettings):
    """Azure OpenAI service configuration."""
    
    endpoint: str = Field(..., description="Azure OpenAI service endpoint")

    @validator("endpoint", pre=True, always=True)
    def ensure_openai_domain(cls, v):
        # Force correct domain for Azure OpenAI endpoint
        if v and ".cognitiveservices.azure.com" in v:
            v = v.replace(".cognitiveservices.azure.com", ".openai.azure.com")
        return v
    api_version: str = Field(default="2024-02-15-preview", description="API version")
    chat_deployment: str = Field(..., description="Chat completion deployment name")
    embedding_deployment: str = Field(..., description="Text embedding deployment name")
    embedding_dimensions: int = Field(default=1536, description="Embedding dimensions")
    max_tokens: int = Field(default=4000, description="Maximum tokens for completions")
    temperature: float = Field(default=0.1, description="Temperature for completions")
    
    class Config:
        env_prefix = "AOAI_"
        env_file = ".env"
        extra = "ignore"


class CosmosDBSettings(BaseSettings):
    """Azure Cosmos DB configuration."""
    
    endpoint: str = Field(..., description="Cosmos DB account endpoint")
    database_name: str = Field(..., description="Database name")
    chat_container: str = Field(default="chat_history", description="Chat history container")
    cache_container: str = Field(default="cache", description="Cache container")
    feedback_container: str = Field(default="feedback", description="Feedback container")
    agent_functions_container: str = Field(default="agent_functions", description="Agent functions container")
    prompts_container: str = Field(default="prompts", description="Prompts container")
    sql_schema_container: str = Field(default="sql_schema", description="SQL schema container")
    contracts_text_container: str = Field(default="contracts_text", description="Contracts text container")
    processed_files_container: str = Field(default="processed_files", description="Processed files container")
    account_resolver_container: str = Field(default="account_resolver", description="Account resolver container")
    
    class Config:
        env_prefix = "COSMOS_"
        env_file = ".env"
        extra = "ignore"
        env_file = ".env"
        extra = "ignore"


class GremlinSettings(BaseSettings):
    """Gremlin graph database configuration.

    The `endpoint` is optional to make local development and tests easier when
    a Gremlin server is not available. Runtime code should check for a
    configured endpoint and skip initializing Gremlin clients when it is None.
    """

    endpoint: Optional[str] = Field(default=None, description="Gremlin endpoint")
    database_name: str = Field(default="graphdb", description="Graph database name")
    graph_name: str = Field(default="account_graph", description="Graph container name")
    max_concurrent_connections: int = Field(default=10, description="Max concurrent connections")
    connection_timeout: int = Field(default=30, description="Connection timeout in seconds")

    class Config:
        env_prefix = "GREMLIN_"
        env_file = ".env"
        extra = "ignore"


class SearchSettings(BaseSettings):
    """Azure AI Search configuration."""
    
    endpoint: Optional[str] = Field(default=None, description="Azure AI Search service endpoint")
    index_name: str = Field(default="contracts", description="Search index name")
    semantic_config: str = Field(default="default", description="Semantic search configuration")
    api_version: str = Field(default="2023-11-01", description="Search API version")
    
    class Config:
        env_prefix = "SEARCH_"
        env_file = ".env"
        extra = "ignore"
        env_file = ".env"
        extra = "ignore"


class FabricLakehouseSettings(BaseSettings):
    """Microsoft Fabric lakehouse configuration for document retrieval and SQL queries."""
    
    # Make these optional for local development and test runs where Fabric is
    # not available. Runtime code should check for an endpoint/database and
    # skip initializing Fabric clients when they're not provided.
    sql_endpoint: Optional[str] = Field(default=None, description="Fabric lakehouse SQL endpoint")
    database: Optional[str] = Field(default=None, description="Lakehouse database name")
    workspace_id: Optional[str] = Field(default=None, description="Fabric workspace ID")
    contracts_table: str = Field(default="contracts_text", description="Contracts table name")
    connection_timeout: int = Field(default=30, description="Connection timeout in seconds")
    max_rows: int = Field(default=1000, description="Maximum rows to return per query")
    query_timeout: int = Field(default=60, description="Query timeout in seconds")
    
    class Config:
        env_prefix = "FABRIC_"
        env_file = ".env"
        extra = "ignore"
        env_file = ".env"
        extra = "ignore"


class RBACSettings(BaseSettings):
    """Role-based access control configuration."""
    
    enforce_rbac: bool = Field(default=True, description="Enable RBAC enforcement")
    admin_users: List[str] = Field(default_factory=list, description="Admin user emails")
    default_access_level: str = Field(default="read", description="Default access level")
    cache_duration: int = Field(default=3600, description="RBAC cache duration in seconds")
    
    @validator("admin_users", pre=True)
    def parse_admin_users(cls, v):
        """Parse admin users from string or list, handling empty values."""
        if v is None or v == "":
            return []
        if isinstance(v, str):
            return [user.strip() for user in v.split(",") if user.strip()]
        return v
    
    class Config:
        env_prefix = "RBAC_"
        env_file = ".env"
        extra = "ignore"


class TelemetrySettings(BaseSettings):
    """Telemetry and monitoring configuration."""
    
    instrumentation_key: Optional[str] = Field(default=None, description="Application Insights key")
    connection_string: Optional[str] = Field(default=None, description="Application Insights connection string")
    enable_telemetry: bool = Field(default=True, description="Enable telemetry collection")
    log_level: str = Field(default="INFO", description="Logging level")
    sampling_rate: float = Field(default=1.0, description="Telemetry sampling rate")
    
    class Config:
        env_prefix = "TELEMETRY_"
        env_file = ".env"
        extra = "ignore"


class CacheSettings(BaseSettings):
    """Cache configuration."""
    
    default_ttl: int = Field(default=3600, description="Default TTL in seconds")
    max_entries: int = Field(default=10000, description="Maximum cache entries")
    cleanup_interval: int = Field(default=300, description="Cache cleanup interval in seconds")
    
    class Config:
        env_prefix = "CACHE_"
        env_file = ".env"
        extra = "ignore"


class AccountResolverSettings(BaseSettings):
    """Account resolver service configuration."""
    
    confidence_threshold: float = Field(default=0.7, description="Confidence threshold for entity resolution")
    max_candidates: int = Field(default=10, description="Maximum candidate entities to consider")
    cache_ttl: int = Field(default=1800, description="Cache TTL for resolved entities")
    embedding_model: str = Field(default="text-embedding-3-small", description="Embedding model for similarity")
    
    class Config:
        env_prefix = "ACCOUNT_RESOLVER_"
        env_file = ".env"
        extra = "ignore"


class FeedbackSettings(BaseSettings):
    """Feedback service configuration."""
    
    enable_feedback: bool = Field(default=True, description="Enable feedback collection")
    auto_save: bool = Field(default=True, description="Auto-save feedback")
    rating_scale: int = Field(default=5, description="Rating scale (1-N)")
    
    class Config:
        env_prefix = "FEEDBACK_"
        env_file = ".env"
        extra = "ignore"


class ChatHistorySettings(BaseSettings):
    """Chat history service configuration."""
    
    max_history_length: int = Field(default=50, description="Maximum conversation history length")
    default_context_window: int = Field(default=5, description="Default context window for conversations")
    enable_search: bool = Field(default=True, description="Enable conversation search")
    search_limit: int = Field(default=20, description="Default search result limit")
    
    class Config:
        env_prefix = "CHAT_HISTORY_"
        env_file = ".env"
        extra = "ignore"


class RetrievalSettings(BaseSettings):
    """Retrieval service configuration."""
    
    max_results: int = Field(default=10, description="Maximum retrieval results")
    chunk_size: int = Field(default=1000, description="Text chunk size for retrieval")
    chunk_overlap: int = Field(default=200, description="Overlap between chunks")
    similarity_threshold: float = Field(default=0.7, description="Similarity threshold for retrieval")
    enable_hybrid_search: bool = Field(default=True, description="Enable hybrid search")
    
    class Config:
        env_prefix = "RETRIEVAL_"
        env_file = ".env"
        extra = "ignore"


class GraphSettings(BaseSettings):
    """Graph service configuration."""
    
    max_traversal_depth: int = Field(default=3, description="Maximum graph traversal depth")
    max_results: int = Field(default=50, description="Maximum graph query results")
    query_timeout: int = Field(default=30, description="Graph query timeout in seconds")
    enable_caching: bool = Field(default=True, description="Enable graph query caching")
    
    class Config:
        env_prefix = "GRAPH_"
        env_file = ".env"
        extra = "ignore"


class PlannerSettings(BaseSettings):
    """Planner service configuration."""
    
    max_iterations: int = Field(default=10, description="Maximum planner iterations")
    enable_step_validation: bool = Field(default=True, description="Enable step validation")
    timeout_seconds: int = Field(default=120, description="Plan execution timeout")
    enable_parallel_execution: bool = Field(default=False, description="Enable parallel step execution")
    
    class Config:
        env_prefix = "PLANNER_"
        env_file = ".env"
        extra = "ignore"


class AgentSettings(BaseSettings):
    """Agent configuration."""
    
    sql_agent_enabled: bool = Field(default=True, description="Enable SQL agent")
    graph_agent_enabled: bool = Field(default=True, description="Enable Graph agent")
    max_function_calls: int = Field(default=10, description="Maximum function calls per agent")
    agent_timeout: int = Field(default=60, description="Agent execution timeout in seconds")
    
    class Config:
        env_prefix = "AGENT_"
        env_file = ".env"
        extra = "ignore"


class SecuritySettings(BaseSettings):
    """Security configuration."""
    
    jwt_secret_key: Optional[str] = Field(default=None, description="JWT secret key")
    jwt_algorithm: str = Field(default="HS256", description="JWT algorithm")
    jwt_expiration: int = Field(default=3600, description="JWT expiration in seconds")
    enable_cors: bool = Field(default=True, description="Enable CORS")
    max_request_size: int = Field(default=10485760, description="Maximum request size in bytes")
    
    class Config:
        env_prefix = "SECURITY_"
        env_file = ".env"
        extra = "ignore"


class FeatureFlagsSettings(BaseSettings):
    """Feature flags configuration."""
    
    # Semantic Kernel removed - using simplified approach
    enable_advanced_analytics: bool = Field(default=True, description="Enable advanced analytics")
    enable_experimental_features: bool = Field(default=False, description="Enable experimental features")
    enable_performance_monitoring: bool = Field(default=True, description="Enable performance monitoring")
    
    class Config:
        env_prefix = "FEATURE_"
        env_file = ".env"
        extra = "ignore"


class ApplicationSettings(BaseSettings):
    """Main application settings."""
    
    # Application metadata
    app_name: str = Field(default="Account Q&A Bot", description="Application name")
    version: str = Field(default="1.0.0", description="Application version")
    debug: bool = Field(default=False, description="Debug mode")
    environment: str = Field(default="development", description="Environment (development, staging, production)")
    dev_mode: bool = Field(default=False, description="Development mode - uses dummy data instead of real services")
    
    # API configuration
    api_host: str = Field(default="0.0.0.0", description="API host")
    api_port: int = Field(default=8000, description="API port")
    api_prefix: str = Field(default="/api/v1", description="API prefix")
    
    # Security
    cors_origins: List[str] = Field(default_factory=lambda: ["*"], description="CORS origins")
    jwt_audience: Optional[str] = Field(default=None, description="JWT audience")
    jwt_issuer: Optional[str] = Field(default=None, description="JWT issuer")
    
    # Service configurations
    azure_openai: AzureOpenAISettings = Field(default_factory=AzureOpenAISettings)
    cosmos_db: CosmosDBSettings = Field(default_factory=CosmosDBSettings)
    gremlin: GremlinSettings = Field(default_factory=GremlinSettings)
    search: SearchSettings = Field(default_factory=SearchSettings)
    fabric_lakehouse: FabricLakehouseSettings = Field(default_factory=FabricLakehouseSettings)
    rbac: RBACSettings = Field(default_factory=RBACSettings)
    telemetry: TelemetrySettings = Field(default_factory=TelemetrySettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    account_resolver: AccountResolverSettings = Field(default_factory=AccountResolverSettings)
    feedback: FeedbackSettings = Field(default_factory=FeedbackSettings)
    chat_history: ChatHistorySettings = Field(default_factory=ChatHistorySettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    graph: GraphSettings = Field(default_factory=GraphSettings)
    planner: PlannerSettings = Field(default_factory=PlannerSettings)
    agents: AgentSettings = Field(default_factory=AgentSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    feature_flags: FeatureFlagsSettings = Field(default_factory=FeatureFlagsSettings)
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"
    
    @validator("cors_origins", pre=True)
    def parse_cors_origins(cls, v):
        """Parse CORS origins from string or list."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v


# Global settings instance
settings = ApplicationSettings()

