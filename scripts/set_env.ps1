
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
		'COSMOS_ENDPOINT','COSMOS_DATABASE_NAME','COSMOS_CHAT_CONTAINER','COSMOS_CACHE_CONTAINER',
		'GREMLIN_ENDPOINT'
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
	} else {
		Write-Warning "No Azure OpenAI account detected in RG $ResourceGroup"
	}

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
}

# Write merged vars to .env and chatbot/.env
$rootEnvPath = Join-Path -Path (Get-Location) -ChildPath ".env"
$chatbotEnvPath = Join-Path -Path (Get-Location) -ChildPath "chatbot\.env"

Write-Output "Pausing 30s to allow Azure operations to settle..."
Start-Sleep -Seconds 30

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
