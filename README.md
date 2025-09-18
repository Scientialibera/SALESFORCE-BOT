# Account Q\&A Bot – Project README

## Overview

The **Account Q&A Bot** answers questions about customer accounts by combining structured Sales Cloud data (Salesforce) and unstructured contract documents (SharePoint PDFs). **Important:** The bot does not directly connect to Salesforce or SharePoint - instead, it queries a **data lakehouse** where a dedicated data engineering team extracts, transforms, and loads data from these source systems.

It runs as a web SPA + backend Chat API hosted on **Azure Container Apps**, fronted by **Azure Front Door (WAF + CDN)** and **Azure API Management** for auth, throttling, and routing.

Data lands in **Microsoft Fabric** using **Dataflows Gen2** and Spark notebooks, following a **Medallion (Bronze/Silver/Gold)** pattern. The bot uses a **Planner-first agentic architecture** (Semantic Kernel style): the **Planner** is the only chat-facing component; it decides whether to call SQL/Graph tools and then composes the final answer with citations.

## Data Architecture

**Key Architectural Principle:** This chatbot operates on processed data, not live source systems:

- **SQL Agent** → Queries the **data lakehouse SQL endpoint** containing structured Salesforce data extracted by the data engineering team
- **Graph Agent** → Queries **Cosmos DB** containing relationship data populated from the lakehouse by the data engineering team  
- **Document Indexer** → Processes SharePoint document metadata from the lakehouse (not direct SharePoint access)

**Data Flow:**
1. **Data Engineering Team** extracts data from Salesforce and SharePoint using **Microsoft Fabric Dataflows Gen2**
2. Data lands in **Microsoft Fabric Lakehouse** following **Medallion (Bronze/Silver/Gold)** pattern
3. **Chatbot** queries the lakehouse SQL endpoint and Cosmos DB for answers
4. **Indexer** processes document content from lakehouse for vector search

```
┌─────────────┐    ┌─────────────┐
│ Salesforce  │    │ SharePoint  │
│   (CRM)     │    │ (Documents) │
└──────┬──────┘    └──────┬──────┘
       │                  │
       │ Data Engineering Team
       │ (Fabric Dataflows)
       ▼                  ▼
   ┌─────────────────────────────────┐
   │     Microsoft Fabric           │
   │        Lakehouse               │
   │ (Bronze/Silver/Gold Tables)    │
   └─────────┬───────────────────────┘
             │
    ┌────────┴────────┐
    ▼                 ▼
┌─────────┐      ┌─────────────┐
│Lakehouse│      │  Cosmos DB  │
│SQL      │      │  (Graph)    │
│Endpoint │      │             │
└────┬────┘      └──────┬──────┘
     │                  │
     │     Chatbot      │
     ▼                  ▼
┌─────────────────────────────────┐
│       Chat API                 │
│  ┌─────────┐  ┌─────────────┐   │
│  │SQL Agent│  │Graph Agent  │   │
│  └─────────┘  └─────────────┘   │
└─────────────────────────────────┘
```

## Goals

* Natural-language Q\&A over **Accounts, Opportunities, Products, Tasks**, and **Contracts**.
* Ground every answer in **verifiable sources** (tables/rows or document passages with URLs).
* Enforce **RBAC** based on the user’s identity (Azure Entra claims).
* Run on a secure, production-ready perimeter (Front Door WAF → APIM → private Container Apps).

---

## High-Level Architecture

**Sources**

* **Salesforce**: Account, Opportunity, Product, Task, User (for ownership).
* **SharePoint Online**: Contract PDFs per account folder.

**Fabric (Ingest & Lakehouse)**

* **Dataflows Gen2**

  * Salesforce Objects → **Bronze Delta tables** with **Incremental Refresh** on `LastModifiedDate/SystemModstamp`.
  * SharePoint file **inventory (metadata + URLs)** → Bronze; PDFs optionally landed in Files.
* **Spark Notebooks**

  * Transform Salesforce to **Silver** (conformed schema, SCDs as needed).
  * Fetch new/changed PDFs by **ETag/LastModified**; extract text via **Azure AI Document Intelligence** → `contracts_text` (Silver) & chunked text for RAG.
* **Gold (optional)**

  * *Account 360* star schema for BI/metrics.

**Serving Layer**

* **Warehouse/Semantic Model (Direct Lake)** for structured queries.
* **Vector Store** (Azure AI Search or Cosmos DB NoSQL w/ vector index) for contract passage retrieval.
* *(Optional)* **Graph (Cosmos Gremlin)** for relationships/RBAC traversal if multi-hop reasoning is needed.

**App Plane**

* **Front Door (WAF)**: single hostname, two routes

  * `/*` → SPA origin (cache static assets, no-cache HTML)
  * `/api/*` → APIM (no cache)
* **API Management (APIM)**: `validate-jwt` (Entra), `rate-limit-by-key`, CORS, request/response transforms, `/api` base path.
* **Container Apps**

  * **Chat API** (Planner orchestrator) – **private ingress** in VNet.
  * **Indexer** – ingests/embeds contracts from Fabric Silver and updates the vector store.
* **Azure OpenAI** for LLM completion/embedding.
* **Application Insights** for end-to-end telemetry.

---

## Data Model (minimal)

**Tables**

* `account(id, name, owner_user_id, created_at, updated_at)`
* `opportunity(id, account_id, owner_user_id, name, stage, amount, close_date, created_at, updated_at)`
* `product(id, name, sku, is_active)`
* `opportunity_product(id, opportunity_id, product_id, quantity, unit_price, total_price)`
* `task(id, account_id?, opportunity_id?, assigned_user_id, subject, status, due_date, created_at, updated_at)`
* `user(id, email UNIQUE, display_name, role, is_active)`
* `contracts_text(file_id, account_id, file_name, file_text, file_summary, etag, last_modified, owner_email)`

**Key relationships**

* Account 1→\* Opportunity (`opportunity.account_id`)
* Account 1→\* Task (`task.account_id` nullable)
* Account 1→\* Contracts (`contracts_text.account_id`)
* User 1→\* Account/Opportunity/Task by owner/assignee FKs

RBAC is enforced with `user.email`/`user.id` → allowlisted accounts and row filters.

┌─────────────┐    ┌─────────────┐
│ Salesforce  │    │ SharePoint  │
│   (CRM)     │    │ (Documents) │
└──────┬──────┘    └──────┬──────┘
       │                  │
       │ Data Engineering Team
       │ (Fabric Dataflows)
       ▼                  ▼
   ┌─────────────────────────────────┐
   │     Microsoft Fabric           │
   │        Lakehouse               │
   │ (Bronze/Silver/Gold Tables)    │
   └─────────┬───────────────────────┘
             │
    ┌────────┴────────┐
    ▼                 ▼
┌─────────┐      ┌─────────────┐
│Lakehouse│      │  Cosmos DB  │
│SQL      │      │  (Graph)    │
│Endpoint │      │             │
└────┬────┘      └──────┬──────┘
     │                  │
     │     Chatbot      │
     ▼                  ▼
┌─────────────────────────────────┐
│       Chat API                 │
│  ┌─────────┐  ┌─────────────┐   │
│  │SQL Agent│  │Graph Agent  │   │
│  └─────────┘  └─────────────┘   │
└─────────────────────────────────┘
---

## Bot Runtime (Planner-first)

### Conversation Flow (summary)

1. **SPA → Chat API**: user text + `chatId` + bearer token.
2. **Auth & History**: API validates token → builds `rbacContext`; loads chat history from cache.
3. **Planner** (single chat-facing LLM):

   * Chooses **No-Tool**, **SQL**, **Graph**, or **Hybrid** plan.
   * For SQL/Graph plans, a pre-invoke **Account Resolver** runs:

     * LLM extracts candidate account name from the query.
     * Service fetches RBAC-scoped account names from SQL.
     * Computes **cosine similarity** (embeddings) and returns `{account_id, account_name}`.
     * If confidence is low, planner asks the user to disambiguate.
   * Executes tools, merges results, composes the answer, and includes **citations**.
4. **Answer** is returned to SPA; history and plan details are appended to cache.
5. **Feedback**: SPA sends 👍/👎 (optional comment) → stored in cache for ranking/evals.

### Tooling Responsibilities

* **SQL Agent**: Executes parameterized T-SQL queries against the **lakehouse SQL endpoint** (not direct Salesforce). The lakehouse contains structured data extracted from Salesforce by the data engineering team. Injects **RBAC filters** (e.g., `WHERE account_id IN (...) AND owner_email = @user`).
* **Graph Agent**: Executes Gremlin traversals against **Cosmos DB** (not direct SharePoint). The graph database contains relationship data populated from the lakehouse by the data engineering team. Queries are scoped by RBAC edges/predicates.
* **Vector retrieval**: Account-scoped search over `contracts_text` chunks stored in the vector store. Document content is extracted from SharePoint by the data engineering team and processed by the indexer. Returns passages + SharePoint URLs for citations.

---

## Pipelines (Data Engineering Team Responsibility)

1. **Salesforce → Bronze** (Dataflows Gen2, incremental refresh) - **Data Engineering Team**
2. **SharePoint → Bronze** (inventory; URLs + metadata) - **Data Engineering Team**  
3. **PDF Processing → Silver** (Spark): fetch new files by ETag, extract with Doc Intelligence, produce `contracts_text` and chunks - **Data Engineering Team**
4. **Gold** (optional): Account 360 marts - **Data Engineering Team**
5. **Indexer** (Container App): embed new/changed chunks from lakehouse; update vector store; maintain `processed_files` table - **Chatbot Team**

**Note:** The chatbot team only manages the indexer (#5). All data extraction and transformation from source systems (Salesforce, SharePoint) is handled by the data engineering team using Fabric pipelines.

---

## SDKs & Identity (local vs cloud)

We use **official Microsoft SDKs** across the stack (Azure OpenAI, Cosmos DB, Azure AI Search, Storage/OneLake, Key Vault, Application Insights) and authenticate with **`DefaultAzureCredential`** to keep code the same in all environments.

**How it authenticates**

* **Local dev**: `DefaultAzureCredential` tries developer sign‑in sources in order (VS/VS Code, Azure CLI, Azure Developer CLI, env vars). After `az login`, your user token is used—no secrets needed.
* **Containers in Azure**: `DefaultAzureCredential` resolves to the **User‑Assigned Managed Identity (UAMI)** on the Container App. No keys are stored in app settings.
* **CI/CD**: Federated OIDC to the same UAMI (no client secrets). Pipelines request short‑lived tokens.

**Resource roles (RBAC only, no keys)**

* **Azure OpenAI**: *Cognitive Services OpenAI User* (inference) for the UAMI.
* **Cosmos DB (NoSQL)**: *Cosmos DB Built‑in Data Contributor* (or data‑plane role with least privilege).
* **Azure AI Search**: *Search Index Data Contributor/Reader* as needed.
* **Storage/OneLake**: *Storage Blob Data Reader/Contributor* as needed for notebooks/indexer.
* **Key Vault**: *Key Vault Secrets User* (only if we keep any secrets; prefer MI wherever possible).

**Configuration (env)**

* Endpoints/ids only, not secrets:

  * `AOAI_ENDPOINT`, `AOAI_DEPLOYMENT` (chat), `AOAI_EMBEDDING_DEPLOYMENT`
  * `COSMOS_ENDPOINT`, `COSMOS_DB`, `COSMOS_CONTAINER`
  * `SEARCH_ENDPOINT`, `SEARCH_INDEX`
  * `FABRIC_WAREHOUSE_ENDPOINT` or Lakehouse SQL endpoint DSN
* Optional SP fallback (for automation only): `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` (not used in app runtime; MI is primary).

**Guidelines**

* Disable key‑based auth on Cosmos/Search where possible; use **RBAC + AAD tokens**.
* Never check secrets into code or app settings. Use **Managed Identity**; if unavoidable, store secrets in **Key Vault**.
* Log the **credential type** at startup (e.g., "Using ManagedIdentityCredential") for diagnostics.

## Security & Networking

* **Front Door (WAF)** in front of SPA & APIM; managed OWASP rules.
* **APIM** validates Entra JWT; central CORS; throttling.
* **Container Apps**: **private** ingress; Managed Identity to reach data plane.
* **Private Endpoints**: Cosmos/AI Search, Storage/OneLake, Key Vault.
* **Key Vault** for secrets (if any); prefer Managed Identity.

---

## Local/Dev Setup (outline)

1. Create Azure resources: Front Door (Std/Prem), APIM, Container Apps env, Key Vault, App Insights, Storage, Azure OpenAI, chosen Vector Store.
2. Provision Fabric workspace, Lakehouse, Warehouse. Enable Dataflows Gen2 connectors.
3. Configure Entra App Registrations for SPA and API; set scopes/roles.
4. Deploy **Indexer** and **Chat API** containers; wire Managed Identity & settings.
5. Configure **Front Door routes** and **APIM** APIs/policies.
6. Run initial dataflows; execute notebooks to build Silver; run indexer once.

---

## Operations

* **Monitoring**: App Insights dashboards for SPA/API/APIM; APIM analytics (call volume, throttles); Front Door WAF logs.
* **Data refresh**: Dataflows scheduled (Salesforce IR, SharePoint inventory). Notebooks on a schedule or event-driven.
* **Backfills**: Re-run Silver notebook and indexer for re-embedding.
* **Schema changes**: Versioned views in Lakehouse/Warehouse; backward-compatible prompts.

---

## Roadmap / Options

* Add **Graph** model (Accounts, Documents, Topics, Similarity) for multi-hop questions.
* Add **Row-Level Security** at SQL endpoint to enforce RBAC inside the data tier.
* Add **evaluation harness** using stored feedback to tune prompts and retrieval.
* Expose bot in **Teams** using the same APIM-backed API.

---

## FAQ

**Do we need a Warehouse to query with SQL?**
No—Lakehouse has a SQL endpoint for reads. Use Warehouse if you need full T‑SQL DML/transactions.

**Can we do near real-time from Salesforce?**
Dataflows provide incremental refresh (pull). If you need push CDC, ingest Change Events via Event Hubs → Fabric/Eventstream.

**Where is contract text stored?**
In Fabric Silver (`contracts_text`). The graph holds relationships; the vector store holds embeddings; the bot cites back to SharePoint URLs.
