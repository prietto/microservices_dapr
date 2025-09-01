[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "INICIANDO API GATEWAY SIN DAPR..." -ForegroundColor Green

# Activar entorno virtual
if (Test-Path "..\venv\Scripts\Activate.ps1") {
    & "..\venv\Scripts\Activate.ps1"
    Write-Host "Entorno virtual activado." -ForegroundColor Green
} else {
    Write-Host "No se encontró el entorno virtual en ..\venv\Scripts\Activate.ps1" -ForegroundColor Red
}

# Instalar dependencias si es necesario
if (Test-Path "requirements.txt") {
    pip install -q -r requirements.txt
}

# Ejecutar el API Gateway con Uvicorn en el puerto 8080
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload

Write-Host "API Gateway detenido." -ForegroundColor Red