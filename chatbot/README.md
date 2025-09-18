# Salesforce Account Q&A Chatbot

## Overview

The **Salesforce Account Q&A Chatbot** is an intelligent conversational AI system that answers questions about customer accounts by combining structured Salesforce data and unstructured contract documents. Built with **Semantic Kernel** and a **planner-first agentic architecture**, it provides natural language access to account information with proper source citations and enterprise-grade security.

## 🏗️ Architecture

### Core Components

- **Planner-First Agent**: Semantic Kernel orchestrator that decides when to call SQL or Graph agents
- **Account Resolution**: TF-IDF + embedding-based entity matching for accurate account identification
- **SQL Agent**: Queries structured Salesforce data from **Microsoft Fabric Lakehouse** (no direct CRM connection)
- **Graph Agent**: Traverses relationships using **Azure Cosmos DB Gremlin API**
- **Vector Search**: Contract document retrieval using Azure AI Search
- **RBAC Engine**: Role-based access control with row-level security

### Data Flow Architecture

```
Salesforce CRM → Microsoft Fabric (Data Pipeline) → Lakehouse/Warehouse
SharePoint Docs → Indexer → Graph DB (Cosmos Gremlin) + Vector Store (AI Search)
                              ↓
User Query → Chatbot → SQL Agent (Fabric) + Graph Agent (Cosmos) → Response
```

### Technology Stack

- **AI/ML**: Azure OpenAI (GPT-4o, text-embedding-3-small), Semantic Kernel 0.9.1b1
- **Backend**: FastAPI, Python 3.11+, Pydantic, structlog
- **Authentication**: Azure Active Directory, DefaultAzureCredential
- **Data Sources**: 
  - **Structured Data**: Microsoft Fabric Lakehouse (Salesforce data via pipeline)
  - **Graph Data**: Azure Cosmos DB Gremlin API (document relationships)
  - **Vector Data**: Azure AI Search (contract documents)
- **Deployment**: Docker, Azure Container Apps
- **Monitoring**: Application Insights, OpenTelemetry

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Docker
- Azure CLI (`az login` completed)
- Access to Azure OpenAI service
- Azure resources (see deployment section)

### Local Development

1. **Clone and Setup**
   ```bash
   cd chatbot
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Environment Configuration**
   ```bash
   cp .env.example .env
   # Edit .env with your Azure resource endpoints
   ```

3. **Download NLTK Data** (for TF-IDF processing)
   ```python
   import nltk
   nltk.download('punkt')
   nltk.download('stopwords')
   ```

4. **Run the Application**
   ```bash
   # Development server
   uvicorn src.chatbot.app:app --reload --host 0.0.0.0 --port 8000
   
   # Or using the main module
   python -m src.chatbot.main
   ```

5. **Test the API**
   ```bash
   # Health check
   curl http://localhost:8000/health
   
   # Chat endpoint (requires valid Bearer token)
   curl -X POST http://localhost:8000/api/chat \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"message": "Show me accounts for Microsoft", "chat_id": "test-123"}'
   ```

## 📁 Project Structure

```
chatbot/
├── src/chatbot/
│   ├── app.py                 # FastAPI application
│   ├── main.py               # Application entry point
│   ├── agents/
│   │   ├── graph_agent.py    # Gremlin graph queries
│   │   ├── sql_agent.py      # SQL queries against Fabric
│   │   ├── tool_definitions.py # Semantic Kernel function definitions
│   │   └── filters/
│   │       ├── account_resolver_filter.py  # TF-IDF entity matching
│   │       ├── invocation_filters.py       # Safety & logging filters
│   │       └── rbac_filter.py              # Access control filters
│   ├── clients/
│   │   ├── aoai_client.py    # Azure OpenAI integration
│   │   ├── cosmos_client.py  # Cosmos DB connections
│   │   └── gremlin_client.py # Gremlin graph client
│   ├── config/
│   │   └── settings.py       # Configuration management
│   ├── models/
│   │   ├── account.py        # Account data models
│   │   ├── message.py        # Chat message models
│   │   ├── plan.py           # Planner execution models
│   │   ├── rbac.py           # RBAC context models
│   │   ├── result.py         # Response models
│   │   └── user.py           # User models
│   ├── repositories/
│   │   ├── agent_functions_repository.py  # SK function definitions
│   │   ├── cache_repository.py           # Redis/memory cache
│   │   ├── chat_history_repository.py    # Conversation persistence
│   │   ├── feedback_repository.py        # User feedback storage
│   │   ├── prompts_repository.py         # System prompts
│   │   └── sql_schema_repository.py      # Database schema metadata
│   ├── routes/
│   │   ├── chat.py           # Chat API endpoints
│   │   └── health.py         # Health check endpoints
│   ├── services/
│   │   ├── account_resolver_service.py   # Entity resolution service
│   │   ├── cache_service.py              # Caching layer
│   │   ├── feedback_service.py           # Feedback processing
│   │   ├── graph_service.py              # Graph traversal service
│   │   ├── history_service.py            # Chat history management
│   │   ├── planner_service.py            # Semantic Kernel planner
│   │   ├── rbac_service.py               # Access control service
│   │   ├── retrieval_service.py          # Vector search service
│   │   ├── sql_service.py                # SQL query execution
│   │   └── telemetry_service.py          # Monitoring & analytics
│   └── utils/
│       └── embeddings.py     # Embedding utilities
├── requirements.txt          # Python dependencies
├── Dockerfile               # Container build definition
└── README.md               # This file
```

## 🔧 Configuration

### Environment Variables

Create a `.env` file based on `.env.example`:

```bash
# Core Application
APP_NAME=salesforce-chatbot
ENVIRONMENT=development
LOG_LEVEL=INFO

# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://your-aoai.openai.azure.com/
AZURE_OPENAI_API_VERSION=2024-02-15-preview
AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4o
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-small

# Azure Cosmos DB (SQL API for cache)
AZURE_COSMOS_ENDPOINT=https://your-cosmos.documents.azure.com:443/
AZURE_COSMOS_DATABASE=chatbot
AZURE_COSMOS_CACHE_CONTAINER=cache
AZURE_COSMOS_HISTORY_CONTAINER=chat_history
AZURE_COSMOS_FEEDBACK_CONTAINER=feedback

# Azure Cosmos DB (Gremlin API for graph)
AZURE_COSMOS_GREMLIN_ENDPOINT=your-cosmos-gremlin.gremlin.cosmos.azure.com
AZURE_COSMOS_GREMLIN_PORT=443
AZURE_COSMOS_GREMLIN_DATABASE=accounts
AZURE_COSMOS_GREMLIN_GRAPH=relationships

# Azure AI Search
AZURE_SEARCH_ENDPOINT=https://your-search.search.windows.net
AZURE_SEARCH_INDEX=contracts-index

# Microsoft Fabric / SQL Endpoint (Lakehouse - no direct Salesforce connection)
FABRIC_SQL_ENDPOINT=your-workspace.datawarehouse.fabric.microsoft.com
FABRIC_SQL_DATABASE=your_lakehouse

# Application Insights
APPLICATIONINSIGHTS_CONNECTION_STRING=InstrumentationKey=your-key;...

# Authentication
AZURE_AD_TENANT_ID=your-tenant-id
AZURE_AD_CLIENT_ID=your-client-id
# Note: Use Azure AD audience for JWT validation in production

# Cache Settings
CACHE_TTL_SECONDS=3600
CHAT_HISTORY_TTL_DAYS=30

# TF-IDF Settings
TFIDF_MIN_SIMILARITY=0.3
ACCOUNT_RESOLUTION_CONFIDENCE_THRESHOLD=0.8

# Rate Limiting
RATE_LIMIT_PER_MINUTE=60
RATE_LIMIT_BURST=10

# Safety Settings
MAX_TOKENS_PER_REQUEST=4000
ENABLE_SAFETY_FILTERS=true
```

## 🤖 AI Agent Architecture

### Planner-First Design

The chatbot uses a **planner-first agentic architecture** where a central Semantic Kernel planner orchestrates all interactions:

1. **User Query Analysis**: Planner analyzes user intent and determines required data sources
2. **Account Resolution**: TF-IDF + embedding-based entity matching resolves account names
3. **Tool Selection**: Planner chooses appropriate agents (SQL, Graph, or both)
4. **Execution**: Selected agents execute with RBAC-filtered results
5. **Response Synthesis**: Planner combines results with proper citations

### Account Resolution with TF-IDF

The system uses advanced TF-IDF vectorization for accurate account entity matching:

- **Text Preprocessing**: NLTK tokenization, stopword removal, stemming
- **TF-IDF Vectorization**: Scikit-learn with n-grams (1-3), sublinear scaling
- **Cosine Similarity**: Fast similarity computation with L2 normalization
- **RBAC Integration**: Results filtered by user's accessible accounts
- **Fallback Methods**: LLM extraction + embeddings as secondary approach

### Agent Responsibilities

**SQL Agent**
- Queries Microsoft Fabric Lakehouse SQL endpoint (no direct Salesforce connection)
- Handles structured Salesforce data ingested via data pipelines
- Injects RBAC filters automatically
- Supports complex aggregations and joins

**Graph Agent**
- Traverses relationships using Cosmos DB Gremlin API
- Discovers document and account connections
- Performs multi-hop reasoning across entities
- Enforces graph-level access control

**Vector Retrieval**
- Searches contract documents by account
- Returns relevant passages with SharePoint URLs
- Provides semantic similarity ranking
- Includes confidence scores

## 🔐 Security & RBAC

### Authentication Flow

1. **Client Authentication**: Azure AD JWT token validation
2. **User Context**: Extract user ID, roles, and permissions from claims
3. **RBAC Context**: Build user's accessible account scope
4. **Query Filtering**: Inject WHERE clauses based on user access
5. **Result Filtering**: Post-process results to ensure compliance

### Access Control Layers

- **API Level**: JWT validation and rate limiting
- **Service Level**: RBAC context enforcement
- **Data Level**: Row-level security filters
- **Response Level**: Citation filtering and sanitization

### Safety Filters

- **SQL Injection Prevention**: Pattern matching for dangerous SQL
- **Token Limits**: Prevent oversized requests
- **Content Policies**: Block unsafe or inappropriate content
- **Audit Logging**: Comprehensive telemetry for compliance

## 📊 Monitoring & Telemetry

### Metrics Tracked

- **Request Metrics**: Response times, error rates, token usage
- **User Analytics**: Query patterns, account access, feedback scores
- **Agent Performance**: Tool selection accuracy, resolution confidence
- **System Health**: Resource utilization, cache hit rates, dependency status

### Observability Stack

- **Application Insights**: Centralized logging and metrics
- **OpenTelemetry**: Distributed tracing across components
- **Structured Logging**: Consistent log format with correlation IDs
- **Health Checks**: Comprehensive dependency monitoring

## 🐳 Deployment

### Docker Build

```bash
# Build the container
docker build -t salesforce-chatbot:latest .

# Run locally
docker run -p 8000:8000 --env-file .env salesforce-chatbot:latest
```

### Azure Container Apps

```bash
# Create Container App (using Azure CLI)
az containerapp create \
  --name salesforce-chatbot \
  --resource-group your-rg \
  --environment your-container-env \
  --image your-registry.azurecr.io/salesforce-chatbot:latest \
  --target-port 8000 \
  --ingress external \
  --min-replicas 1 \
  --max-replicas 10
```

### Environment-Specific Configuration

**Development**
- Single replica, local Azure resources
- Verbose logging, debug mode enabled
- Mock data for testing

**Staging**
- Auto-scaling enabled (1-3 replicas)
- Production Azure resources with test data
- Full monitoring without sensitive data

**Production**
- Auto-scaling (2-10 replicas)
- High availability across zones
- Enhanced security, audit logging
- Performance monitoring and alerting

## 🧪 Testing

### Unit Tests

```bash
# Run unit tests
python -m pytest tests/ -v

# With coverage
python -m pytest tests/ --cov=src/chatbot --cov-report=html
```

### Integration Tests

```bash
# Test with real Azure resources
python -m pytest tests/integration/ --env=staging
```

### Load Testing

```bash
# Using Apache Bench
ab -n 1000 -c 10 -H "Authorization: Bearer TOKEN" \
   http://localhost:8000/api/chat

# Or use Azure Load Testing for comprehensive testing
```

## 🔧 Development Guide

### Adding New Agents

1. **Create Agent Class**: Implement in `agents/` following existing patterns
2. **Define Functions**: Add Semantic Kernel function definitions
3. **Update Planner**: Register new tools in planner configuration
4. **Add Tests**: Unit and integration tests for the new agent
5. **Update Documentation**: Add usage examples and configuration

### Custom Filters

1. **Implement Filter**: Create class in `agents/filters/`
2. **Register Filter**: Add to filter chain in `invocation_filters.py`
3. **Configure Order**: Ensure proper execution sequence
4. **Test Thoroughly**: Verify security and performance impact

### Extending RBAC

1. **Update Models**: Modify RBAC models in `models/rbac.py`
2. **Service Integration**: Update `rbac_service.py` with new logic
3. **Filter Updates**: Modify filters to use new permissions
4. **Migration**: Plan data migration if schema changes

## 🤝 Contributing

### Code Style

- **PEP 8**: Follow Python style guidelines
- **Type Hints**: Use comprehensive type annotations
- **Docstrings**: Document all public functions and classes
- **Logging**: Use structured logging with proper levels

### Pull Request Process

1. **Branch**: Create feature branch from `main`
2. **Develop**: Implement changes with tests
3. **Test**: Ensure all tests pass and coverage remains high
4. **Document**: Update README and inline documentation
5. **Review**: Submit PR with clear description

### Security Guidelines

- **No Secrets**: Never commit secrets or credentials
- **Managed Identity**: Use Azure Managed Identity whenever possible
- **Input Validation**: Validate and sanitize all user inputs
- **Error Handling**: Don't leak sensitive information in errors

## 📚 API Documentation

### Chat Endpoint

```http
POST /api/chat
Authorization: Bearer {jwt_token}
Content-Type: application/json

{
  "message": "Show me opportunities for Microsoft",
  "chat_id": "user-session-123",
  "context": {
    "account_focus": "microsoft-corp",
    "time_range": "2024-Q1"
  }
}
```

### Response Format

```json
{
  "response": "I found 5 opportunities for Microsoft Corporation...",
  "citations": [
    {
      "source": "sql",
      "table": "opportunities",
      "query": "SELECT * FROM opportunities WHERE account_name = 'Microsoft'",
      "confidence": 0.95
    }
  ],
  "metadata": {
    "tokens_used": 1250,
    "response_time_ms": 2300,
    "plan_type": "sql_agent",
    "account_resolution": {
      "resolved_accounts": ["Microsoft Corporation"],
      "confidence": 0.92,
      "method": "tfidf"
    }
  }
}
```

## 🆘 Troubleshooting

### Common Issues

**Authentication Failures**
- Verify `az login` status
- Check Azure AD app registration
- Ensure Managed Identity permissions

**TF-IDF Errors**
- Verify NLTK data downloads
- Check account corpus availability
- Review preprocessing logs

**Performance Issues**
- Monitor token usage and limits
- Check cache hit rates
- Review query complexity

**Vector Search Problems**
- Verify Azure AI Search connectivity
- Check index schema and data
- Review embedding deployment

### Debug Mode

```bash
# Enable verbose logging
export LOG_LEVEL=DEBUG

# Run with debug options
python -m src.chatbot.main --debug
```

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙋‍♂️ Support

For questions or issues:

1. **Documentation**: Check this README and inline documentation
2. **Issues**: Create GitHub issue with detailed description
3. **Security**: Report security issues privately to the team
4. **Features**: Discuss new features in GitHub discussions

---

**Built with ❤️ using Azure AI and Semantic Kernel**