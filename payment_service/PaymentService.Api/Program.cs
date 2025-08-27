using Dapr.Client;
using PaymentService.Api.Models;
using Microsoft.AspNetCore.Mvc;

var builder = WebApplication.CreateBuilder(args);

// Add services
builder.Services.AddDaprClient();
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();

var app = builder.Build();

// Configure pipeline
if (app.Environment.IsDevelopment())
{
    app.UseSwagger();
    app.UseSwaggerUI();
}

app.UseCloudEvents();
app.MapSubscribeHandler();


app.MapPost("/payment-request", async (PaymentRequestEvent request, DaprClient daprClient, ILogger<Program> logger) =>
{
    try
    {
        logger.LogInformation("Received payment request. Starting processing...");

        // 🆕 DELAY AL INICIO - SIEMPRE, incluso para errores
        var startTime = DateTime.UtcNow;
        logger.LogInformation("⏱️  Starting 15-second payment processing simulation at {StartTime}...",
            startTime.ToString("HH:mm:ss.fff"));

        // SIMULAR DELAY DE PROCESAMIENTO (incluso para validaciones)
        for (int i = 1; i <= 15; i++)
        {
            await Task.Delay(1000); // 1 segundo
            if (i % 5 == 0) // Log cada 5 segundos
            {
                logger.LogInformation("⏱️  Processing... {Seconds}/15 seconds elapsed", i);
            }
        }

        var endTime = DateTime.UtcNow;
        var actualDelay = endTime - startTime;
        logger.LogInformation("✅ Payment processing delay completed at {EndTime}. Actual delay: {ActualDelay}ms",
            endTime.ToString("HH:mm:ss.fff"), actualDelay.TotalMilliseconds);

        // 🆕 AHORA HACER VALIDACIONES DESPUÉS DEL DELAY
        if (string.IsNullOrEmpty(request.InvoiceId))
        {
            logger.LogWarning("Payment processing failed: InvoiceId is null or empty");

            // Publicar evento de fallo DESPUÉS del delay
            await PublishPaymentFailedEvent(daprClient, logger, request, "InvoiceId is required");

            return Results.BadRequest("InvoiceId is required");
        }

        if (request.Amount <= 0)
        {
            logger.LogWarning("Payment processing failed: Invalid amount: {Amount}", request.Amount);

            await PublishPaymentFailedEvent(daprClient, logger, request, "Amount must be greater than zero");

            return Results.BadRequest("Amount must be greater than zero");
        }

        // Si llegamos aquí, los datos son válidos
        logger.LogInformation("Payment request validation passed for invoice: {InvoiceId}, amount: {Amount}",
            request.InvoiceId, request.Amount);

        // Simular procesamiento del pago
        var paymentResult = SimulatePayment(request.Amount);
        var transactionId = Guid.NewGuid().ToString();

        // Guardar estado del pago
        var paymentRecord = new PaymentResponse(
            Id: request.InvoiceId,
            Status: paymentResult,
            TransactionId: transactionId,
            Message: paymentResult == "approved" ? "Payment processed successfully" : "Payment rejected",
            ProcessedAt: DateTime.UtcNow
        );

        await daprClient.SaveStateAsync("statestore", $"payment-{request.InvoiceId}", paymentRecord);

        // Publicar eventos según resultado
        await PublishEventWithRetry(daprClient, logger, paymentResult, request, transactionId);

        logger.LogInformation("Payment completed for invoice {InvoiceId}, transaction: {TransactionId}",
            request.InvoiceId, transactionId);

        return Results.Ok();
    }
    catch (Exception ex)
    {
        logger.LogError(ex, "Error processing payment request for invoice {InvoiceId}", request?.InvoiceId ?? "unknown");

        // También publicar evento de fallo en caso de excepción
        await PublishPaymentFailedEvent(daprClient, logger, request, $"Payment processing error: {ex.Message}");

        return Results.Problem("Error processing payment");
    }
})
.WithTopic("rabbitmq-pubsub", "payment-request")
.WithName("ProcessPaymentRequest");


// NUEVA FUNCIÓN: Publicar evento de pago fallido
static async Task PublishPaymentFailedEvent(DaprClient daprClient, ILogger logger, PaymentRequestEvent request, string reason)
{
    try
    {
        var failedEvent = new
        {
            invoice_id = request?.InvoiceId ?? request?.OrderId ?? "unknown",
            order_id = request?.OrderId ?? request?.InvoiceId ?? "unknown",
            amount = request?.Amount ?? 0,
            customer_id = request?.CustomerId ?? "unknown",
            product_id = request?.ProductId ?? "unknown",
            reason = reason,
            error_details = $"Payment validation failed: {reason}",
            failed_at = DateTime.UtcNow,
            transaction_id = Guid.NewGuid().ToString()
        };

        await daprClient.PublishEventAsync("rabbitmq-pubsub", "payment-failed", failedEvent);
        logger.LogInformation("Published payment-failed event for invoice {InvoiceId} with reason: {Reason}",
            failedEvent.invoice_id, reason);
    }
    catch (Exception ex)
    {
        logger.LogError(ex, "Failed to publish payment-failed event");
    }
}



// Endpoint original para procesar pagos directamente
app.MapPost("/api/payment/process", async (PaymentRequest request, DaprClient daprClient, ILogger<Program> logger) =>
{
    try
    {
        logger.LogInformation("Processing payment for order: {OrderId}", request.OrderId);

        var response = new PaymentResponse(
            Id: request.Id,
            Status: SimulatePayment(request.Amount),
            TransactionId: Guid.NewGuid().ToString(),
            Message: "Payment processed successfully",
            ProcessedAt: DateTime.UtcNow
        );

        await daprClient.SaveStateAsync("statestore", $"payment-{response.Id}", response);
        await daprClient.PublishEventAsync("rabbitmq-pubsub", "payment-processed", response);

        logger.LogInformation("Payment {PaymentId} processed with status: {Status}", response.Id, response.Status);

        return Results.Ok(response);
    }
    catch (Exception ex)
    {
        logger.LogError(ex, "Error processing payment");
        return Results.Problem("Internal server error");
    }
})
.WithName("ProcessPayment");

// Obtener pago por ID
app.MapGet("/api/payment/{paymentId}", async (string paymentId, DaprClient daprClient, ILogger<Program> logger) =>
{
    try
    {
        var payment = await daprClient.GetStateAsync<PaymentResponse>("statestore", $"payment-{paymentId}");

        if (payment == null)
        {
            return Results.NotFound($"Payment {paymentId} not found");
        }

        return Results.Ok(payment);
    }
    catch (Exception ex)
    {
        logger.LogError(ex, "Error retrieving payment {PaymentId}", paymentId);
        return Results.Problem("Internal server error");
    }
})
.WithName("GetPayment");

// Health check
app.MapGet("/health", () => Results.Ok(new { status = "healthy", service = "payment-service" }))
.WithName("HealthCheck");

// Suscripción a order-created (existente)
app.MapPost("/api/payment/subscription/order-created", async (
    [FromBody] OrderCreatedEvent orderEvent,
    DaprClient daprClient,
    ILogger<Program> logger) =>
{
    logger.LogInformation("Received order created event for order: {OrderId}", orderEvent.OrderId);
    return Results.Ok();
})
.WithTopic("rabbitmq-pubsub", "order-created")
.WithName("OrderCreatedSubscription");

app.Run();

// Función auxiliar para publicar eventos con retry
static async Task PublishEventWithRetry(DaprClient daprClient, ILogger logger, string paymentResult, PaymentRequestEvent request, string transactionId)
{
    const int maxRetries = 3;
    
    for (int attempt = 1; attempt <= maxRetries; attempt++)
    {
        try
        {
            if (paymentResult == "approved")
            {
                var completedEvent = new
                {
                    invoice_id = request.InvoiceId,
                    order_id = request.OrderId,
                    transaction_id = transactionId,
                    amount = request.Amount,
                    currency = request.Currency,
                    customer_id = request.CustomerId,
                    processed_at = DateTime.UtcNow,
                    status = "completed"
                };

                await daprClient.PublishEventAsync("rabbitmq-pubsub", "payment-completed", completedEvent);
            }
            else
            {
                var failedEvent = new
                {
                    invoice_id = request.InvoiceId,
                    order_id = request.OrderId,
                    amount = request.Amount,
                    customer_id = request.CustomerId,
                    reason = "Payment rejected by payment processor",
                    error_details = "Insufficient funds or card declined",
                    failed_at = DateTime.UtcNow,
                    status = "failed"
                };

                await daprClient.PublishEventAsync("rabbitmq-pubsub", "payment-failed", failedEvent);
            }
            
            logger.LogInformation("Event published successfully on attempt {Attempt}", attempt);
            break; // Éxito, salir del loop
        }
        catch (Exception ex) when (attempt < maxRetries)
        {
            logger.LogWarning("Failed to publish event on attempt {Attempt}: {Error}", attempt, ex.Message);
            await Task.Delay(1000 * attempt); // Backoff exponencial
        }
        catch (Exception ex)
        {
            logger.LogError("Failed to publish event after {MaxRetries} attempts: {Error}", maxRetries, ex.Message);
            // No relanzar la excepción para evitar bucles
        }
    }
}

static string SimulatePayment(decimal amount)
{
    if (amount < 1000)
    {
        return "approved";
    }

    var random = new Random();
    return random.NextDouble() > 0.3 ? "approved" : "rejected";
}