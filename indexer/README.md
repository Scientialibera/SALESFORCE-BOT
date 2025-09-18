# SharePoint Document Indexer

AI-powered document indexing service that processes SharePoint documents, extracts content using Azure Document Intelligence, and creates searchable vector embeddings in Azure AI Search.

## Architecture

The indexer follows a layered architecture:

- **FastAPI Application**: REST API for job management and search
- **Processing Pipelines**: Document processing and embedding generation workflows
- **Service Layer**: Business logic for document extraction, chunking, and vector operations
- **Repository Layer**: Data access for Cosmos DB (SQL + Gremlin APIs)
- **Client Layer**: Azure service integrations (Document Intelligence, AI Search, SharePoint, OpenAI)

## Key Features

### Document Processing
- SharePoint Online integration with comprehensive file discovery
- Azure Document Intelligence for advanced content extraction
- Multiple chunking strategies (fixed, semantic, paragraph, sentence)
- Entity extraction and metadata enrichment
- Change Data Capture (CDC) for incremental processing

### Vector Search
- Azure AI Search integration with vector and hybrid search
- Multiple embedding models support (text-embedding-ada-002, text-embedding-3-small/large)
- Semantic ranking and filtering capabilities
- Account-based access control

### Job Management
- Asynchronous background processing
- Progress tracking and metrics collection
- Comprehensive error handling and retry logic
- Full and incremental indexing workflows

### Machine Learning
- Advanced text preprocessing with NLTK and spaCy
- TF-IDF analysis and feature extraction
- Document classification and similarity analysis
- Entity recognition and named entity extraction

## Configuration

Configure the application using environment variables:

### Azure Settings
```bash
# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://your-openai.openai.azure.com/
AZURE_OPENAI_API_VERSION=2024-02-01
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o
AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME=text-embedding-ada-002

# Cosmos DB
COSMOS_DB_ENDPOINT=https://your-cosmos.documents.azure.com:443/
COSMOS_DB_DATABASE_NAME=salesforce-bot
COSMOS_DB_CONTAINER_NAME=documents
COSMOS_DB_GREMLIN_ENDPOINT=wss://your-cosmos.gremlin.cosmos.azure.com:443/

# Document Intelligence
DOCUMENT_INTELLIGENCE_ENDPOINT=https://your-doc-intel.cognitiveservices.azure.com/

# SharePoint
SHAREPOINT_SITE_URL=https://yourtenant.sharepoint.com/sites/yoursite
SHAREPOINT_CLIENT_ID=your-app-registration-id
SHAREPOINT_TENANT_ID=your-tenant-id

# Azure AI Search
AZURE_SEARCH_ENDPOINT=https://your-search.search.windows.net
AZURE_SEARCH_INDEX_NAME=documents-index
```

### Processing Settings
```bash
# Chunking
CHUNK_SIZE=1000
CHUNK_OVERLAP=200
MAX_CHUNKS_PER_DOCUMENT=100

# Vector Search
VECTOR_DIMENSIONS=1536
SIMILARITY_THRESHOLD=0.7

# Job Management
MAX_CONCURRENT_JOBS=5
JOB_TIMEOUT_MINUTES=60
RETRY_ATTEMPTS=3
```

## API Endpoints

### Health Checks
- `GET /health` - Basic health check
- `GET /health/detailed` - Detailed component health status

### Job Management
- `POST /jobs/full-index` - Start full document indexing
- `POST /jobs/incremental-index` - Start incremental indexing based on changes
- `POST /jobs/regenerate-embeddings` - Regenerate all embeddings
- `POST /jobs/update-missing-embeddings` - Generate embeddings for chunks without them
- `GET /jobs` - List jobs with filtering
- `GET /jobs/{job_id}` - Get job details and metrics
- `DELETE /jobs/{job_id}` - Cancel a running job

### Change Data Capture
- `POST /cdc/scan` - Scan SharePoint for document changes
- `GET /cdc/statistics` - Get change detection statistics

### Search
- `GET /search` - Search documents using vector similarity
  - Supports semantic and hybrid search modes
  - Account-based filtering
  - Configurable result count and similarity threshold

### Statistics
- `GET /statistics/system` - System-wide metrics
- `GET /statistics/pipeline` - Pipeline status and performance
- `GET /statistics/embeddings` - Embedding generation statistics

## Usage Examples

### Start Full Indexing
```bash
curl -X POST "http://localhost:8000/jobs/full-index" \
  -G -d "force_reprocess=true"
```

### Search Documents
```bash
curl -X GET "http://localhost:8000/search" \
  -G -d "query=contract terms" \
  -d "search_type=hybrid" \
  -d "top_k=10"
```

### Monitor Job Progress
```bash
curl -X GET "http://localhost:8000/jobs/your-job-id"
```

## Development

### Install Dependencies
```bash
pip install -r requirements.txt
pip install -e .
```

### Run Locally
```bash
python -m uvicorn src.indexer.main:app --reload --port 8000
```

### Run Tests
```bash
pytest tests/ -v
```

## Docker Deployment

### Build Image
```bash
docker build -t sharepoint-indexer .
```

### Run Container
```bash
docker run -p 8000:8000 \
  -e AZURE_OPENAI_ENDPOINT=your-endpoint \
  -e COSMOS_DB_ENDPOINT=your-endpoint \
  sharepoint-indexer
```

## Processing Workflows

### Full Indexing
1. Discover all SharePoint documents
2. Extract content using Document Intelligence
3. Apply chunking strategies
4. Generate vector embeddings
5. Index in Azure AI Search
6. Update processing metadata

### Incremental Indexing
1. Scan for document changes (CDC)
2. Process only new/modified files
3. Update existing embeddings if needed
4. Maintain index consistency

### Embedding Pipeline
1. Retrieve document chunks
2. Generate embeddings using Azure OpenAI
3. Validate embedding quality
4. Update vector store
5. Collect generation metrics

## Monitoring

The indexer provides comprehensive monitoring through:

- **Health endpoints** for service status
- **Job metrics** for processing performance
- **System statistics** for resource utilization
- **CDC statistics** for change detection efficiency
- **Embedding statistics** for ML pipeline health

## Security

- Azure Managed Identity for service authentication
- Account-based access control for search results
- Secure client configurations with proper authentication
- Input validation and sanitization
- Error handling without information disclosure

## Performance

- Asynchronous processing for scalability
- Batch operations for efficiency
- Connection pooling and resource management
- Progress tracking and optimization metrics
- Configurable concurrency limits

## Error Handling

- Comprehensive retry logic with exponential backoff
- Detailed error logging and monitoring
- Graceful degradation for partial failures
- Circuit breaker patterns for external services
- Recovery mechanisms for interrupted jobs Service

Background worker that ingests/refreshes searchable signals for the chatbot.

## Responsibilities
- Discover new/changed SharePoint PDFs (via inventory/ETag/LastModified)
- Extract text (Azure AI Document Intelligence), chunk, and store in vector store
- Sync structured schema hints (for SQL Agent) into `sql_schema`
- Track progress (`processed_files`) and emit telemetry
