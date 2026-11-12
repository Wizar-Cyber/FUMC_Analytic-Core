# 08.01 | POC de agentes distribuidos en Azure

> Arquitectura objetivo y estado general: [`ProductionArchitecture.md`](./ProductionArchitecture.md). Estado de recursos: [`CloudDeploymentArchitecture.md`](./CloudDeploymentArchitecture.md), verificado el 2026-11-09.

## 1. Flujo de caso implementado en código

1. La API valida `DATA_MODE=synthetic` y contratos de caso con identificador `syn-`; el prefijo no es prueba de procedencia.
2. La API registra el lote en Azure Tables y Service Bus reparte el análisis académico, financiero/socioeconómico y de bienestar (lotes de 20 casos, del mayor al menor riesgo). Durable Functions se retiró del flujo: sus actividades no se indexaban en el host.
3. Cada worker usa Semantic Kernel y Azure OpenAI GPT-5-mini. RAG académico está apagado salvo configuración de un índice aprobado.
4. El sintetizador devuelve un objeto estructurado y conserva la probabilidad que recibió; no recalcula el score ni ejecuta acciones.
5. Cuando llegan las tres respuestas, el recolector ejecuta la síntesis; la propuesta se guarda en Blob con estado `pending_approval` y en Azure SQL. Un revisor autenticado puede decidir y, según la decisión, crear un seguimiento auditable.

Las llamadas contabilizan tokens de entrada/salida reportados por el servicio. El costo es una estimación con tarifas configuradas; no es una cuota ni un límite de gasto.

## 2. Seguridad y límites de datos

- Usa únicamente fixtures sintéticos; no enviar nombres, documentos, contactos, IDs institucionales ni notas clínicas.
- Entra/Easy Auth protege la app y el código valida además la allowlist `CASE_REVIEWER_ALLOWED_PRINCIPAL_IDS`.
- Verificación del 2026-11-12: las rutas anónimas devuelven `401` y un revisor autenticado obtiene `200`. Los `POST` desde el navegador requieren que el dominio esté en «Allowed external redirect URLs» de Easy Auth (protección CSRF).
- La salida LLM es apoyo revisable, no causalidad, diagnóstico ni decisión. El contenido recuperado es no confiable.
- No se envían comunicaciones, no se asigna ayuda automáticamente y no se ejecutan decisiones académicas/financieras.

## 3. Persistencia e integración

La POC guarda datos sintéticos, estado de lotes y propuestas en Azure Tables/Blob, y desde el 2026-11-12 escribe también en Azure SQL (predicción, propuesta, una fila por agente en `AgentExecution` y auditoría). La cohorte se puntuó con el endpoint Azure ML v2. Detalle y evidencia en [`E2EValidation.md`](./E2EValidation.md).

## 4. Estado de despliegue

Al 2026-11-12 la Function App `FUMCanalyticscore` (grupo `FUMC.CaseReviewer`, Brazil South, Flex Consumption, Python 3.11) está `Running`. El flujo de agentes por Service Bus se verificó con un usuario autenticado (lote de 20 casos: 20 procesados, 0 fallidos), la cohorte de 15.000 estudiantes está puntuada por el endpoint Azure ML v2 y la app escribe en Azure SQL. Evidencia en [`E2EValidation.md`](./E2EValidation.md).

No usar con datos reales. La conexión de AML, el uso de SQL por Functions, la prueba de usuario autorizada, Foundry evaluation, CI/CD empresarial y fuentes institucionales siguen pendientes según [los gates](./ProductionArchitecture.md#5-criterios-de-habilitación-institucional).

## 5. Cuándo aparecen los resultados GPT

La página y el refresco automático no llaman GPT. El dashboard agrega el score del modelo Azure ML v2 y las alertas por regla de riesgo. Para generar una propuesta hay que autenticarse como revisor permitido, tener casos pendientes y pulsar «Analizar casos prioritarios»: el lote toma hasta veinte casos, del mayor al menor riesgo, y los tres agentes trabajan en paralelo; no se garantiza que incluya el perfil abierto. Al completar, la propuesta queda en Blob y en Azure SQL, y el dashboard la muestra. Sin login, sin casos pendientes, con la POC pausada o si falla Service Bus/Identity/OpenAI, no aparece un resultado nuevo. Un lote de veinte casos produce hasta 80 llamadas de agente y síntesis (menos si se reutilizan respuestas guardadas por caso); el lote E2E del 2026-11-12 terminó en menos de un minuto.

## 5. Desarrollo local

Sigue [`azure/agent_platform/README.md`](../../azure/agent_platform/README.md). Usa Python 3.11, Core Tools v4, configuración local no versionada y recursos de desarrollo autorizados; iniciar la app local no crea infraestructura.
