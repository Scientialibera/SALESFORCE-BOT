# Start the FastAPI uvicorn server with correct PYTHONPATH and log redirection.
# Run from project root: .\scripts\start_server.ps1

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Get-Location

# If not running under a permissive execution policy, relaunch this script with Bypass so Start-Process/Redirect works
try {
    $currentPolicy = Get-ExecutionPolicy -Scope Process -ErrorAction SilentlyContinue
} catch {
    $currentPolicy = $null
}

if ($currentPolicy -ne 'Bypass' -and $currentPolicy -ne 'Unrestricted') {
    Write-Output "ExecutionPolicy is '$currentPolicy' - relaunching this script with Bypass to allow Start-Process and redirection."
    Start-Process -FilePath powershell -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',"$MyInvocation.MyCommand.Path" -WorkingDirectory $repoRoot
    exit 0
}

# Ensure .env is loaded by the app; we don't set env variables here except to note DEV_MODE
$envPath = Join-Path $repoRoot '.env'
if (-Not (Test-Path $envPath)) {
    Write-Output ".env not found. Run .\scripts\set_env.ps1 first."
    exit 1
}

# Stop any process listening on port 8000 so we can restart cleanly
$port = 8000
Write-Output "Checking for processes listening on port $port..."
try {
    $connections = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if ($connections) {
        $owningPids = $connections | Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($procId in $owningPids) {
            if ($procId -and $procId -ne $PID) {
                Write-Output "Stopping process with PID $procId listening on port $port"
                Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            }
        }
    } else {
        Write-Output "No process found on port $port"
    }
} catch {
    Write-Output ("Failed to check or stop processes on port {0}: {1}" -f $port, $_)
}

# Build PYTHONPATH to include chatbot/src
$pythonpath = Join-Path (Join-Path $repoRoot 'chatbot') 'src'
$env:PYTHONPATH = $pythonpath
Write-Output "PYTHONPATH set to $env:PYTHONPATH"

# Start uvicorn in a new process and redirect output to server.log
$logPath = Join-Path $repoRoot 'server.log'
Write-Output "Starting uvicorn; logs will be written to $logPath"

# Use Start-Process so the server runs independently of the shell
$pythonExe = "python"
$uvicornModule = "-m uvicorn"
$appModule = "chatbot.app:app"
$hostPort = "--host 127.0.0.1 --port 8000"
$logLevel = "--log-level info"

# Start as background process. Combine stderr with stdout so only server.log is created.
Start-Process -FilePath $pythonExe -ArgumentList "$uvicornModule $appModule $hostPort $logLevel" -WorkingDirectory $repoRoot -NoNewWindow -RedirectStandardOutput $logPath
Write-Output "Uvicorn process started. Check $logPath for logs."