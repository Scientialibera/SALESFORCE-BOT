
param(
	[string]$ResourceGroup
)

# This script merges `.env.example` into `.env` and performs best-effort Azure discovery
# when a resource group is supplied. Discovery requires the Azure CLI (`az`) and an
# authenticated principal. Management/provisioning operations are executed via AAD/az and
# do NOT use account keys. If discovery or provisioning fails due to permission limits,
# set the required environment variables manually or have an administrator pre-create
# the Cosmos DB resources.

function Read-EnvFile {
	param([string]$path)
	$h = @{}
	if (Test-Path $path) {
		Get-Content $path | ForEach-Object {
			if ($_ -match '^(\s*#|\s*$)') { return }
			$parts = $_ -split '=', 2
			if ($parts.Length -eq 2) { $h[$parts[0].Trim()] = $parts[1].Trim() }
		}
	}
	return $h
}

function Write-EnvFile {
	param([string]$path, [hashtable]$env)
	$orderedKeys = @(
		'DEV_MODE','AOAI_ENDPOINT','AOAI_CHAT_DEPLOYMENT','AOAI_EMBEDDING_DEPLOYMENT',
		'AZURE_OPENAI_ENDPOINT','AZURE_OPENAI_API_VERSION','AZURE_OPENAI_CHAT_DEPLOYMENT_NAME','AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME',
		'COSMOS_ENDPOINT','COSMOS_DATABASE_NAME','COSMOS_CHAT_CONTAINER','COSMOS_CACHE_CONTAINER','COSMOS_FEEDBACK_CONTAINER','COSMOS_PROCESSED_FILES_CONTAINER','COSMOS_PROMPTS_CONTAINER','COSMOS_SQL_SCHEMA_CONTAINER','COSMOS_ACCOUNT_RESOLVER_CONTAINER','COSMOS_AGENT_FUNCTIONS_CONTAINER',
		'AZURE_COSMOS_ENDPOINT','AZURE_COSMOS_DATABASE','AZURE_COSMOS_HISTORY_CONTAINER','AZURE_COSMOS_FEEDBACK_CONTAINER','AZURE_COSMOS_GREMLIN_ENDPOINT','AZURE_COSMOS_GREMLIN_DATABASE','AZURE_COSMOS_GREMLIN_GRAPH','AZURE_COSMOS_GREMLIN_PORT',
		'GREMLIN_ENDPOINT','GREMLIN_USERNAME',
		'FABRIC_SQL_ENDPOINT','FABRIC_SQL_DATABASE','FABRIC_WORKSPACE_ID',
		'AZURE_SEARCH_ENDPOINT','AZURE_SEARCH_INDEX',
		'APPLICATIONINSIGHTS_CONNECTION_STRING',
		'CONTAINER_APP_RESOURCE_GROUP','CONTAINER_APP_ENVIRONMENT','CONTAINER_APP_SUBSCRIPTION_ID',
		'AZURE_AD_TENANT_ID'
	)
	$lines = @()
	foreach ($k in $orderedKeys) {
		if ($env.ContainsKey($k)) { $lines += "$k=$($env[$k])" }
	}
	foreach ($k in $env.Keys) {
		if (-not ($orderedKeys -contains $k)) { $lines += "$k=$($env[$k])" }
	}
	Set-Content -Path $path -Value ($lines -join "`n") -Encoding UTF8
}

# Merge .env.example into .env, preserving existing values and adding missing ones
$envPath = Join-Path -Path (Get-Location) -ChildPath ".env"
$examplePath = Join-Path -Path (Get-Location) -ChildPath ".env.example"

Write-Output "Merging .env.example into .env..."

# Read existing envs
$envVars = Read-EnvFile -path $envPath
$exampleVars = Read-EnvFile -path $examplePath

# Add missing example vars to envVars
foreach ($key in $exampleVars.Keys) {
	if (-not $envVars.ContainsKey($key)) {
		$envVars[$key] = $exampleVars[$key]
	}
}

# Attempt to auto-detect resource group if not provided via parameter
if (-not $ResourceGroup) {
	try {
		if ($envVars.ContainsKey('COSMOS_ENDPOINT') -and $envVars['COSMOS_ENDPOINT']) {
			$cosEnd = $envVars['COSMOS_ENDPOINT']
			$acct = $cosEnd.Replace('https://','') -split '\.' | Select-Object -First 1
			if ($acct) {
				Write-Output "Attempting to auto-detect resource group for Cosmos account: $acct"
				try {
					$lookup = az resource list --resource-type 'Microsoft.DocumentDB/databaseAccounts' --query "[?contains(name, `'$acct'`)]" -o json 2>$null | ConvertFrom-Json
					if ($lookup -and $lookup.Length -gt 0 -and $lookup[0].resourceGroup) {
						$ResourceGroup = $lookup[0].resourceGroup
						Write-Output "Auto-detected resource group: $ResourceGroup"
					}
				} catch {
					Write-Warning "az lookup failed while auto-detecting resource group: $_"
				}
			}
		}
	} catch {
		# noop - best-effort only
	}
}

# If a resource group is provided, attempt to discover AOAI/Cosmos endpoints and deployment names
if ($ResourceGroup) {
	try {
		az account show > $null 2>&1
	} catch {
		Write-Warning "Azure CLI not available or not logged in. Skipping azure discovery."
		$ResourceGroup = $null
	}
}

if ($ResourceGroup) {
	Write-Output "Attempting Azure resource discovery in resource group: $ResourceGroup"
	# Discover cognitive accounts
	$cogs = az resource list -g $ResourceGroup --query "[?type=='Microsoft.CognitiveServices/accounts']" -o json | ConvertFrom-Json
	$foundAoai = $null
	foreach ($c in $cogs) {
		if ($c.Kind -and $c.Kind -match 'OpenAI') { $foundAoai = $c; break }
		if ($c.Name -and $c.Name -match 'openai|aoai|open-ai|aoai') { $foundAoai = $c; break }
	}

	if ($foundAoai) {
		$aoaiName = $foundAoai.name
		$aoaiEndpoint = "https://$($aoaiName).cognitiveservices.azure.com"
		Write-Output "Detected Azure OpenAI account: $aoaiName -> $aoaiEndpoint"
		$envVars['AOAI_ENDPOINT'] = $aoaiEndpoint

		# Attempt to list deployments via az openai, else fallback to management REST
		$deployments = $null
		try {
			Write-Output "Attempting to list deployments via 'az openai deployment list'..."
			$raw = az openai deployment list --resource-group $ResourceGroup --resource-name $aoaiName -o json 2>$null
			if ($raw) { $deployments = $raw | ConvertFrom-Json }
		} catch {
			Write-Output "'az openai' not available; trying REST fallback."
		}

		if (-not $deployments) {
			try {
				$sub = (az account show -o json | ConvertFrom-Json).id
				$api = "https://management.azure.com/subscriptions/$sub/resourceGroups/$ResourceGroup/providers/Microsoft.CognitiveServices/accounts/$aoaiName/openai/deployments?api-version=2022-12-01"
				$raw = az rest --method get --uri $api -o json 2>$null
				if ($raw) { $resp = $raw | ConvertFrom-Json; if ($resp.value) { $deployments = $resp.value } }
			} catch {
				Write-Warning "Failed to query deployments via REST fallback: $_"
			}
		}

		$chatDeployment = $null
		$embedDeployment = $null
		if ($deployments) {
			foreach ($d in $deployments) {
				$dName = $d.name
				$model = $null
				if ($d.model) { $model = $d.model }
				elseif ($d.properties -and $d.properties.model) { $model = $d.properties.model }
				if (-not $model) { continue }
				$lm = $model.ToString().ToLower()
				if (-not $chatDeployment -and ($lm -match 'gpt' -or $lm -match 'chat' -or $lm -match 'turbo')) { $chatDeployment = $dName }
				if (-not $embedDeployment -and ($lm -match 'embed' -or $lm -match 'text-embedding')) { $embedDeployment = $dName }
				if ($chatDeployment -and $embedDeployment) { break }
			}
		}

		if ($chatDeployment) { $envVars['AOAI_CHAT_DEPLOYMENT'] = $chatDeployment; Write-Output "Detected chat deployment: $chatDeployment" } 
		elseif (-not $envVars.ContainsKey('AOAI_CHAT_DEPLOYMENT')) { $envVars['AOAI_CHAT_DEPLOYMENT'] = 'chat-deployment'; Write-Warning "No chat deployment detected; using placeholder 'chat-deployment'" }

		if ($embedDeployment) { $envVars['AOAI_EMBEDDING_DEPLOYMENT'] = $embedDeployment; Write-Output "Detected embedding deployment: $embedDeployment" } 
		elseif (-not $envVars.ContainsKey('AOAI_EMBEDDING_DEPLOYMENT')) { $envVars['AOAI_EMBEDDING_DEPLOYMENT'] = 'embedding-deployment'; Write-Warning "No embedding deployment detected; using placeholder 'embedding-deployment'" }

		# If we still have placeholders, prefer any existing AZURE_OPENAI_* keys found in the merged env
		$altChatKeys = @('AZURE_OPENAI_CHAT_DEPLOYMENT','AZURE_OPENAI_CHAT_DEPLOYMENT_NAME','AZURE_OPENAI_CHAT_DEPLOYMENTNAME','AZURE_OPENAI_CHAT_DEPLOYMENT')
		foreach ($k in $altChatKeys) {
			if ($envVars.ContainsKey($k) -and $envVars[$k] -and $envVars[$k] -ne 'chat-deployment' -and ($envVars['AOAI_CHAT_DEPLOYMENT'] -eq 'chat-deployment' -or -not $envVars['AOAI_CHAT_DEPLOYMENT'])) {
				$envVars['AOAI_CHAT_DEPLOYMENT'] = $envVars[$k]
				Write-Output "Using existing $k -> $($envVars[$k]) for AOAI_CHAT_DEPLOYMENT"
				break
			}
		}

		$altEmbedKeys = @('AZURE_OPENAI_EMBEDDING_DEPLOYMENT','AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME','AZURE_OPENAI_EMBEDDING_DEPLOYMENTNAME','AZURE_OPENAI_EMBEDDING_DEPLOYMENT')
		foreach ($k in $altEmbedKeys) {
			if ($envVars.ContainsKey($k) -and $envVars[$k] -and $envVars[$k] -ne 'embedding-deployment' -and ($envVars['AOAI_EMBEDDING_DEPLOYMENT'] -eq 'embedding-deployment' -or -not $envVars['AOAI_EMBEDDING_DEPLOYMENT'])) {
				$envVars['AOAI_EMBEDDING_DEPLOYMENT'] = $envVars[$k]
				Write-Output "Using existing $k -> $($envVars[$k]) for AOAI_EMBEDDING_DEPLOYMENT"
				break
			}
		}

		# Set AZURE_OPENAI_ENDPOINT from AOAI_ENDPOINT
		if (-not $envVars.ContainsKey('AZURE_OPENAI_ENDPOINT') -or $envVars['AZURE_OPENAI_ENDPOINT'] -match 'your') {
			$envVars['AZURE_OPENAI_ENDPOINT'] = $aoaiEndpoint
		}
	} else {
		Write-Warning "No Azure OpenAI account detected in RG $ResourceGroup"
	}

	# Persist the resource group into the merged env so other scripts can use it
	$envVars['CONTAINER_APP_RESOURCE_GROUP'] = $ResourceGroup

	# Discover Cosmos DB
	$cosmos = az resource list -g $ResourceGroup --query "[?type=='Microsoft.DocumentDB/databaseAccounts']" -o json | ConvertFrom-Json
	if ($cosmos -and $cosmos.Length -gt 0) {
		$cos = $cosmos[0]
		$cosmosName = $cos.name
		$cosmosEndpoint = "https://$($cosmosName).documents.azure.com:443/"
		Write-Output "Detected Cosmos DB account: $cosmosName -> $cosmosEndpoint"
		$envVars['COSMOS_ENDPOINT'] = $cosmosEndpoint
		if (-not $envVars.ContainsKey('COSMOS_DATABASE_NAME')) { $envVars['COSMOS_DATABASE_NAME'] = 'appdb' }
	} else {
		Write-Warning "No Cosmos DB account detected in RG $ResourceGroup"
	}

	# Attempt to detect Gremlin/graph endpoint
	try {
		$allRes = az resource list -g $ResourceGroup -o json | ConvertFrom-Json
		$gremlinRes = $allRes | Where-Object { $_.Name -match '(?i)gremlin|graph' }
		if ($gremlinRes -and $gremlinRes.Length -gt 0) {
			$g = $gremlinRes[0]
			$gremlinEndpoint = "https://$($g.Name).gremlin.cosmos.azure.com:443/"
			Write-Output "Detected Gremlin-ish resource: $($g.Name) -> $gremlinEndpoint"
			$envVars['GREMLIN_ENDPOINT'] = $gremlinEndpoint
		}
	} catch {
		Write-Warning "Failed to detect gremlin resource: $_"
	}

	# Detect Application Insights
	try {
		$appInsights = az resource list -g $ResourceGroup --query "[?type=='Microsoft.Insights/components']" -o json | ConvertFrom-Json
		if ($appInsights -and $appInsights.Length -gt 0) {
			$ai = $appInsights[0]
			$aiName = $ai.name
			$region = $ai.location
			$connString = "InstrumentationKey=$($ai.properties.InstrumentationKey);IngestionEndpoint=https://$region.in.applicationinsights.azure.com/"
			Write-Output "Detected Application Insights: $aiName -> $connString"
			$envVars['APPLICATIONINSIGHTS_CONNECTION_STRING'] = $connString
		}
	} catch {
		Write-Warning "Failed to detect Application Insights: $_"
	}

	# Detect Azure Search
	try {
		$searchServices = az resource list -g $ResourceGroup --query "[?type=='Microsoft.Search/searchServices']" -o json | ConvertFrom-Json
		if ($searchServices -and $searchServices.Length -gt 0) {
			$search = $searchServices[0]
			$searchName = $search.name
			$searchEndpoint = "https://$searchName.search.windows.net"
			Write-Output "Detected Azure Search: $searchName -> $searchEndpoint"
			$envVars['AZURE_SEARCH_ENDPOINT'] = $searchEndpoint
			if (-not $envVars.ContainsKey('AZURE_SEARCH_INDEX')) { $envVars['AZURE_SEARCH_INDEX'] = 'contracts-index' }
		}
	} catch {
		Write-Warning "Failed to detect Azure Search: $_"
	}

	# Detect Power BI Workspace (if any, but hard to query via az)
	# For now, skip or set placeholder

	# Detect Fabric Workspace
	try {
		$fabricWorkspaces = az resource list -g $ResourceGroup --query "[?type=='Microsoft.Fabric/workspaces']" -o json | ConvertFrom-Json
		if ($fabricWorkspaces -and $fabricWorkspaces.Length -gt 0) {
			$fw = $fabricWorkspaces[0]
			$workspaceId = $fw.name
			$fabricEndpoint = "https://$workspaceId.datawarehouse.fabric.microsoft.com"
			Write-Output "Detected Fabric Workspace: $workspaceId -> $fabricEndpoint"
			$envVars['FABRIC_WORKSPACE_ID'] = $workspaceId
			$envVars['FABRIC_SQL_ENDPOINT'] = $fabricEndpoint
			if (-not $envVars.ContainsKey('FABRIC_SQL_DATABASE')) { $envVars['FABRIC_SQL_DATABASE'] = 'lakehouse_db' }
		}
	} catch {
		Write-Warning "Failed to detect Fabric Workspace: $_"
	}
}

# Set default values for variables that are empty or placeholders
$defaults = @{
    'COSMOS_DATABASE_NAME' = 'appdb'
    'COSMOS_CHAT_CONTAINER' = 'chat_history'
    'COSMOS_CACHE_CONTAINER' = 'cache'
    'COSMOS_FEEDBACK_CONTAINER' = 'feedback'
    'COSMOS_PROCESSED_FILES_CONTAINER' = 'processed_files'
    'COSMOS_PROMPTS_CONTAINER' = 'prompts'
    'COSMOS_SQL_SCHEMA_CONTAINER' = 'sql_schema'
    'COSMOS_ACCOUNT_RESOLVER_CONTAINER' = 'account_resolver'
    'COSMOS_AGENT_FUNCTIONS_CONTAINER' = 'agent_functions'
    'AZURE_COSMOS_DATABASE' = 'chatbot'
    'AZURE_COSMOS_HISTORY_CONTAINER' = 'chat_history'
    'AZURE_COSMOS_FEEDBACK_CONTAINER' = 'feedback'
    'AZURE_COSMOS_GREMLIN_DATABASE' = 'graphdb'
    'AZURE_COSMOS_GREMLIN_GRAPH' = 'relationships'
    'AZURE_COSMOS_GREMLIN_PORT' = '443'
    'APP_LOG_LEVEL' = 'INFO'
    'DEV_ENABLE_SWAGGER' = 'true'
    'SQL_CONNECTION_TIMEOUT_SECONDS' = '30'
    'GRAPH_AGENT_MAX_TRAVERSAL_DEPTH' = '5'
    'GREMLIN_GRAPH_NAME' = 'account_graph'
    'AZURE_OPENAI_TEMPERATURE' = '0.7'
    'SQL_MAX_ROWS' = '1000'
    'AZURE_OPENAI_PRESENCE_PENALTY' = '0.0'
    'RBAC_ENFORCE_RBAC' = 'false'
    'SECURITY_JWT_SECRET_KEY' = 'dev-secret'
    'SHAREPOINT_CLIENT_ID' = 'your-sharepoint-app-id'
    'SQL_QUERY_TIMEOUT_SECONDS' = '30'
    'AZURE_OPENAI_FREQUENCY_PENALTY' = '0.0'
    'SECURITY_ACCESS_TOKEN_EXPIRE_MINUTES' = '60'
    'POWERBI_CLIENT_ID' = 'your-powerbi-app-id'
    'HEALTH_CHECK_OPENAI_ENABLED' = 'true'
    'HYBRID_AGENT_CONFIDENCE_THRESHOLD' = '0.8'
    'RBAC_CACHE_TTL_MINUTES' = '30'
    'GRAPH_AGENT_QUERY_TIMEOUT_SECONDS' = '30'
    'TFIDF_MIN_SIMILARITY' = '0.3'
    'RATE_LIMIT_ENABLED' = 'true'
    'SK_MAX_TOKENS' = '4000'
    'DEV_ENABLE_DEBUG_ROUTES' = 'false'
    'SQL_ENCRYPT' = 'true'
    'ACCOUNT_RESOLUTION_CONFIDENCE_THRESHOLD' = '0.8'
    'TELEMETRY_SAMPLING_RATE' = '0.1'
    'APP_VERSION' = '1.0.0'
    'TELEMETRY_ENABLE_TRACING' = 'true'
    'SQL_AGENT_MAX_QUERY_COMPLEXITY' = 'high'
    'RATE_LIMIT_BURST_SIZE' = '10'
    'CACHE_MAX_SIZE_MB' = '100'
    'ENABLE_QUERY_LOGGING' = 'true'
    'CHAT_HISTORY_TTL_DAYS' = '30'
    'COSMOS_DB_DATABASE_NAME' = 'salesforce_chatbot'
    'HEALTH_CHECK_COSMOS_ENABLED' = 'true'
    'SQL_AGENT_NAME' = 'sql_data_agent'
    'FEATURE_ENABLE_GRAPH_QUERIES' = 'true'
    'APP_ENVIRONMENT' = 'production'
    'DYNAMICS_365_CLIENT_ID' = 'your-dynamics-app-id'
    'RATE_LIMIT_BURST' = '10'
    'AZURE_COSMOS_GREMLIN_ENDPOINT' = 'your-cosmos-gremlin.gremlin.cosmos.azure.com'
    'SQL_AGENT_MAX_ROWS_RETURNED' = '1000'
    'HEALTH_CHECK_GREMLIN_ENABLED' = 'true'
    'SQL_DRIVER' = 'ODBC Driver 18 for SQL Server'
    'COSMOS_CONTRACTS_TEXT_CONTAINER' = 'contracts_text'
    'RBAC_JWT_AUDIENCE' = 'your-application-id'
    'APP_NAME' = 'Salesforce Chatbot'
    'RBAC_ADMIN_ROLES' = 'Global Administrator,Application Administrator'
    'MOCK_COSMOS_GREMLIN' = 'false'
    'VECTOR_SEARCH_TOP_K' = '5'
    'RBAC_DEFAULT_ROLE' = 'User'
    'DOCKER_REGISTRY' = 'your-registry.azurecr.io'
    'COSMOS_DB_REQUEST_TIMEOUT_SECONDS' = '30'
    'GREMLIN_MAX_RETRY_ATTEMPTS' = '3'
    'ACCOUNT_RESOLVER_CONFIDENCE_THRESHOLD' = '0.8'
    'RBAC_ENABLED' = 'true'
    'COSMOS_DB_MAX_RETRY_ATTEMPTS' = '3'
    'HYBRID_AGENT_NAME' = 'hybrid_reasoning_agent'
    'MOCK_FABRIC_SQL' = 'false'
    'TELEMETRY_ENABLE_LOGGING' = 'true'
    'COSMOS_DB_CHAT_HISTORY_CONTAINER' = 'chat_history'
    'SECURITY_ALLOWED_HOSTS' = 'your-domain.com,*.your-domain.com'
    'DOCKER_IMAGE_NAME' = 'salesforce-chatbot'
    'SQL_MAX_POOL_SIZE' = '20'
    'TELEMETRY_SERVICE_VERSION' = '1.0.0'
    'FEATURE_ENABLE_HYBRID_MODE' = 'true'
    'SK_TEMPERATURE' = '0.1'
    'APP_CORS_ALLOW_CREDENTIALS' = 'true'
    'RATE_LIMIT_REQUESTS_PER_MINUTE' = '60'
    'APP_DEBUG' = 'false'
    'HEALTH_CHECK_TIMEOUT_SECONDS' = '5'
    'HEALTH_CHECK_SQL_ENABLED' = 'true'
    'GREMLIN_REQUEST_TIMEOUT_SECONDS' = '30'
    'COSMOS_DB_AGENT_FUNCTIONS_CONTAINER' = 'agent_functions'
    'APP_MAX_REQUEST_SIZE_MB' = '10'
    'RBAC_MANAGER_ROLES' = 'Sales Manager,Account Manager'
    'ACCOUNT_RESOLVER_MAX_SUGGESTIONS' = '3'
    'ENABLE_SAFETY_FILTERS' = 'true'
    'AZURE_OPENAI_MAX_TOKENS' = '4000'
    'AZURE_OPENAI_TOP_P' = '0.9'
    'CACHE_DEFAULT_TTL_SECONDS' = '3600'
    'GREMLIN_CONNECTION_POOL_SIZE' = '10'
    'DEBUG_MODE' = 'false'
    'CACHE_EMBEDDINGS_TTL_SECONDS' = '86400'
    'CACHE_SCHEMA_TTL_SECONDS' = '7200'
    'CACHE_PROMPTS_TTL_SECONDS' = '1800'
    'TELEMETRY_ENABLE_METRICS' = 'true'
    'FEATURE_ENABLE_FEEDBACK' = 'true'
    'FEATURE_ENABLE_ANALYTICS' = 'true'
    'FEATURE_ENABLE_CACHING' = 'true'
    'FEATURE_ENABLE_ACCOUNT_RESOLUTION' = 'true'
    'FEATURE_ENABLE_SQL_QUERIES' = 'true'
    'APP_CORS_ORIGINS' = 'https://your-frontend-domain.com,https://your-portal.com'
    'SECURITY_SECRET_KEY' = 'your-super-secret-key-change-this-in-production'
    'SECURITY_ALGORITHM' = 'HS256'
    'SECURITY_HTTPS_ONLY' = 'true'
    'SK_PLANNER_TYPE' = 'sequential'
    'SK_MAX_PLAN_STEPS' = '10'
    'SK_PLAN_TIMEOUT_SECONDS' = '120'
    'SK_FUNCTION_TIMEOUT_SECONDS' = '30'
    'SK_MAX_TOKENS_PER_FUNCTION' = '1000'
    'SK_ENABLE_TRACING' = 'true'
    'GRAPH_AGENT_NAME' = 'knowledge_graph_agent'
    'GRAPH_AGENT_MAX_RESULTS_RETURNED' = '100'
    'HYBRID_AGENT_SQL_WEIGHT' = '0.6'
    'HYBRID_AGENT_GRAPH_WEIGHT' = '0.4'
    'ACCOUNT_RESOLVER_EMBEDDING_MODEL' = 'text-embedding-3-small'
    'TELEMETRY_SERVICE_NAME' = 'salesforce-chatbot'
    'CONTAINER_APP_NAME' = 'salesforce-chatbot'
    'DOCKER_IMAGE_TAG' = 'latest'
    'DEV_MOCK_AZURE_AUTH' = 'false'
    'DEV_MOCK_DATABASE' = 'false'
    'DEV_CORS_ALLOW_ALL' = 'false'
    'SHAREPOINT_SITE_URL' = 'https://your-tenant.sharepoint.com/sites/your-site'
    'POWERBI_WORKSPACE_ID' = 'your-workspace-id'
    'DYNAMICS_365_URL' = 'https://your-org.crm.dynamics.com'
    'COSMOS_DB_CACHE_CONTAINER' = 'cache'
    'COSMOS_DB_FEEDBACK_CONTAINER' = 'feedback'
    'COSMOS_DB_PROMPTS_CONTAINER' = 'prompts'
    'COSMOS_DB_SQL_SCHEMA_CONTAINER' = 'sql_schema'
    'COSMOS_DB_RETRY_DELAY_SECONDS' = '2'
    'GREMLIN_DATABASE_NAME' = 'salesforce_graph'
    'SQL_SERVER_NAME' = 'your-fabric-workspace.datawarehouse.fabric.microsoft.com'
    'SQL_DATABASE_NAME' = 'your_warehouse_name'
    'SQL_COMMAND_TIMEOUT_SECONDS' = '300'
    'RBAC_JWT_ISSUER' = 'https://sts.windows.net/your-tenant-id/'
    'APP_HOST' = '0.0.0.0'
    'APP_PORT' = '8000'
    'APP_WORKERS' = '4'
    'APP_API_PREFIX' = '/api/v1'
    'AZURE_OPENAI_ENDPOINT' = 'https://your-aoai.openai.azure.com/'
    'AZURE_COSMOS_ENDPOINT' = 'https://your-cosmos-account.documents.azure.com:443/'
    'AZURE_COSMOS_CACHE_CONTAINER' = 'cache'
    'AZURE_SEARCH_ENDPOINT' = 'https://your-search.search.windows.net'
    'AZURE_SEARCH_INDEX' = 'contracts-index'
    'FABRIC_SQL_ENDPOINT' = 'your-workspace.datawarehouse.fabric.microsoft.com'
    'FABRIC_SQL_DATABASE' = 'lakehouse_db'
    'AZURE_AD_CLIENT_ID' = 'your-client-id'
    'DEV_USER_EMAIL' = ''
    'ENVIRONMENT' = 'development'
    'LOG_LEVEL' = 'INFO'
    'MAX_TOKENS_PER_REQUEST' = '4000'
    'TELEMETRY_ENABLE_TELEMETRY' = 'false'
    'VECTOR_SEARCH_SCORE_THRESHOLD' = '0.7'
    'DEV_MODE' = 'true'
}

foreach ($key in $defaults.Keys) {
    if (-not $envVars.ContainsKey($key) -or -not $envVars[$key] -or $envVars[$key] -match '^your|^$') {
        $envVars[$key] = $defaults[$key]
        Write-Output "Set default for $key = $($defaults[$key])"
    }
}
if ($ResourceGroup) {
	if (-not $envVars.ContainsKey('CONTAINER_APP_RESOURCE_GROUP') -or $envVars['CONTAINER_APP_RESOURCE_GROUP'] -match 'your') {
		$envVars['CONTAINER_APP_RESOURCE_GROUP'] = $ResourceGroup
	}
	if (-not $envVars.ContainsKey('CONTAINER_APP_ENVIRONMENT') -or $envVars['CONTAINER_APP_ENVIRONMENT'] -match 'your') {
		$envVars['CONTAINER_APP_ENVIRONMENT'] = $ResourceGroup
	}
	try {
		$acct = az account show -o json | ConvertFrom-Json
		$sub = $acct.id
		$tenant = $acct.tenantId
		if ($sub) {
			if (-not $envVars.ContainsKey('CONTAINER_APP_SUBSCRIPTION_ID') -or $envVars['CONTAINER_APP_SUBSCRIPTION_ID'] -match 'your') {
				$envVars['CONTAINER_APP_SUBSCRIPTION_ID'] = $sub
			}
		}
		if ($tenant) {
			if (-not $envVars.ContainsKey('AZURE_AD_TENANT_ID') -or $envVars['AZURE_AD_TENANT_ID'] -match 'your') {
				$envVars['AZURE_AD_TENANT_ID'] = $tenant
			}
		}
	} catch { Write-Warning "Could not detect subscription id or tenant id: $_" }
}

# If AZURE_COSMOS_ENDPOINT contains 'your', set it from detected Cosmos endpoint
if ($envVars.ContainsKey('COSMOS_ENDPOINT') -and $envVars['COSMOS_ENDPOINT'] -and ($envVars['COSMOS_ENDPOINT'] -notmatch 'your')) {
	$cosmosEndpoint = $envVars['COSMOS_ENDPOINT']
	if (-not $envVars.ContainsKey('AZURE_COSMOS_ENDPOINT') -or $envVars['AZURE_COSMOS_ENDPOINT'] -match 'your') {
		$envVars['AZURE_COSMOS_ENDPOINT'] = $cosmosEndpoint
	}
	if (-not $envVars.ContainsKey('AZURE_COSMOS_DATABASE') -or $envVars['AZURE_COSMOS_DATABASE'] -match 'your') {
		$envVars['AZURE_COSMOS_DATABASE'] = $envVars['COSMOS_DATABASE_NAME']
	}
	if (-not $envVars.ContainsKey('AZURE_COSMOS_HISTORY_CONTAINER') -or $envVars['AZURE_COSMOS_HISTORY_CONTAINER'] -match 'your') {
		$envVars['AZURE_COSMOS_HISTORY_CONTAINER'] = 'chat_history'
	}
	if (-not $envVars.ContainsKey('AZURE_COSMOS_FEEDBACK_CONTAINER') -or $envVars['AZURE_COSMOS_FEEDBACK_CONTAINER'] -match 'your') {
		$envVars['AZURE_COSMOS_FEEDBACK_CONTAINER'] = 'feedback'
	}
	if (-not $envVars.ContainsKey('COSMOS_CHAT_CONTAINER') -or $envVars['COSMOS_CHAT_CONTAINER'] -match 'your') {
		$envVars['COSMOS_CHAT_CONTAINER'] = 'chat_history'
	}
	if (-not $envVars.ContainsKey('COSMOS_CACHE_CONTAINER') -or $envVars['COSMOS_CACHE_CONTAINER'] -match 'your') {
		$envVars['COSMOS_CACHE_CONTAINER'] = 'cache'
	}
	if (-not $envVars.ContainsKey('COSMOS_FEEDBACK_CONTAINER') -or $envVars['COSMOS_FEEDBACK_CONTAINER'] -match 'your') {
		$envVars['COSMOS_FEEDBACK_CONTAINER'] = 'feedback'
	}
	if (-not $envVars.ContainsKey('COSMOS_PROCESSED_FILES_CONTAINER') -or $envVars['COSMOS_PROCESSED_FILES_CONTAINER'] -match 'your') {
		$envVars['COSMOS_PROCESSED_FILES_CONTAINER'] = 'processed_files'
	}
	if (-not $envVars.ContainsKey('COSMOS_PROMPTS_CONTAINER') -or $envVars['COSMOS_PROMPTS_CONTAINER'] -match 'your') {
		$envVars['COSMOS_PROMPTS_CONTAINER'] = 'prompts'
	}
	if (-not $envVars.ContainsKey('COSMOS_SQL_SCHEMA_CONTAINER') -or $envVars['COSMOS_SQL_SCHEMA_CONTAINER'] -match 'your') {
		$envVars['COSMOS_SQL_SCHEMA_CONTAINER'] = 'sql_schema'
	}
	if (-not $envVars.ContainsKey('COSMOS_ACCOUNT_RESOLVER_CONTAINER') -or $envVars['COSMOS_ACCOUNT_RESOLVER_CONTAINER'] -match 'your') {
		$envVars['COSMOS_ACCOUNT_RESOLVER_CONTAINER'] = 'account_resolver'
	}
	if (-not $envVars.ContainsKey('COSMOS_AGENT_FUNCTIONS_CONTAINER') -or $envVars['COSMOS_AGENT_FUNCTIONS_CONTAINER'] -match 'your') {
		$envVars['COSMOS_AGENT_FUNCTIONS_CONTAINER'] = 'agent_functions'
	}
}

# Set Gremlin derived vars
if ($envVars.ContainsKey('GREMLIN_ENDPOINT') -and $envVars['GREMLIN_ENDPOINT'] -and ($envVars['GREMLIN_ENDPOINT'] -notmatch 'your')) {
	if (-not $envVars.ContainsKey('AZURE_COSMOS_GREMLIN_ENDPOINT') -or $envVars['AZURE_COSMOS_GREMLIN_ENDPOINT'] -match 'your') {
		$envVars['AZURE_COSMOS_GREMLIN_ENDPOINT'] = $envVars['GREMLIN_ENDPOINT']
	}
	if (-not $envVars.ContainsKey('AZURE_COSMOS_GREMLIN_DATABASE') -or $envVars['AZURE_COSMOS_GREMLIN_DATABASE'] -match 'your') {
		$envVars['AZURE_COSMOS_GREMLIN_DATABASE'] = 'graphdb'
	}
	if (-not $envVars.ContainsKey('AZURE_COSMOS_GREMLIN_GRAPH') -or $envVars['AZURE_COSMOS_GREMLIN_GRAPH'] -match 'your') {
		$envVars['AZURE_COSMOS_GREMLIN_GRAPH'] = 'relationships'
	}
	if (-not $envVars.ContainsKey('AZURE_COSMOS_GREMLIN_PORT') -or $envVars['AZURE_COSMOS_GREMLIN_PORT'] -match 'your') {
		$envVars['AZURE_COSMOS_GREMLIN_PORT'] = '443'
	}
}

# Write merged vars to .env and chatbot/.env
$rootEnvPath = Join-Path -Path (Get-Location) -ChildPath ".env"
$chatbotEnvPath = Join-Path -Path (Get-Location) -ChildPath "chatbot\.env"


Write-Output "Writing merged .env to $rootEnvPath and $chatbotEnvPath"

# read existing root env
$rootEnv = Read-EnvFile -path $rootEnvPath
foreach ($k in $envVars.Keys) { $rootEnv[$k] = $envVars[$k] }
Write-EnvFile -path $rootEnvPath -env $rootEnv

$chatEnv = Read-EnvFile -path $chatbotEnvPath
foreach ($k in $envVars.Keys) { $chatEnv[$k] = $envVars[$k] }
Write-EnvFile -path $chatbotEnvPath -env $chatEnv

Write-Output "Merged .env written. You can now run .\scripts\start_server.ps1 to start the app."

Write-Output "Note: This script attempts to auto-discover endpoints and AOAI deployment names; if deployments aren't found they must be set manually in the .env files."
