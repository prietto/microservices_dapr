Write-Host "=== Iniciando Payment Service ===" -ForegroundColor Green
Write-Host "Servicio: payment-service" -ForegroundColor Yellow
Write-Host "Puerto App: 5003" -ForegroundColor Yellow
Write-Host "Puerto Dapr HTTP: 3503" -ForegroundColor Yellow
Write-Host "Puerto Dapr gRPC: 55431" -ForegroundColor Yellow
Write-Host "=================================" -ForegroundColor Green
Write-Host ""

Set-Location -Path "PaymentService.Api"

if (-not (Test-Path "PaymentService.Api.csproj")) {
    Write-Host "ERROR: No se encontro PaymentService.Api.csproj" -ForegroundColor Red
    exit 1
}

$componentsPath = "..\dapr\components"
if (-not (Test-Path $componentsPath)) {
    Write-Host "ERROR: No se encontro la carpeta de componentes" -ForegroundColor Red
    exit 1
}

Write-Host "Restaurando dependencias..." -ForegroundColor Cyan
dotnet restore

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Fallo la restauracion" -ForegroundColor Red
    exit 1
}

Write-Host "Compilando proyecto..." -ForegroundColor Cyan
dotnet build

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Fallo la compilacion" -ForegroundColor Red
    exit 1
}

Write-Host "Iniciando Payment Service con Dapr..." -ForegroundColor Green

$env:DAPR_API_TOKEN = "dapr-microservices-poc-token-2025"

dapr run --app-id payment-service --app-port 5003 --dapr-http-port 3503 --dapr-grpc-port 55431 --config ..\..\dapr\config\access-control.yaml ` --resources-path ../dapr/components -- dotnet run --urls http://localhost:5003