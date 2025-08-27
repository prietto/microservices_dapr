$env:DAPR_API_TOKEN = "dapr-microservices-poc-token-2025"

dapr run `
  --app-id billing-service `
  --app-port 8001 `
  --dapr-http-port 3501 `
  --dapr-grpc-port 50002 `
  --config ..\dapr\config\access-control.yaml `
  --components-path ./components `
  -- python -m app.main