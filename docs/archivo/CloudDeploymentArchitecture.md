# 10.02 | Estado de despliegue y arquitectura en Azure

> **Corte de verificación: 2026-11-09.** Este documento registra el resultado observado en Azure y separa el aprovisionamiento de infraestructura de la validación del flujo funcional autenticado.

## 1. Resumen ejecutivo

La infraestructura de la POC está desplegada. La Function App en uso es `FUMCanalyticscore` (grupo `FUMC.CaseReviewer`, Brazil South, Flex Consumption, Python 3.11), `Running`, publicada por zip deploy con compilación remota. El grupo `rg-sat-fumc-prod` del despliegue Bicep original sigue existiendo, pero ya no contiene la Function App.

El 2026-11-12 se verificó el flujo autenticado de punta a punta con datos sintéticos: sesión Entra con respuestas `200`, lote de agentes de 20 casos sin fallos y escritura en Azure SQL. Esto no equivale a un servicio institucional: no hay fuentes FUMC ni gobierno de datos aprobado. Evidencia en [`E2EValidation.md`](./E2EValidation.md).

## 2. Inventario verificado

| Recurso/capacidad | Identificador | Estado comprobado |
|---|---|---|
| Grupo de recursos | `FUMC.CaseReviewer` | Contiene la Function App en uso, Storage, Service Bus, Azure OpenAI y SQL |
| Function App | `FUMCanalyticscore` | `Running`; Linux; Python 3.11; Flex Consumption |
| Plan Functions | Flex Consumption (`FC1`) | Provisionado |
| Storage | `satfumcst8e039be1e4` | `Succeeded`; acceso HTTPS requerido |
| Key Vault | `satfumckvea1ada48` | `Succeeded`; autorización RBAC |
| Service Bus | Namespace de la POC | `Succeeded`; colas definidas en Bicep |
| Azure OpenAI | Cuenta de la POC / `sat-gpt5-mini` | Cuenta y deployment `Succeeded` |
| Azure SQL | Servidor `satfumc-sql-fumc01`; base `SATFUMCOperational` | Base `Online`, nivel serverless General Purpose (`GP_S_Gen5`, 1 vCore, autopausa 60 min); diez tablas del esquema aplicadas y verificadas |
| Application Insights / Log Analytics | Componentes de la POC | Provisionados |

Los nombres identifican recursos de esta POC; no incluyen tokens ni contraseñas. Los secretos se mantienen fuera del repositorio, en Key Vault. No copiar valores de configuración segura a documentación, issues o logs.

## 3. Estado real de las integraciones

### 3.1. Functions, agentes y SPA

El código publicado contiene la API y la SPA, el flujo de lotes sobre Service Bus y Azure Tables, los workers de agentes y los temporizadores `batch_reaper` y `cache_warmer`. Quedan cuatro actividades Durable heredadas que fallan al indexarse y ya no se usan. La configuración de Easy Auth requiere autenticación Entra y el código aplica además la allowlist de revisores.

Comprobaciones HTTP anónimas:

| Ruta | Respuesta | Interpretación |
|---|---:|---|
| `/` | `401` | Acceso anónimo bloqueado; no prueba que una sesión autenticada cargue la SPA |
| `/api/poc/status` | `401` | Acceso de API anónimo bloqueado, comportamiento esperado |
| `/.auth/login/aad` | `302` | Redirección a `login.microsoftonline.com`; no prueba el callback ni una respuesta autorizada |

La aceptación final de la app requiere abrir el login con una cuenta autorizada, completar Entra y comprobar la SPA/API con un `200`. Esa prueba no se pudo completar desde la sesión de despliegue.

### 3.2. Azure SQL

`azure/agent_platform/infra/sql_schema.sql` se aplicó a `SATFUMCOperational`. Se comprobaron estas diez tablas: `SchemaVersion`, `ModelRelease`, `StudentSnapshot`, `Prediction`, `AgentExecution`, `ReviewProposal`, `HumanDecision`, `Intervention`, `OutcomeTarget` y `AuditEvent`.

El esquema y la base existen, pero la Function App **todavía persiste en Azure Tables/Blob**. `src/persistence/sql_repository.py` no está integrado en las rutas/servicios de Functions ni se validó una escritura operacional desde la aplicación.

### 3.3. Azure Machine Learning

El repositorio contiene jobs, scoring scripts y manifiestos de endpoint AML. La POC distribuida **no envía sus snapshots al endpoint AML**: la probabilidad de sus datos de demo se genera en el Digital Twin. El estado actual de un endpoint AML independiente no forma parte de esta verificación; no debe inferirse a partir de que existan YAML o scripts.

## 4. Arquitectura: actual y objetivo

```mermaid
flowchart LR
    AML[Azure ML · modelo v2] -->|score de la cohorte| TB
    P[POC Functions] --> TB[Azure Tables / Blob]
    P --> SB[Service Bus]
    SB --> AG[Workers Semantic Kernel]
    AG --> OAI[Azure OpenAI GPT-5-mini]
    P --> AUTH[Easy Auth / Entra]
    AUTH --> UI[SPA protegida]
    AG --> SQL[Azure SQL · auditoría]
```

La arquitectura objetivo de ramas paralelas, un snapshot común y consolidación SQL se documenta en [`ProductionArchitecture.md`](./ProductionArchitecture.md). El diagrama de arriba refleja la integración verificada el 2026-11-12.

## 5. Comandos de comprobación

Ejecutar desde una sesión Azure CLI con la suscripción correcta; no pasar secretos en línea:

```powershell
az deployment group show -g rg-sat-fumc-prod -n satfumc-prod --query properties.provisioningState -o tsv
az functionapp show -g FUMC.CaseReviewer -n FUMCanalyticscore --query state -o tsv
az functionapp function list -g FUMC.CaseReviewer -n FUMCanalyticscore --query "[].name" -o table
az sql db show -g FUMC.CaseReviewer -s satfumc-sql-fumc01 -n SATFUMCOperational --query status -o tsv
```

Las solicitudes anónimas a rutas protegidas deben ser rechazadas. Las pruebas autenticadas deben realizarse con usuario de prueba autorizado y no deben registrar tokens.

## 6. Advertencias, seguridad y costo

- Bicep produjo `BCP187` sobre `sku` en la definición SQL. ARM terminó `Succeeded` y SQL aparece `Online`; conviene revisar el schema Bicep/API, pero el warning no fue el resultado final del despliegue.
- La POC permanece en `DATA_MODE=synthetic`. No está autorizada para datos FUMC.
- La existencia de Azure SQL no significa que Functions lo use; la existencia de recursos AML tampoco significa que la aplicación esté conectada.
- Functions, SQL serverless, Service Bus, Storage, Key Vault, Application Insights y Azure OpenAI pueden generar costos. Pausar la Function App no elimina todos los cargos; antes de borrar, exportar el esquema/estado necesario.
- Revisa [`Azure-Integration-and-Shutdown-Guide.md`](./Azure-Integration-and-Shutdown-Guide.md) antes de detener o eliminar recursos y [`ProductionReadiness.md`](./ProductionReadiness.md) antes de solicitar uso institucional.
