param(
  [Parameter(Mandatory=$true)][string]$BaseName,
  [Parameter(Mandatory=$true)][string]$Location,
  [Parameter(Mandatory=$true)][string]$OpenAiLocation,
  [Parameter(Mandatory=$true)][string]$ChatImage,
  [Parameter(Mandatory=$true)][string]$IndexerImage,
  [string]$Rg = "$BaseName-rg",
  [string]$OpenAiModel = "gpt-4o",
  [string]$OpenAiModelVersion = "2024-05-13",
  [string]$SpaPath,
  [switch]$DisableAoaiKeys,
  [switch]$PrivateNetworking
)

# ------------- helpers -------------
function Ensure-Ext($name) {
  $exists = az extension list --query "[?name=='$name']" -o tsv 2>$null
  if (-not $exists) { az extension add -n $name | Out-Null } else { az extension update -n $name | Out-Null }
}
function Mime-FromExt($path) {
  $ext = [System.IO.Path]::GetExtension($path).ToLower()
  switch ($ext) {
    '.html' { 'text/html' }
    '.js'   { 'application/javascript' }
    '.css'  { 'text/css' }
    '.svg'  { 'image/svg+xml' }
    '.png'  { 'image/png' }
    '.jpg'  { 'image/jpeg' }
    '.jpeg' { 'image/jpeg' }
    '.gif'  { 'image/gif' }
    '.webp' { 'image/webp' }
    '.woff' { 'font/woff' }
    '.woff2'{ 'font/woff2' }
    default { 'application/octet-stream' }
  }
}

# ------------- pre-checks -------------
$ctx = az account show -o json 2>$null | ConvertFrom-Json
if (-not $ctx) { throw "Please run 'az login' first." }
$tenantId = $ctx.tenantId
$subId = $ctx.id

az provider register -n Microsoft.App --wait | Out-Null
az provider register -n Microsoft.CognitiveServices --wait | Out-Null
az provider register -n Microsoft.DocumentDB --wait | Out-Null
az provider register -n Microsoft.Cdn --wait | Out-Null
az provider register -n Microsoft.ApiManagement --wait | Out-Null
az provider register -n Microsoft.Network --wait | Out-Null
Ensure-Ext 'containerapp'
Ensure-Ext 'afd'

# ------------- names -------------
$N = $BaseName.ToLower()
$EnvName = "$N-env"
$MiName = "$N-mi"
$LaName = "$N-log"
$AppiName = "$N-appi"
$AoaiName = "$N-aoai"
$CosmosSql = "$N-cosmos-sql"
$CosmosGraph = "$N-cosmos-graph"
$Storage = ($N + "spa" + (Get-Random -Maximum 99999)).ToLower()
$ApimName = "$N-apim"
$FdProfile = "$N-fd"
$FdEndpoint = "$N-ep"
$SpaOg = "$N-spa-og"
$ApimOg = "$N-apim-og"
$ChatApp = "$N-chat"
$IndexerApp = "$N-indexer"
$WafName = "$N-waf"

# VNet bits (only when -PrivateNetworking)
$VnetName = "$N-vnet"
$SubnetAca = "aca-subnet"
$SubnetApim = "apim-subnet"
$SubnetPe = "pe-subnet"

Write-Host ">>> Resource group" -ForegroundColor Cyan
az group create -n $Rg -l $Location -o none

# --- Derive APIM publisher info from the signed-in Entra user ---
# Primary attempt: use Entra user object (works when logged in as a user)
$publisherName = $null
$publisherEmail = $null
try {
  $me = az ad signed-in-user show -o json 2>$null | ConvertFrom-Json
  if ($me) {
    $publisherName  = $me.displayName
    $publisherEmail = if ($me.mail) { $me.mail } else { $me.userPrincipalName }
  }
} catch { }

# Fallback: use az account (works for SPN too; synthesize an email if needed)
if (-not $publisherName -or -not $publisherEmail) {
  $acct = az account show -o json | ConvertFrom-Json
  $upn  = $acct.user.name
  if (-not $publisherName)  { $publisherName = $upn }
  if (-not $publisherEmail) {
    if ($upn -like "*@*") { $publisherEmail = $upn }
    else {
      # Create a safe-looking email using tenant's onmicrosoft domain
      $publisherEmail = "$($env:USERNAME)@$($tenantId).onmicrosoft.com"
    }
  }
}

Write-Host "APIM Publisher: $publisherName <$publisherEmail>"

# ------------- Managed Identity -------------
Write-Host ">>> Managed Identity" -ForegroundColor Cyan
$uami = az identity create -g $Rg -n $MiName -l $Location -o json | ConvertFrom-Json
$miId = $uami.id
$miPid = $uami.principalId
$miClientId = $uami.clientId

# ------------- Networking (optional) -------------
if ($PrivateNetworking) {
  Write-Host ">>> VNet + subnets (ACA / APIM / Private Endpoints)" -ForegroundColor Cyan
  az network vnet create -g $Rg -n $VnetName -l $Location --address-prefixes 10.40.0.0/16 -o none
  az network vnet subnet create -g $Rg --vnet-name $VnetName -n $SubnetAca --address-prefixes 10.40.1.0/24 `
    --delegations Microsoft.App/environments -o none
  az network vnet subnet create -g $Rg --vnet-name $VnetName -n $SubnetApim --address-prefixes 10.40.2.0/24 -o none
  az network vnet subnet create -g $Rg --vnet-name $VnetName -n $SubnetPe  --address-prefixes 10.40.3.0/24 -o none
  $subnetAcaId = az network vnet subnet show -g $Rg --vnet-name $VnetName -n $SubnetAca --query id -o tsv
  $subnetApimId = az network vnet subnet show -g $Rg --vnet-name $VnetName -n $SubnetApim --query id -o tsv
  $subnetPeId = az network vnet subnet show -g $Rg --vnet-name $VnetName -n $SubnetPe --query id -o tsv
}

# ------------- Log Analytics + App Insights -------------
Write-Host ">>> Log Analytics + App Insights" -ForegroundColor Cyan
$law = az monitor log-analytics workspace create -g $Rg -n $LaName -l $Location -o json | ConvertFrom-Json
$lawKey = (az monitor log-analytics workspace get-shared-keys -g $Rg -n $LaName --query primarySharedKey -o tsv)
$appi = az monitor app-insights component create -g $Rg -a $AppiName -l $Location --workspace $law.id -o json | ConvertFrom-Json
$appInsightsConn = $appi.connectionString

# ------------- Container Apps Env -------------
Write-Host ">>> Container Apps Environment" -ForegroundColor Cyan
if ($PrivateNetworking) {
  az containerapp env create -g $Rg -n $EnvName -l $Location `
    --infrastructure-subnet-resource-id $subnetAcaId `
    --logs-workspace-id $law.customerId --logs-workspace-key $lawKey -o none
} else {
  az containerapp env create -g $Rg -n $EnvName -l $Location `
    --logs-workspace-id $law.customerId --logs-workspace-key $lawKey -o none
}

# ------------- Cosmos DB (NoSQL) -------------
Write-Host ">>> Cosmos DB (NoSQL)" -ForegroundColor Cyan
az cosmosdb create -g $Rg -n $CosmosSql -l $Location --kind GlobalDocumentDB --public-network-access Enabled -o none
az cosmosdb sql database create -g $Rg -a $CosmosSql -n appdb -o none
$containers = @(
  @{ name = 'prompts';         pk = '/tenantId'     }
  @{ name = 'chat_history';    pk = '/chatId'       ; uk = "[{'paths':['/chatId','/turnId']}]" }
  @{ name = 'cache';           pk = '/key'          }
  @{ name = 'feedback';        pk = '/chatId'       }
  @{ name = 'sql_schema';      pk = '/entity'       }
  @{ name = 'agent_functions'; pk = '/agent'        }
)
foreach ($c in $containers) {
  $args = @("cosmosdb","sql","container","create","-g",$Rg,"-a",$CosmosSql,"-d","appdb","-n",$c.name,"--partition-key-path",$c.pk,"-o","none")
  if ($c.uk) { $args += @("--unique-key-policy",$c.uk) }
  az @args
}
$cosmosSqlId = az cosmosdb show -g $Rg -n $CosmosSql --query id -o tsv
$cosmosSqlEp = az cosmosdb show -g $Rg -n $CosmosSql --query documentEndpoint -o tsv

# ------------- Cosmos DB (Gremlin) -------------
Write-Host ">>> Cosmos DB (Gremlin)" -ForegroundColor Cyan
az cosmosdb create -g $Rg -n $CosmosGraph -l $Location --capabilities EnableGremlin --public-network-access Enabled -o none
az cosmosdb gremlin database create -g $Rg -a $CosmosGraph -n graphdb -o none
az cosmosdb gremlin graph create -g $Rg -a $CosmosGraph -d graphdb -n account_graph --partition-key-path "/partitionKey" -o none
$cosmosGraphId = az cosmosdb show -g $Rg -n $CosmosGraph --query id -o tsv
$cosmosGraphEp = az cosmosdb show -g $Rg -n $CosmosGraph --query documentEndpoint -o tsv

# ------------- Azure OpenAI (token-only) -------------
Write-Host ">>> Azure OpenAI + gpt-4o (token only)" -ForegroundColor Cyan
$aoaiArgs = @("cognitiveservices","account","create","-g",$Rg,"-n",$AoaiName,"-l",$OpenAiLocation,"--kind","OpenAI","--sku","S0","--yes","--assign-identity",$miId)
# Always disable local auth for token-only as per requirement
$aoaiArgs += @("--disable-local-auth","true")
az @aoaiArgs -o none
az cognitiveservices account deployment create -g $Rg -n $AoaiName --deployment-name $OpenAiModel `
  --model-name $OpenAiModel --model-version $OpenAiModelVersion --model-format OpenAI --scale-settings-scale-type Standard -o none
$aoaiId = az cognitiveservices account show -g $Rg -n $AoaiName --query id -o tsv
$aoaiEndpoint = "https://$AoaiName.openai.azure.com/"

# ------------- Storage (SPA) -------------
Write-Host ">>> Storage (Static Website + upload with Cache-Control)" -ForegroundColor Cyan
az storage account create -g $Rg -n $Storage -l $Location --sku Standard_LRS --kind StorageV2 --https-only true --allow-blob-public-access true -o none
az storage blob service-properties update --account-name $Storage --static-website --index-document index.html --404-document index.html -o none
$spaHost = "$Storage.z13.web.core.windows.net"
if (-not $SpaPath) {
  $tmp = Join-Path $env:TEMP "$N-spa"
  New-Item -ItemType Directory -Force -Path $tmp | Out-Null
  "<!doctype html><html><head><meta charset='utf-8'><title>$BaseName</title></head><body><h1>$BaseName SPA</h1></body></html>" `
    | Out-File -Encoding utf8 (Join-Path $tmp "index.html")
  $SpaPath = $tmp
}
Get-ChildItem -Path $SpaPath -Recurse -File | ForEach-Object {
  $rel = $_.FullName.Substring($SpaPath.Length).TrimStart('\','/')
  if (-not $rel) { $rel = $_.Name }
  $mime = Mime-FromExt $_.FullName
  $cache = "public, max-age=31536000, immutable"
  if ($_.Name -match '\.html$' -or $rel -eq "index.html") { $cache = "no-store" }
  az storage blob upload --account-name $Storage --container-name '$web' --name $rel `
    --file $_.FullName --overwrite `
    --content-type "$mime" --content-cache-control "$cache" -o none
}

# ------------- API Management -------------
Write-Host ">>> API Management (Developer)" -ForegroundColor Cyan
if ($PrivateNetworking) {
  az apim create -g $Rg -n $ApimName -l $Location `
    --publisher-email $publisherEmail --publisher-name $publisherName `
    --sku-name Developer --virtual-network-type External --subnet $subnetApimId -o none
} else {
  az apim create -g $Rg -n $ApimName -l $Location `
    --publisher-email $publisherEmail --publisher-name $publisherName `
    --sku-name Developer -o none
}
az apim api create -g $Rg --service-name $ApimName --api-id acctbot --path "api" --display-name "acctbot" --protocols https -o none
az apim api operation create -g $Rg --service-name $ApimName --api-id acctbot --url-template "/ask" --method POST --display-name "ask" -o none

# ------------- Container Apps (Chat + Indexer) -------------
Write-Host ">>> Container Apps" -ForegroundColor Cyan
$commonEnv = @(
  @{ name="APPINSIGHTS_CONNECTION_STRING"; value=$appInsightsConn },
  @{ name="AOAI_ENDPOINT"; value=$aoaiEndpoint },
  @{ name="AOAI_DEPLOYMENT"; value=$OpenAiModel },
  @{ name="AZURE_CLIENT_ID"; value=$miClientId },
  @{ name="COSMOS_SQL_ENDPOINT"; value=$cosmosSqlEp },
  @{ name="COSMOS_SQL_DB"; value="appdb" },
  @{ name="COSMOS_GRAPH_ENDPOINT"; value=$cosmosGraphEp },
  @{ name="GRAPH_DB"; value="graphdb" },
  @{ name="GRAPH_NAME"; value="account_graph" }
) | ConvertTo-Json

if ($PrivateNetworking) {
  # Chat = internal; Indexer = internal
  az containerapp create -g $Rg -n $ChatApp -l $Location --environment $EnvName --image $ChatImage `
    --ingress internal --target-port 8080 --user-assigned $miId --cpu 1 --memory 2Gi --env-vars $commonEnv | Out-Null
  az containerapp create -g $Rg -n $IndexerApp -l $Location --environment $EnvName --image $IndexerImage `
    --ingress internal --target-port 8080 --user-assigned $miId --cpu 1 --memory 2Gi --env-vars $commonEnv | Out-Null
} else {
  # Chat = public; Indexer = internal
  az containerapp create -g $Rg -n $ChatApp -l $Location --environment $EnvName --image $ChatImage `
    --ingress external --target-port 8080 --user-assigned $miId --cpu 1 --memory 2Gi --env-vars $commonEnv | Out-Null
  az containerapp create -g $Rg -n $IndexerApp -l $Location --environment $EnvName --image $IndexerImage `
    --ingress internal --target-port 8080 --user-assigned $miId --cpu 1 --memory 2Gi --env-vars $commonEnv | Out-Null
}
$chatFqdn = az containerapp show -g $Rg -n $ChatApp --query "properties.configuration.ingress.fqdn" -o tsv

# ------------- Front Door Standard + WAF -------------
Write-Host ">>> Front Door (Std) + two routes + WAF" -ForegroundColor Cyan
az afd profile create -g $Rg -n $FdProfile --sku Standard_AzureFrontDoor -o none
az afd endpoint create -g $Rg --profile-name $FdProfile -n $FdEndpoint -o none

az afd origin-group create -g $Rg --profile-name $FdProfile -n $SpaOg --session-affinity-enabled Disabled -o none
az afd origin create -g $Rg --profile-name $FdProfile --origin-group-name $SpaOg -n spa `
  --host-name $spaHost --origin-host-header $spaHost --enabled-state Enabled -o none

$apimGw = (az apim show -g $Rg -n $ApimName --query "gatewayUrl" -o tsv).Replace("https://","")
az afd origin-group create -g $Rg --profile-name $FdProfile -n $ApimOg -o none
az afd origin create -g $Rg --profile-name $FdProfile --origin-group-name $ApimOg -n apim `
  --host-name $apimGw --origin-host-header $apimGw --enabled-state Enabled -o none

az afd route create -g $Rg --profile-name $FdProfile --endpoint-name $FdEndpoint -n api-route `
  --origin-group $ApimOg --https-redirect Enabled --forwarding-protocol HttpsOnly `
  --supported-protocols Https --patterns-to-match "/api/*" -o none
az afd route create -g $Rg --profile-name $FdProfile --endpoint-name $FdEndpoint -n spa-route `
  --origin-group $SpaOg --https-redirect Enabled --forwarding-protocol HttpsOnly `
  --supported-protocols Https --patterns-to-match "/*" -o none

# API bypass cache; SPA compression on
$apiRouteId="/subscriptions/$subId/resourceGroups/$Rg/providers/Microsoft.Cdn/profiles/$FdProfile/afdEndpoints/$FdEndpoint/routes/api-route?api-version=2023-05-01"
$spaRouteId="/subscriptions/$subId/resourceGroups/$Rg/providers/Microsoft.Cdn/profiles/$FdProfile/afdEndpoints/$FdEndpoint/routes/spa-route?api-version=2023-05-01"
az rest --method patch --uri "https://management.azure.com$apiRouteId" --body (@{ properties = @{ cacheConfiguration = @{ cacheBehavior = "BypassCache"; compressionSettings = @{ isCompressionEnabled = $false } } } } | ConvertTo-Json) | Out-Null
az rest --method patch --uri "https://management.azure.com$spaRouteId" --body (@{ properties = @{ cacheConfiguration = @{ compressionSettings = @{ isCompressionEnabled = $true }; queryStringCachingBehavior = "IgnoreQueryString" } } } | ConvertTo-Json) | Out-Null

# WAF policy attach to both routes
$waf = az network front-door waf-policy create -g $Rg -n $WafName --mode Prevention --sku Standard_AzureFrontDoor -o json | ConvertFrom-Json
$wafId = $waf.id
az rest --method patch --uri "https://management.azure.com$apiRouteId" --body (@{ properties = @{ webApplicationFirewallPolicyLink = @{ id = $wafId } } } | ConvertTo-Json) | Out-Null
az rest --method patch --uri "https://management.azure.com$spaRouteId" --body (@{ properties = @{ webApplicationFirewallPolicyLink = @{ id = $wafId } } } | ConvertTo-Json) | Out-Null

$fdDefaultHost = az afd endpoint show -g $Rg --profile-name $FdProfile -n $FdEndpoint --query "hostName" -o tsv

# ------------- Entra Apps (API + SPA PKCE) -------------
Write-Host ">>> Entra App Registrations (API + SPA PKCE)" -ForegroundColor Cyan
$ApiAppName = "$BaseName-api-app"
$SpaAppName = "$BaseName-spa-app"

# API app
$apiApp = az ad app create --display-name $ApiAppName --sign-in-audience AzureADMyOrg -o json | ConvertFrom-Json
$apiAppId = $apiApp.appId
az ad app update --id $apiAppId --identifier-uris "api://$apiAppId" | Out-Null
$scopeId = (New-Guid).Guid
$oauthScopes = @(
  @{
    adminConsentDescription = "Access $BaseName API"
    adminConsentDisplayName = "Access $BaseName API"
    id = $scopeId
    type = "User"
    value = "access_as_user"
    enabled = $true
  }
) | ConvertTo-Json
az ad app update --id $apiAppId --set api.oauth2PermissionScopes="$oauthScopes" | Out-Null
az ad sp create --id $apiAppId -o none

# SPA app with redirect to Front Door
$spaRedirect = "https://$fdDefaultHost/"
$spaApp = az ad app create --display-name $SpaAppName --sign-in-audience AzureADMyOrg --spa-redirect-uris $spaRedirect -o json | ConvertFrom-Json
$spaAppId = $spaApp.appId
az ad sp create --id $spaAppId -o none
# grant SPA -> API
az ad app permission add --id $spaAppId --api $apiAppId --api-permissions "$scopeId=Scope" -o none
try { az ad app permission admin-consent --id $spaAppId -o none } catch { Write-Warning "Admin consent failed. Run as tenant admin to grant." }

# ------------- APIM policy: validate JWT + route to Chat app -------------
Write-Host ">>> APIM validate-jwt + rewrite" -ForegroundColor Cyan
$openid = "https://login.microsoftonline.com/$tenantId/v2.0/.well-known/openid-configuration"
$chatBackendUrl = if ($PrivateNetworking) { "https://$chatFqdn" } else { "https://$chatFqdn" }
$policy = @"
<policies>
  <inbound>
    <base />
    <validate-jwt header-name=""Authorization"" failed-validation-httpcode=""401"" require-signed-tokens=""true"" require-expiration-time=""true"">
      <openid-config url=""$openid"" />
      <audiences>
        <audience>api://$apiAppId</audience>
      </audiences>
    </validate-jwt>
    <rewrite-uri template=""@(context.Request.OriginalUrl.PathAndQuery.Substring(4))"" />
    <set-backend-service base-url=""$chatBackendUrl"" />
  </inbound>
  <backend><base /></backend>
  <outbound><base /></outbound>
  <on-error><base /></on-error>
</policies>
"@
az apim api policy apply -g $Rg --service-name $ApimName --api-id acctbot --xml-content $policy | Out-Null

# ------------- Private Endpoints for Cosmos (if -PrivateNetworking) -------------
if ($PrivateNetworking) {
  Write-Host ">>> Cosmos Private Endpoints + Private DNS" -ForegroundColor Cyan

  # Private DNS zones for Cosmos
  $dnsZoneCosmos = "privatelink.documents.azure.com"
  az network private-dns zone create -g $Rg -n $dnsZoneCosmos -o none
  az network private-dns link vnet create -g $Rg -n "$N-cosmos-dnslink" -z $dnsZoneCosmos -v $VnetName -e true -o none

  # NoSQL PE
  az network private-endpoint create -g $Rg -n "$N-pe-cosmos-sql" -l $Location `
    --vnet-name $VnetName --subnet $SubnetPe `
    --private-connection-resource-id $cosmosSqlId --group-ids Sql `
    --connection-name "$N-peconn-cosmos-sql" -o none
  az network private-endpoint dns-zone-group create -g $Rg -n "$N-dns-cosmos-sql" `
    --endpoint-name "$N-pe-cosmos-sql" --private-dns-zone $dnsZoneCosmos --zone-name "cosmos-sql" -o none

  # Gremlin PE
  az network private-endpoint create -g $Rg -n "$N-pe-cosmos-gremlin" -l $Location `
    --vnet-name $VnetName --subnet $SubnetPe `
    --private-connection-resource-id $cosmosGraphId --group-ids Gremlin `
    --connection-name "$N-peconn-cosmos-gremlin" -o none
  az network private-endpoint dns-zone-group create -g $Rg -n "$N-dns-cosmos-gremlin" `
    --endpoint-name "$N-pe-cosmos-gremlin" --private-dns-zone $dnsZoneCosmos --zone-name "cosmos-gremlin" -o none
}

# ------------- RBAC for MI (AOAI + Cosmos) -------------
Write-Host ">>> RBAC: MI -> AOAI + Cosmos data-plane" -ForegroundColor Cyan
az role assignment create --assignee-object-id $miPid --assignee-principal-type ServicePrincipal --role "Cognitive Services OpenAI User" --scope $aoaiId -o none
az role assignment create --assignee-object-id $miPid --assignee-principal-type ServicePrincipal --role "Cosmos DB Built-in Data Contributor" --scope $cosmosSqlId -o none
az role assignment create --assignee-object-id $miPid --assignee-principal-type ServicePrincipal --role "Cosmos DB Built-in Data Contributor" --scope $cosmosGraphId -o none

# ------------- Summary -------------
$fdDefaultHost = az afd endpoint show -g $Rg --profile-name $FdProfile -n $FdEndpoint --query "hostName" -o tsv
Write-Host ""
Write-Host "================ DEPLOYMENT COMPLETE ================" -ForegroundColor Cyan
Write-Host ("Front Door URL         : https://{0}" -f $fdDefaultHost)
Write-Host ("SPA Redirect URI       : https://{0}" -f $fdDefaultHost)
Write-Host ("APIM Base (via FD)     : https://{0}/api" -f $fdDefaultHost)
Write-Host ("Chat App (FQDN)        : https://{0}" -f $chatFqdn)
Write-Host ("AOAI endpoint (short)  : {0}" -f $aoaiEndpoint)
Write-Host ("API App (clientId)     : {0}" -f $apiAppId)
Write-Host ("SPA App (clientId)     : {0}" -f $spaAppId)
Write-Host ("Managed Identity       : {0} (clientId: {1})" -f $MiName, $miClientId)
Write-Host ("Cosmos NoSQL endpoint  : {0} (db: appdb)" -f $cosmosSqlEp)
Write-Host ("Cosmos Graph endpoint  : {0} (db: graphdb, graph: account_graph)" -f $cosmosGraphEp)
Write-Host ("Private Networking     : {0}" -f ($PrivateNetworking.IsPresent))
Write-Host "====================================================="
