# 08.01 | POC de agentes distribuidos en Azure

> Arquitectura objetivo y estado general: [`ProductionArchitecture.md`](./ProductionArchitecture.md). Estado de recursos: [`CloudDeploymentArchitecture.md`](./CloudDeploymentArchitecture.md), verificado el 2026-11-09.

## 1. Flujo de caso implementado en código

1. La API valida `DATA_MODE=synthetic` y contratos de caso con identificador `syn-`; el prefijo no es prueba de procedencia.
2. Durable Functions inicia la orquestación y Service Bus reparte el análisis académico, financiero/socioeconómico y de bienestar.
3. Cada worker usa Semantic Kernel y Azure OpenAI GPT-5-mini. RAG académico está apagado salvo configuración de un índice aprobado.
4. El sintetizador devuelve un objeto estructurado y conserva la probabilidad que recibió; no recalcula el score ni ejecuta acciones.
5. La propuesta se guarda en Blob con estado `pending_approval`; un revisor autenticado puede decidir y, según la decisión, crear un seguimiento auditable.

Las llamadas contabilizan tokens de entrada/salida reportados por el servicio. El costo es una estimación con tarifas configuradas; no es una cuota ni un límite de gasto.

## 2. Seguridad y límites de datos

- Usa únicamente fixtures sintéticos; no enviar nombres, documentos, contactos, IDs institucionales ni notas clínicas.
- Entra/Easy Auth protege la app y el código valida además la allowlist `CASE_REVIEWER_ALLOWED_PRINCIPAL_IDS`.
- Verificación viva del 2026-11-09: Functions está `Running`; requests anónimos a `/` y `/api/poc/status` devuelven `401`; `/.auth/login/aad` redirige (`302`) a Microsoft. El inicio interactivo y un `200` autenticado siguen pendientes.
- La salida LLM es apoyo revisable, no causalidad, diagnóstico ni decisión. El contenido recuperado es no confiable.
- No se envían comunicaciones, no se asigna ayuda automáticamente y no se ejecutan decisiones académicas/financieras.

## 3. Persistencia e integración

La POC guarda datos sintéticos, propuestas y controles en Azure Tables/Blob. Azure SQL está provisionado y `sql_schema.sql` está aplicado, pero el código de Functions aún no usa `src/persistence/sql_repository.py`. La probabilidad de demo la genera el Digital Twin; el flujo de casos no está conectado al endpoint Azure ML.

## 4. Estado de despliegue

`azure/agent_platform/infra/main.bicep` se desplegó como `satfumc-prod` con estado `Succeeded`. La Function App Linux/Flex Consumption `satfumcfunc0e83b2486979` usa Python 3.11 y tras publicación Core Tools v4/build remoto Azure indexó 33 funciones. Esto verifica aprovisionamiento y carga del host; no una corrida autenticada end-to-end.

No usar con datos reales. La conexión de AML, el uso de SQL por Functions, la prueba de usuario autorizada, Foundry evaluation, CI/CD empresarial y fuentes institucionales siguen pendientes según [los gates](./ProductionArchitecture.md#5-criterios-de-habilitación-institucional).

## 5. Cuándo aparecen los resultados GPT

La página y el refresco automático de 30 segundos no llaman GPT. El dashboard agrega score/riesgo del Digital Twin y alertas sintéticas por regla. Para generar una propuesta hay que autenticarse como revisor permitido, tener casos pendientes y confirmar explícitamente un lote de hasta cinco desde el Dashboard. Los casos se procesan por orden de antigüedad; no se garantiza que el lote incluya el perfil abierto. Al completar, los agentes/sintetizador guardan JSON en Blob y el dashboard lee las propuestas para mostrarlas. Sin login, sin casos pendientes, con la POC pausada o si falla Service Bus/Identity/OpenAI, no aparece un resultado nuevo.

## 5. Desarrollo local

Sigue [`azure/agent_platform/README.md`](../azure/agent_platform/README.md). Usa Python 3.11, Core Tools v4, configuración local no versionada y recursos de desarrollo autorizados; iniciar la app local no crea infraestructura.
