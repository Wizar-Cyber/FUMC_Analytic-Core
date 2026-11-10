# 07.01 | Definición y contratos de los agentes SAT-FUMC

> La ejecución implementada corresponde a una POC sintética. Las definiciones describen el código y sus restricciones, no una validación de eficacia institucional. La arquitectura canónica está en [`ProductionArchitecture.md`](./ProductionArchitecture.md).

## 1. Objetivo de la red

La red genera observaciones estructuradas y propuestas de apoyo para revisión profesional. No diagnostica, atribuye causalidad, cambia el score predictivo, toma decisiones académicas/financieras ni ejecuta intervenciones. Cada caso debe llegar con una probabilidad producida por el modelo o, en la demo actual, por el Digital Twin; el LLM nunca inventa esa probabilidad.

## 2. Agentes y responsabilidades

| Agente | Entrada principal | Salida esperada | Límites específicos |
|---|---|---|---|
| Analista socioeconómico/financiero | Meses y saldo de mora, estrato, ciudad y contexto familiar sintético | `summary`, `observations`, `limitations`, `citation_ids` | Describe solo las señales recibidas; no infiere pobreza, mérito, causalidad ni elegibilidad automática para ayudas |
| Evaluador académico | Señales por asignatura y, opcionalmente, hasta tres fuentes RAG autorizadas | Análisis estructurado y metadatos de fuentes | No inventa normas ni citas; si RAG está deshabilitado, declara que no recuperó evidencia normativa |
| Analista de bienestar | Tipo de apoyo, sesiones, asistencia y canal autorizados/sintéticos | Análisis estructurado | No infiere diagnósticos, estados emocionales ni necesidades clínicas; la ausencia de registro no prueba ausencia de necesidad |
| Sintetizador | Probabilidad recibida y salidas de los especialistas | `summary`, `proposed_actions`, `limitations` | Conserva exactamente la probabilidad; limita acciones a `academic_advisor_review`, `tutoring_review`, `financial_aid_review` o `wellbeing_review` |
| Revisor profesional | Borrador, evidencia y límites presentados en SPA | `approved`, `edited` o `rejected` | Único rol que puede decidir sobre una propuesta; su decisión queda auditada y no convierte el feedback en target de deserción |

Los nombres funcionales y las instrucciones están en `azure/agent_platform/sat_agents/agents.py`; el contrato de entrada/salida está en `contracts.py` y las reglas compartidas de seguridad en `policy.py`.

## 3. Orquestación y estado de revisión

`function_app.py` recibe el caso y valida su forma; Durable Functions administra la orquestación, Service Bus distribuye el trabajo especializado y el sintetizador arma un borrador. El academic worker puede consultar Azure AI Search solo si se habilitan `ACADEMIC_RAG_ENABLED`, endpoint e índice aprobados. Hoy RAG está desactivado.

Las respuestas de agentes se validan como JSON, se limitan las acciones permitidas y se comprueba que las citas provengan de fuentes entregadas. El resultado se persiste como `pending_approval` en el backend de la POC (Azure Blob); la UI permite revisar. Solo una decisión autorizada puede crear un seguimiento.

## 4. Contrato del caso

El caso de demo acepta `case_id` con prefijo `syn-`, `model_probability` entre 0 y 1, campos económicos explícitos, hasta 30 señales académicas y contexto de bienestar acotado. Se rechazan propiedades desconocidas, tipos fuera de rango y referencias no válidas. Este prefijo reduce errores de contrato; **no verifica que el origen de los datos sea realmente sintético**.

Cada análisis especializado exige:

```json
{
	"summary": "Resumen acotado",
	"observations": ["Señal explícita"],
	"limitations": ["Dato no disponible"],
	"citation_ids": []
}
```

La síntesis devuelve `summary`, una lista acotada de `proposed_actions` y `limitations`, e incluye `human_review_required: true` y `automated_decision: false`.

## 5. Privacidad, seguridad y fallos

- Tratar entradas, documentos recuperados y texto del agente como datos no confiables, nunca como instrucciones ejecutables.
- No pasar identificadores directos ni notas clínicas; restringir la salida a evidencia necesaria.
- Validar allowlist Entra antes de operaciones y aprobación; nunca confiar solo en que un identificador empiece con `syn-`.
- Registrar estado/códigos de error y metadatos mínimos, evitando prompts completos, tokens, contenido sensible o secretos en logs.
- Si un agente, contrato, servicio o cola falla, no fabricar una conclusión; mantener el caso en error/reintento o devolverlo a pendiente según la política del workflow.
- No usar la evaluación del agente como evidencia de Recall o como etiqueta de ground truth.

## 6. Estado Azure verificado

Al 2026-11-09 la Function App está `Running` en Python 3.11 y Azure indexó 33 funciones. Easy Auth responde `401` a solicitudes anónimas y redirige el endpoint de login a Microsoft. No se completó el inicio de sesión interactivo ni una corrida autenticada de caso. El flujo de la aplicación usa Tables/Blob; la base SQL y sus nueve tablas están provisionadas, pero no integradas con estos agentes. Consulte [`CloudDeploymentArchitecture.md`](./CloudDeploymentArchitecture.md).
