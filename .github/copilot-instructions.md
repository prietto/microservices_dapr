# Instrucciones de Copilot para Agentes de Codificación IA

## Descripción General del Proyecto
Este repositorio implementa una arquitectura de microservicios usando Dapr para la comunicación entre servicios. Contiene varios servicios basados en Python y un servicio .NET, cada uno con su propio dominio y base de datos. Los sidecars de Dapr se utilizan para pub/sub, gestión de estado e invocación de servicios.

## Componentes Principales
- **account_service/**: Gestiona cuentas de clientes. Archivos clave: `app/main.py`, `app/service/customer_service.py`.
- **billing_service/**: Maneja facturación y facturas. Archivos clave: `app/main.py`, `app/services/invoice_service.py`.
- **inventory_service/**: Gestiona artículos de inventario y categorías. Archivos clave: `app/main.py`, `app/services/inventory_service.py`.
- **api_gateway/**: Gateway Python FastAPI para enrutamiento, autenticación y agregación. Archivos clave: `app/main.py`, `app/services/dapr_client.py`.
- **payment_service/**: API de pagos basada en .NET. Archivo clave: `PaymentService.Api/Program.cs`.

## Comunicación e Integración
- **Dapr**: Todos los servicios usan Dapr para pub/sub (RabbitMQ), almacén de estado e invocación de servicios. Las configuraciones de componentes Dapr están en carpetas `dapr/components/` y `components/`.
- **Bases de Datos**: Cada servicio tiene su propia BD SQLite (ej. `billing.db`, `inventory.db`).
- **API Gateway**: Maneja autenticación JWT y enruta solicitudes a servicios backend vía Dapr.

## Flujos de Trabajo del Desarrollador
- **Ejecutar Servicios**: Usa los scripts PowerShell proporcionados (ej. `run-accounts-with-dapr.ps1`, `run-billing-with-dapr.ps1`) para iniciar cada servicio con Dapr.
- **Servicio .NET**: Usa `run-payment-with-dapr.ps1` para el servicio de pagos.
- **Pruebas**: No hay ejecutor unificado de pruebas; prueba cada servicio individualmente. (No se detectaron archivos de prueba.)
- **Dependencias**: Dependencias Python en `requirements.txt`. Dependencias .NET en `PaymentService.Api/`.

## Convenciones del Proyecto
- **Estructura de Servicios**: Cada servicio tiene `app/` con subcarpetas: `api/`, `core/`, `models/`, `schemas/`, `services/`.
- **Versionado de API**: Endpoints REST versionados bajo `api/v1/`.
- **Configuración**: Configuraciones de servicios en `core/config.py` o `appsettings.json` (para .NET).
- **Autenticación**: Manejo JWT en `api_gateway/app/auth/jwt_handler.py`.

## Patrones y Ejemplos
- **Dapr Pub/Sub**: Ver `components/rabbitmq-pubsub.yaml` y scripts de inicio de servicios para configuración pub/sub.
- **Invocación de Servicios**: Usar APIs HTTP/gRPC de Dapr; ver `api_gateway/app/services/dapr_client.py` para uso.
- **Acceso a Base de Datos**: Cada servicio usa su propio módulo BD (ej. `db.py`, `database.py`).

## Dependencias Externas
- **Dapr**: Requerido para toda comunicación entre servicios.
- **RabbitMQ**: Usado para pub/sub vía Dapr.
- **SQLite**: BD local para cada servicio.

## Consejos para Agentes IA
- Siempre usar Dapr para llamadas entre servicios.
- Seguir la estructura de carpetas y convenciones de nomenclatura para nuevos servicios.
- Referenciar los scripts PowerShell proporcionados para inicio correcto de servicios.
- Actualizar YAMLs de componentes Dapr para nuevas necesidades de pub/sub o almacén de estado.

---
Edita este archivo para mantener las instrucciones actualizadas conforme evoluciona la arquitectura.
