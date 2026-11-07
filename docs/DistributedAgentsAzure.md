# Agentes distribuidos en Azure — estado de la POC

## Alcance implementado en el repositorio

La app aislada [azure/agent_platform](../azure/agent_platform/README.md) agrega
una arquitectura asíncrona con Azure Functions y Durable Functions:

1. `POST /api/cases` valida un caso sintético, reserva un cupo del piloto y
   crea una orquestación durable. La UI protegida estática está en
   `azure/agent_platform/static/`.
2. La orquestación publica dos mensajes independientes en Azure Service Bus.
3. El agente socioeconómico y el agente académico trabajan en paralelo. El
   segundo consulta Azure AI Search y solo puede citar documentos recuperados.
4. El sintetizador conserva la probabilidad producida por el modelo tabular y
  genera una recomendación estructurada, validada por contrato.
5. El resultado se guarda en Blob Storage con estado `generated` y se muestra
  automáticamente en el dashboard y el perfil después del lote. No hay paso
  de aprobación humana para visualizar resultados en el modo de demo.
6. Las alertas y seguimientos simulados se guardan en Azure Tables con estado e
  historial. Sus controles no envían comunicaciones ni realizan cambios
  académicos o financieros. Una futura integración institucional requiere
  controles y aprobación institucional antes de cualquier intervención.

Semantic Kernel proporciona el tipo `ChatCompletionAgent`; Durable Functions
controla la coordinación persistente y Service Bus distribuye el trabajo. No se
usan los patrones de orquestación multiagente experimentales de Semantic Kernel
para el flujo institucional.

El contrato de entrada excluye campos de nombres, correo, teléfono e
identificadores institucionales; durante esta POC exige `DATA_MODE=synthetic` y
`case_id` con prefijo `syn-`. Esas son barreras de configuración, no una prueba
de procedencia: el operador debe alimentar exclusivamente fixtures generados.
El identificador de caso no se incluye en el prompt enviado al modelo. El score
ML es inmutable en el flujo LLM. Una respuesta mal formada, cita no recuperada
o error de integración falla explícitamente; no se sustituye por una respuesta
de éxito.

## Preflight confirmado y bloqueos pendientes

- **Estado Azure actualizado:** se creó la cuenta AI Services `satfumcai94035`
  en Brazil South y el deployment `sat-gpt5-mini` (`gpt-5-mini`,
  `2025-08-07`, GlobalStandard). El deployment está `Succeeded`, con capacidad
  5; aún no se ha enviado ninguna solicitud de inferencia ni se han creado
  Search, Service Bus, Function App, colas, contenedor de revisiones o
  autenticación de revisores.
- La disponibilidad regional consultada para `gpt-4o-mini` / `GlobalStandard`
  (versión `2024-07-18`) incluye Brazil South. Tras registrar el proveedor con
  autorización, la cuota de `Tokens Per Minute - GPT-4o-mini - GlobalStandard`
  es **0 usados / 0 asignados**. La suscripción puede crear como máximo una
  cuenta Cognitive Services S0 (0/1 usada), pero no capacidad para ese modelo.
- **Preflight confirmado:** GPT-5-mini GlobalStandard, versión `2025-08-07`,
  dispone de **500.000 TPM (0 usados)** en Brazil South y admite Chat
  Completions. La POC Azure Students autorizada usa exclusivamente ese modelo,
  sin tarjeta ni formulario/aumento de cuota.
- El código usa API `2025-04-01-preview` para GPT-5, `max_completion_tokens` y
  omite `temperature`. La versión API y el comportamiento para otros modelos
  configurados permanecen independientes.
- El alcance autorizado fija un máximo técnico de **10.000 evaluaciones** para
  el piloto y **una sola evaluación activa**. La UI solo inicia una solicitud
  manual a la vez; el primer smoke test debe ser un caso sintético generado,
  seguido de pausa e inspección. No se carga un lote al iniciar/desplegar.
- La cuota TPM confirmada no es un límite de gasto. El código contabiliza el
  uso real de entrada/salida de las tres llamadas y estima USD con tarifas
  configuradas. No se afirma que Azure tenga un hard cap de costo; los
  presupuestos de Azure solo notifican.
- `o4-mini` tiene 100.000 TPM disponibles, pero el catálogo lo marca como
  **Deprecated**; no se recomienda iniciar una integración nueva con ese modelo.
- `text-embedding-3-small` tiene 1.000.000 TPM disponibles; sirve para
  embeddings/RAG, no sustituye al modelo generativo de los agentes.
- Se había preparado una solicitud de 10.000 TPM para `gpt-4o-mini`, pero no se
  envió. Queda **cancelada/no necesaria** si se elige GPT-5-mini; no completar
  el cuestionario de aumento de cuota para este camino.
- Los proveedores `Microsoft.CognitiveServices`, `Microsoft.Search`,
  `Microsoft.ServiceBus` y `Microsoft.Web` aparecen `Registered`. El único
  recurso nuevo verificado para esta POC es la cuenta/deployment de GPT-5-mini
  descritos arriba; no se modificaron el Storage, Key Vault, Application
  Insights ni el workspace ML existentes.
- Se añadió [IaC Bicep](../azure/agent_platform/infra/README.md) para Flex
  Consumption, Service Bus Standard, almacenamiento dedicado, colas, roles de
  identidad y Easy Auth. `bicep build` pasó; no se ha ejecutado What-If ni se
  aprovisionaron esos recursos. El template requiere un registro Entra existente
  y su secreto, y sigue sujeto a revisión de costo y despliegue.
- La política de la suscripción permite Brazil South; la consulta regional
  reportó disponibilidad para Functions, Storage y Service Bus. El template
  crea almacenamiento separado para evitar conceder al agente acceso al
  Storage de analítica existente. No se conectaron datos institucionales.
- No aparece un recurso de Azure AI Search existente. La cuota permite **1
  Search Free (0 usadas)** en la suscripción y hasta 16 Basic. Free está
  disponible según la tarifa regional; sigue sujeto a sus límites de 50 MB y 3
  índices.
- El grupo de recursos ya contiene Storage, Key Vault, Application Insights y
  Azure ML en Brazil South. El template reutiliza Application Insights pero crea
  Storage dedicado para Durable Functions, paquetes y revisiones; el costo de
  transacciones/GB y retención de logs aún depende del uso y configuración.
- Azure Retail Prices API devolvió tarifas para Search, Service Bus y Functions
  (detalladas abajo), pero no para los modelos. Foundry muestra precios
  orientativos para GPT-5-mini (detallados abajo); se deben confirmar en el
  portal antes de usarlo. Storage, conexiones y el uso real de Functions siguen
  pendientes de medición. Un Azure Budget solo notifica; no detiene
  automáticamente el consumo.
- No se identificó un reglamento estudiantil autorizado en el repositorio ni
  se configuró el índice RAG. El RAG queda deshabilitado por defecto; el agente
  académico solo analiza señales sintéticas hasta que exista un índice
  aprobado con `id`, `title`, `source_uri`, `section` y `content`.
- No existe contrato, credencial ni autorización para conectarse al SIS, LMS,
  pagos o bienestar. No se debe inferir que un endpoint del modelo accede a esas
  fuentes en tiempo real.
- No están configurados el registro de aplicación/rol de revisor, Teams,
  Microsoft Graph, Power Automate ni un workspace/licencia Power BI institucional.
- La UI no debilita la seguridad si Entra no está configurado: no se envían
  claves de Functions desde el navegador y la API muestra bloqueo hasta que
  App Service Authentication y el rol de revisor estén implementados y
  verificados. El hosting debe proteger todas las rutas API y enrutar `/api`
  desde el mismo origen o un proxy servidor-a-servidor.
- El dashboard HTML y las exportaciones actuales pertenecen al pipeline batch
  determinístico; no son todavía una visualización en tiempo real de las
  decisiones de esta nueva app.

Antes del primer smoke test, el responsable debe comprobar saldo y elegibilidad
vigentes en Azure Education Hub/Cost Management, terminar el aprovisionamiento
de aplicación tras revisar What-If, y validar Entra, roles, red y almacenamiento.
La cuenta/modelo ya están creados, pero no se ha llamado al modelo. Azure for
Students no requiere tarjeta para el uso aprobado, pero un Azure Budget no
detiene automáticamente el consumo.

### Alternativa de modelo con cuota existente

La ficha de modelo de GPT-5-mini muestra para Global Standard precios
orientativos de USD 0,25 por millón de tokens de entrada y USD 2,00 por millón
de tokens de salida. La API minorista no corroboró el precio por modelo; la
plantilla configura esas tarifas para estimaciones, que deben confirmarse en
Azure. No son un tope de consumo.

Con el supuesto de 1.000 tokens de entrada y 300 de salida **por cada una de
las tres llamadas** del flujo actual:

- 1.000 evaluaciones: aproximadamente **USD 2,55** en tokens.
- 10.000 evaluaciones (límite técnico del piloto): aproximadamente
  **USD 25,50** solo bajo el mismo supuesto de tokens.
- 27.975 filas del snapshot: aproximadamente **USD 71,34** si hipotéticamente
  cada fila generara tres llamadas. La app no ingiere este Parquet y el piloto
  no permite más de 10.000 evaluaciones.
- 35.000 evaluaciones: aproximadamente **USD 89,25** solo en tokens, casi todo
  el crédito anual de USD 100, sin infraestructura ni margen para prompts/RAG
  más grandes.
- 100 evaluaciones: aproximadamente **USD 0,26** en tokens, útil como primera
  prueba de costo/latencia, no como garantía de costo final.

Las 27.975 filas son longitudinales, no casos independientes de inferencia, y
no deben enviarse al LLM. No existe ruta de ingesta batch:
cada evaluación empieza por una acción manual. El primer smoke test es un
único caso sintético generado y después se pausa para inspeccionar el resultado.
El límite de 10.000 no es una meta de volumen ni habilita el uso de datos
institucionales. El modo demo muestra recomendaciones automáticamente; no
ejecuta decisiones ni intervenciones sobre estudiantes reales.

Los endpoints Serverless API de modelos de partners requieren un método de pago
válido; las suscripciones Free/Trial no son elegibles. Evitar esa ruta para no
añadir una tarjeta ni depender de ofertas de Marketplace. La [documentación de
Azure for Students](https://learn.microsoft.com/azure/education-hub/about-azure-for-students)
confirma USD 100 de crédito sin tarjeta; la [ficha de despliegue de
GPT-5-mini](https://ai.azure.com/explore/models/gpt-5-mini/version/2025-08-07/registry/azure-openai/)
y la [guía de cuotas](https://learn.microsoft.com/azure/foundry/openai/quotas-limits)
son referencias para verificar elegibilidad, cuota y precio al desplegar.

## Estimación de tokens compartida

Con los precios proporcionados para GPT-4o mini Global Standard —USD 0,15 por
millón de tokens de entrada, USD 0,60 por millón de salida y USD 0,075 por
millón de entrada en caché—, el flujo actual hace **tres llamadas LLM por caso**
(dos agentes y un sintetizador). Si cada llamada usa 1.000 tokens de entrada y
300 de salida, el costo de tokens sería:

- 1.000 casos: 3 millones de entrada × USD 0,15 + 0,9 millones de salida ×
  USD 0,60 = **USD 0,99**.
- 27.975 casos hipotéticos del Digital Twin: aproximadamente **USD 27,70 solo
  en tokens**, bajo el precio compartido para GPT-4o mini; no corresponde al
  modelo activo ni al límite de evaluaciones del piloto.

La estimación de USD 0,33 por 1.000 casos corresponde a una llamada por caso;
no incluye los dos análisis especializados y la síntesis de esta arquitectura.
Los prompts RAG y la síntesis pueden superar 1.000 tokens de entrada, por lo
que hay que medir tokens reales antes de aceptar el presupuesto. No se cuenta
con descuento por caché hasta confirmar que los tokens del prefijo sean
elegibles. El Batch API oficial ofrece 50% de descuento para cargas Global
Standard con respuesta de hasta 24 horas, pero esta app publica solicitudes
interactivas por Service Bus y no usa dicho API. Estos valores no incluyen
Functions, Service Bus, Search ni almacenamiento. El código limita la
recuperación a tres documentos con extractos acotados, limita la salida a 512
tokens por agente y 768 para síntesis, y limita reintentos del cliente. Esos
controles acotan cada llamada. La app conserva los tokens realmente reportados
por cada llamada en la propuesta y calcula el costo estimado a partir de las
tarifas configuradas. El contador durable impide superar 10.000 evaluaciones
aceptadas en este piloto y limita la concurrencia a una, pero no fija un hard
cap monetario ni incluye costos de infraestructura.

La tarifa de GPT-4o-mini se conserva como dato compartido por el usuario. La
plantilla de la app configura las tarifas orientativas de GPT-5-mini
(USD 0,25/1M entrada y USD 2,00/1M salida). La UI identifica el cálculo como
estimado; no reemplaza una cotización de Azure ni detiene consumo.

## Tarifas de infraestructura consultadas

La Retail Prices API pública de Azure sí devolvió estos valores para Brazil
South:

| Servicio/SKU | Tarifa minorista publicada | Implicación para esta POC |
|---|---:|---|
| Azure AI Search Free | USD 0/h | Cuota confirmada: 1 servicio disponible; límite Free de 50 MB/3 índices. |
| Azure AI Search Basic | USD 0,133/h (≈ USD 97,09 por 730 h) | No cabe junto con la evaluación hipotética de las 27.975 filas usando GPT-5-mini dentro de USD 100. No desplegar Basic para esta POC. |
| Service Bus Basic | USD 0,05 por millón de operaciones | Menor precio, menos capacidades de broker para un diseño resiliente. |
| Service Bus Standard | USD 10/mes de base, más aprox. USD 0,20–0,80 por millón de operaciones | Aproximadamente USD 10 de base por namespace/mes; el volumen de mensajes añade poco en el supuesto de POC. |
| Functions Flex Consumption (FC1) | La consulta actual de la SKU exacta en Brazil South no devolvió precio | El costo depende de ejecuciones y GB-s; no se asume un grant gratuito. Confirmar con Azure Pricing Calculator/portal. |
| Storage Standard_LRS dedicado | La consulta actual de la SKU exacta en Brazil South no devolvió precio | Faltan costos de capacidad, transacciones y retención; confirmar antes de desplegar. |

Con el límite de 10.000 evaluaciones, el subtotal ilustrativo conocido es
USD 25,50 de tokens GPT-5-mini + USD 10 de base de Service Bus Standard + menos
de USD 1 de operaciones de Service Bus. Functions Flex Consumption y el
Storage dedicado quedan adicionales y sin estimación hasta confirmar sus
precios y uso. Evaluar las 27.975 filas costaría cerca de USD 71,34 solo en
tokens y no está permitido por el límite del piloto. Ninguna estimación incluye
almacenamiento, GB-s, conexiones brokered, tokens por encima de la hipótesis,
otros recursos de Foundry ni impuestos/condiciones de Azure for Students;
tampoco es una cotización ni un hard cap de USD 100. Si se requiere Search
Basic, añade alrededor de USD 97/mes.

El template usa Flex Consumption FC1, no el plan clásico Consumption; por tanto,
no se deben aplicar a esta infraestructura los precios/grants clásicos de
Functions consultados anteriormente. La consulta minorista actual no devolvió
precios para FC1 ni Standard_LRS en Brazil South. La disponibilidad regional
reportada no confirma precio ni headroom del crédito. Service Bus Standard es
la SKU fijada en el template; cualquier cambio a Basic requiere revisar las
capacidades y garantías del broker.

## Configuración e identidad

`local.settings.example.json` es una plantilla sin claves. La app usa
`DefaultAzureCredential` y se espera que en Azure se asigne Managed Identity.
Roles mínimos de datos:

| Componente | Acceso necesario |
|---|---|
| Azure OpenAI | Cognitive Services OpenAI User sobre el recurso aprobado |
| Azure AI Search | Search Index Data Reader sobre el servicio/índice, solo si se habilita RAG |
| Service Bus | Data Sender y Data Receiver en el namespace |
| Storage dedicado de Function App | Storage Blob Data Owner, Storage Queue Data Contributor y Storage Table Data Contributor |

El endpoint de aprobación solo acepta un principal de App Service Authentication
que incluya el valor de rol indicado en `CASE_REVIEWER_ROLE_VALUE`. Antes de habilitarlo, TI
debe configurar Entra ID, asignaciones de rol, exposición privada y pruebas de
acceso no autorizado. La clave de Functions no sustituye la identidad del
revisor. El endpoint permanece deshabilitado hasta que
`REVIEWER_AUTH_ENFORCED=true` se configure explícitamente después de validar
App Service Authentication.

En Azure, configurar Durable Functions Storage con la identidad administrada
del Function App (`AzureWebJobsStorage__accountName` para la cuenta existente)
y asignar los roles de Blob, Queue y Table requeridos por el proveedor Durable.
El ejemplo local usa Azurite; no contiene credenciales de Azure.

## Fuente en tiempo real y visualización

Una conexión en tiempo real solo es posible si el sistema fuente ofrece API,
CDC o eventos autorizados, con latencia y semántica acordadas. La siguiente
integración debe definir ese contrato con el propietario del SIS/LMS; no se
deben leer bases institucionales directamente ni pasar atributos personales a
la cola o al modelo antes de la revisión de privacidad y seguridad.

Para la primera POC se recomienda un corte sintético batch. El reporte agregado
actual sirve para revisar scores de ese pipeline, no para auditar propuestas
LLM. Antes de conectar Power BI a revisiones, se necesita una proyección
agregada con mínimo de cohorte, control de acceso y reconciliación con Blob. No
exponer prompts, notas de aprobación ni detalles por estudiante en un dataset
de Power BI general.

## Verificación local

Desde la raíz, las pruebas del contrato no necesitan credenciales ni recursos
Azure:

```powershell
pytest -q tests/test_distributed_agent_contracts.py
```

Para probar el host local se requiere Functions Core Tools v4, Azurite y
recursos de desarrollo aprobados. Copiar el ejemplo a `local.settings.json`;
no incluir ese archivo en commits. El manifiesto Bicep de la POC compila y está
en [azure/agent_platform/infra](../azure/agent_platform/infra/README.md); el
What-If y el despliegue siguen pendientes de la revisión de costos y de contar
con el registro/rol Entra autorizado y el secreto suministrado por un canal
seguro.

## Criterios para promover más allá de POC

1. Fuente SIS/LMS aprobada, propósito, SLA, base legal, minimización y retención
   documentados por la Universidad.
2. Reglamento autorizado, indexado con citas verificables y evaluación de
   recuperación/actualización.
3. Evaluación del modelo y prompts con conjunto versionado; pruebas de sesgo,
   calibración, falsos positivos/negativos, inyección en documentos y salidas
   JSON inválidas.
4. Identidad Entra, roles de revisor, auditoría, red privada y controles de
   operación revisados por TI/seguridad.
5. Pruebas de carga, fallos de cola, reintentos, DLQ, idempotencia,
   recuperación durable y retención aprobadas.
6. Power BI agregado aprobado y conciliado. La decisión final y toda
   intervención siguen bajo responsabilidad humana.

## Referencias oficiales

- [Precios de Azure OpenAI](https://azure.microsoft.com/pricing/details/azure-openai/)
- [Precios de Azure AI Search](https://azure.microsoft.com/pricing/details/search/)
- [Precios de Azure Functions](https://azure.microsoft.com/pricing/details/functions/)
- [Precios de Service Bus](https://azure.microsoft.com/pricing/details/service-bus/)
- [Batch API de Azure OpenAI](https://learn.microsoft.com/azure/ai-services/openai/how-to/batch)
- [Semantic Kernel ChatCompletionAgent](https://learn.microsoft.com/semantic-kernel/frameworks/agent/agent-types/chat-completion-agent)
- [Estado experimental de Semantic Kernel Agent Orchestration](https://learn.microsoft.com/semantic-kernel/frameworks/agent/agent-orchestration/)
- [Durable Functions](https://learn.microsoft.com/azure/durable-task/durable-functions/durable-functions-overview)
- [Azure Identity para Python](https://learn.microsoft.com/python/api/overview/azure/identity-readme?view=azure-python)
