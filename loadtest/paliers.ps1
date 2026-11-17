param(
    [string]$HostUrl = "http://127.0.0.1:8000",
    [string]$ResultsDirectory = "locust-results\tp5-saturation",
    [int[]]$Plateaus = @(10, 25, 50, 100, 150),
    [string]$Duration = "2m",
    [int]$SpawnRate = 10
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command locust -ErrorAction SilentlyContinue)) {
    throw "Locust is not available in PATH. Install requirements-dev.txt first."
}

$ready = Invoke-WebRequest -Uri "$HostUrl/ready" -UseBasicParsing
if ($ready.StatusCode -ne 200) {
    throw "The API readiness check returned HTTP $($ready.StatusCode)."
}

New-Item -ItemType Directory -Force -Path $ResultsDirectory | Out-Null

Write-Host "Running one-minute warm-up..."
locust --headless --locustfile locustfile.py --host $HostUrl `
    --users 5 --spawn-rate 5 --run-time 1m --only-summary
if ($LASTEXITCODE -ne 0) {
    throw "The warm-up campaign failed with exit code $LASTEXITCODE."
}

foreach ($users in $Plateaus) {
    $prefix = Join-Path $ResultsDirectory ("users-{0}" -f $users)
    Write-Host "Running plateau with $users users..."
    locust --headless --locustfile locustfile.py --host $HostUrl `
        --users $users --spawn-rate $SpawnRate --run-time $Duration `
        --csv $prefix --html "$prefix.html"
    if ($LASTEXITCODE -ne 0) {
        throw "The plateau with $users users failed with exit code $LASTEXITCODE."
    }
}

python loadtest\summary.py --results-dir $ResultsDirectory
