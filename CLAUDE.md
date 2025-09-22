# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Salesforce Account Q&A Bot built with a planner-first agentic architecture. The system operates on processed data from Microsoft Fabric lakehouse rather than live Salesforce/SharePoint connections.

**Key Components:**
- **Chatbot** (`chatbot/`): FastAPI-based chat API with planner orchestrator
- **Indexer** (`indexer/`): Document processing and vector store management
- **Scripts** (`scripts/`): Infrastructure and deployment automation

**Architecture Pattern:**
1. **Planner** parses user input and routes to appropriate agents
2. **Account Resolver** maps account names to IDs with confidence scoring
3. **SQL Agent** queries structured data from Fabric lakehouse SQL endpoint
4. **Graph Agent** queries relationship data from Cosmos DB and retrieves document content
5. **RBAC** enforcement occurs at the service layer, not in agents

## Development Commands

### Chatbot Service
```bash
cd chatbot/
# Install dependencies
pip install -r requirements.txt
pip install -e .[dev]  # For development dependencies

# Code formatting and linting
black src/
isort src/
flake8 src/
mypy src/

# Run tests
pytest

# Run locally
python -m chatbot.main
# or
uvicorn chatbot.main:app --reload
```

### Indexer Service
```bash
cd indexer/
# Install dependencies
pip install -r requirements.txt

# Run indexer
python -m indexer.main
```

## Code Architecture

### Data Flow
- **Source Systems**: Salesforce CRM + SharePoint Documents
- **Data Engineering**: Fabric Dataflows extract to Bronze/Silver/Gold lakehouse tables
- **Chatbot Layer**: Queries lakehouse SQL endpoint + Cosmos DB (not live systems)
- **RBAC**: Injected at SQL query construction, scoped by user identity

### Service Structure

**Chatbot (`chatbot/src/chatbot/`)**:
- `app.py`: Main FastAPI application and planner orchestration
- `agents/`: SQL and Graph agents for data retrieval
- `services/`: Business logic layer with RBAC enforcement
- `repositories/`: Data access layer for lakehouse and Cosmos DB
- `clients/`: Azure SDK clients (OpenAI, Cosmos, Search, etc.)
- `config/`: Environment configuration management
- `routes/`: API endpoint definitions
- `models/`: Pydantic data models

**Indexer (`indexer/src/indexer/`)**:
- `main.py`: Primary indexing orchestration
- `pipelines/`: Document processing pipelines
- `services/`: Vector embedding and storage services
- `repositories/`: Data access for lakehouse and vector store
- `clients/`: Azure SDK integrations

### Authentication & Security
- Uses `DefaultAzureCredential` for consistent auth across environments
- Local dev: Azure CLI login (`az login`)
- Azure: User-Assigned Managed Identity (UAMI)
- No client secrets stored in code or config
- RBAC enforced at SQL service layer via user identity claims

### Key Dependencies
- **FastAPI**: Web framework for chatbot API
- **Semantic Kernel**: LLM orchestration and planning
- **Azure SDK**: OpenAI, Cosmos DB, AI Search, Key Vault, Storage
- **pyodbc**: SQL connectivity to Fabric lakehouse
- **gremlinpython**: Cosmos DB Gremlin API for graph queries

## Environment Configuration

Required environment variables (endpoints only, no secrets):
- `AOAI_ENDPOINT`, `AOAI_DEPLOYMENT`, `AOAI_EMBEDDING_DEPLOYMENT`
- `COSMOS_ENDPOINT`, `COSMOS_DB`, `COSMOS_CONTAINER`
- `SEARCH_ENDPOINT`, `SEARCH_INDEX`
- `FABRIC_WAREHOUSE_ENDPOINT` (lakehouse SQL endpoint)

## Important Guidelines

### Code Style
- Never use emojis in code
- Avoid trivial or obvious inline comments
- Never use API keys, passwords, or placeholders in code
- Always write full, complete code implementations

### RBAC & Security
- RBAC enforcement happens at the service layer (SQL query construction)
- Agents receive pre-resolved account IDs and execute queries within scope
- Account resolver runs once per request with confidence scoring
- Dev mode disables RBAC for testing with dummy data

### Agent Responsibilities
- **SQL Agent**: Executes parameterized queries against lakehouse SQL endpoint
- **Graph Agent**: Executes Gremlin traversals against Cosmos DB, retrieves content from lakehouse
- **Account Resolver**: Maps fuzzy account names to exact IDs using embeddings similarity
- **Planner**: Routes requests, orchestrates tools, composes final responses with citations