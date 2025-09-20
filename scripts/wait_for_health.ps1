$up = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:8000/health -TimeoutSec 3
        if ($r.StatusCode -eq 200) { Write-Output "UP"; $up = $true; break }
    } catch {
        Start-Sleep -Seconds 1
    }
}
if (-not $up) { Write-Output "NOTUP"; exit 1 }
