dapr run `
  --app-id inventory-service `
  --app-port 8000 `
  --dapr-http-port 3500 `
  --dapr-grpc-port 50001 `
  --components-path ./components `
  -- python -m app.main