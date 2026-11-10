# 09.01 | Interfaz web del SAT-FUMC

> La SPA autenticada es el punto único de acceso operativo. La arquitectura canónica, estado y limitaciones están en [`ProductionArchitecture.md`](./ProductionArchitecture.md).

## 1. Navegación

- **Dashboard:** cobertura del corte, distribución de riesgo, alertas abiertas, seguimientos y actividad reciente. Toda métrica muestra periodo y fuente.
- **Estudiantes:** búsqueda/paginación de registros autorizados, filtros y estado de revisión. No se muestran expedientes locales de fallback cuando la API falla.
- **Ficha:** señales académicas, financieras, de bienestar y LMS disponibles al corte; score del modelo con versión/umbral; factores y origen de datos.
- **Análisis:** resúmenes separados por agente, evidencia/citas disponibles, limitaciones, uso del LLM y propuestas estructuradas.
- **Alertas y seguimiento:** registro de tareas después de una decisión humana, con actor, fecha y estado.
- **Revisión:** aprobar o rechazar propuestas pendientes. La decisión queda auditada; no se envían mensajes ni se ejecutan intervenciones automáticamente.
- **Reportes:** descarga CSV controlada desde la API de la misma plataforma.

## 2. Principios de interacción

1. La SPA no inventa datos cuando el API responde error; muestra un estado de indisponibilidad.
2. El score se presenta como probabilidad estimada, separado del texto generativo; no se presenta como diagnóstico ni causa.
3. Cada resultado muestra si es sintético o institucional, el corte, la versión y sus limitaciones.
4. Los controles de revisión y exportación requieren Entra ID y la allowlist institucional.
5. No se muestran nombres, documentos ni cifras de ejemplo como si fueran datos reales.
6. El LLM configurado en la POC es GPT-5-mini; genera propuestas para revisión humana.

## 3. Estado y límite de verificación

La Function App publicó la SPA y Azure indexó la función que sirve su contenido. Easy Auth está configurado: solicitudes anónimas a `/` respondieron `401` y `/.auth/login/aad` redirigió (`302`) a Microsoft. No se terminó un login interactivo ni se verificó la carga de la SPA/API con una respuesta autenticada `200`.

La POC opera contra datos sintéticos en Azure Tables/Blob. Azure SQL está provisionado y con esquema aplicado, pero la SPA/API aún no usa ese repositorio. Tampoco se conecta el snapshot de agentes al endpoint Azure ML. Los estados `Running` del host y `401` de una solicitud anónima no deben confundirse con disponibilidad de producción o con éxito de una sesión autorizada.

## 4. Origen de la información presentada

| Área visible | Origen actual | ¿GPT? |
|---|---|---|
| Conteo de estudiantes, niveles/probabilidades y filtros | Digital Twin sintético en Azure Tables | No; el score se genera en el Digital Twin, no lo produce el LLM |
| Distribución por sede/programa/facultad y matriz de riesgo | Agregaciones calculadas por la API sobre el snapshot sintético | No |
| Tendencia histórica | Filas explícitamente sembradas como `simulated-history` | No; es una tendencia simulada |
| Alertas iniciales | Regla sintética de riesgo alto/crítico | No. No deben titularse “generadas por IA” |
| Seguimientos iniciales | Registros sembrados de demostración en Tables | No |
| Resultados recientes, síntesis y análisis por agente | Propuestas `pending_approval` / `generated` leídas de Blob | Sí; solo tras ejecución de un lote de agentes |

## 5. Condición para mostrar resultados GPT

La carga inicial/refresco del dashboard solo consulta APIs y agregados; **no llama GPT**. Para crear resultados, el revisor debe completar login Entra, estar en la allowlist, tener la POC habilitada y casos pendientes, luego iniciar y confirmar un lote. `POST /api/batches` procesa como máximo cinco casos pendientes (los más antiguos; no necesariamente el perfil abierto). Durable Functions envía mensajes a Service Bus; los tres workers consultan Azure OpenAI y el sintetizador guarda la propuesta en Blob. Al terminar el lote, la SPA vuelve a consultar el dashboard y lista las propuestas guardadas.

Si no hay casos pendientes, la POC está pausada o el usuario no está autenticado, **Actualizar** solo refresca datos o no puede ejecutar el lote. Al 2026-11-09 el acceso anónimo devolvía `401`, no se completó el login interactivo ni un `200` autenticado, y Application Insights devolvió cero requests y cero dependencies en la consulta de los últimos 14 días. Por tanto no existe evidencia de una corrida GPT exitosa en Azure en esa ventana.
