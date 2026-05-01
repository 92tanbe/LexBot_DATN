$root = $PSScriptRoot
if (-not $root) {
    $root = (Get-Location).Path
}

$chatbotDir = Join-Path $root "chatbot"
$backendDir = Join-Path $root "backend"
$frontendDir = Join-Path $root "frontend"

Write-Host "Repo root: $root"
Write-Host ""

Write-Host "Starting Chatbot on port 8001..."
Write-Host "  -> cd `"$chatbotDir`"; uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload"
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location `"$chatbotDir`"; if (-not (Test-Path .\venv\Scripts\Activate.ps1)) { Write-Error 'Thieu chatbot\\venv. Chay: python -m venv venv va pip install -r requirements.txt'; exit 1 }; .\venv\Scripts\Activate.ps1; uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload"
)

Write-Host "Starting Backend on port 8000..."
Write-Host "  -> cd `"$backendDir`"; uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location `"$backendDir`"; if (-not (Test-Path .\venv\Scripts\Activate.ps1)) { Write-Error 'Thieu backend\\venv. Chay: python -m venv venv va pip install -r requirements.txt'; exit 1 }; .\venv\Scripts\Activate.ps1; uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
)

Write-Host "Starting Frontend on port 5173..."
Write-Host "  -> cd `"$frontendDir`"; npm run dev"
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location `"$frontendDir`"; if (-not (Test-Path .\node_modules)) { Write-Warning 'Chua co node_modules. Chay: npm install truoc khi npm run dev' }; npm run dev"
)

Write-Host ""
Write-Host "All services started in separate windows!"
