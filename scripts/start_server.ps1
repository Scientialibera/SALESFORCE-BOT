# Start the FastAPI uvicorn server with correct PYTHONPATH and log redirection.
# Run from project root: .\scripts\start_server.ps1

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Get-Location

# Ensure .env is loaded by the app; we don't set env variables here except to note DEV_MODE
$envPath = Join-Path $repoRoot '.env'
if (-Not (Test-Path $envPath)) {
    Write-Output ".env not found. Run .\scripts\set_env.ps1 first."
    exit 1
}

# Build PYTHONPATH to include chatbot/src
$pythonpath = Join-Path $repoRoot 'chatbot' 'src'
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

# Start as background process
Start-Process -FilePath $pythonExe -ArgumentList "$uvicornModule $appModule $hostPort $logLevel" -WorkingDirectory $repoRoot -NoNewWindow -RedirectStandardOutput $logPath -RedirectStandardError $logPath
Write-Output "Uvicorn process started. Use Get-Process -Name python to find it or check $logPath for logs."