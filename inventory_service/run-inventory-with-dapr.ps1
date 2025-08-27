$env:DAPR_API_TOKEN = "dapr-microservices-poc-token-2025"

dapr run `
  --app-id inventory-service `
  --app-port 8000 `
  --dapr-http-port 3500 `
  --dapr-grpc-port 50001 `
  --config ..\dapr\config\access-control.yaml `
  --components-path ./components `
  -- python -m app.main