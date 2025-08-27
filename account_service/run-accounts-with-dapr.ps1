$env:DAPR_API_TOKEN = "dapr-microservices-poc-token-2025"

dapr run `
  --app-id accounts-service `
  --app-port 8002 `
  --dapr-http-port 3502 `
  --dapr-grpc-port 50012 `
  --config ..\dapr\config\access-control.yaml `
  --components-path ./components `
  -- python -m app.main