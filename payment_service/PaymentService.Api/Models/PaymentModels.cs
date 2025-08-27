// Esta línea dice: "Este archivo pertenece al espacio de nombres PaymentService.Api.Models"
// Es como decir "esta clase vive en esta carpeta virtual"
namespace PaymentService.Api.Models;

// PRIMER MODELO: PaymentRequest (Solicitud de Pago)
// "record" es como una "class" pero más simple para datos
// Los paréntesis contienen los datos que SIEMPRE necesitas enviar
public record PaymentRequest(
    string OrderId,        // ID del pedido (texto)
    decimal Amount,        // Cantidad de dinero (número con decimales)
    string Currency = "USD",      // Moneda (por defecto USD)
    string PaymentMethod = "credit_card",  // Método de pago (por defecto tarjeta)
    string CustomerId = ""        // ID del cliente (por defecto vacío)
)
{
    // Estas son propiedades AUTOMÁTICAS que se crean solas:
    public string Id { get; init; } = Guid.NewGuid().ToString();  // ID único automático
    public DateTime CreatedAt { get; init; } = DateTime.UtcNow;   // Fecha actual automática
}

// SEGUNDO MODELO: PaymentResponse (Respuesta del Pago)
// Este es lo que devuelve el servicio después de procesar el pago
public record PaymentResponse(
    string Id,              // ID del pago
    string Status,          // Estado: "approved", "rejected", "pending"
    string TransactionId,   // ID de la transacción bancaria
    string Message,         // Mensaje descriptivo
    DateTime ProcessedAt    // Cuándo se procesó
);

// TERCER MODELO: OrderCreatedEvent (Evento de Pedido Creado)
// Este es para recibir notificaciones cuando se crea un pedido
public record OrderCreatedEvent(
    string OrderId,         // ID del pedido
    string CustomerId,      // ID del cliente
    decimal TotalAmount,    // Monto total
    DateTime CreatedAt      // Cuándo se creó
);



public record PaymentRequestEvent(
    string InvoiceId,
    string OrderId,
    decimal Amount,
    string CustomerId,
    string ProductId,
    string Currency,
    string Description,
    string RequestedBy
);