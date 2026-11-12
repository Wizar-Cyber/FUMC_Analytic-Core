# 09.01 | Interfaz web del SAT-FUMC

> La SPA autenticada es el punto único de acceso operativo. La arquitectura canónica, estado y limitaciones están en [`ProductionArchitecture.md`](./ProductionArchitecture.md).

## 1. Navegación

- **Dashboard:** cobertura del corte, distribución de riesgo, alertas abiertas, seguimientos y actividad reciente. Toda métrica muestra periodo y fuente.
- **Estudiantes:** búsqueda/paginación de registros autorizados, filtros y estado de revisión. No se muestran expedientes locales de fallback cuando la API falla.
- **Ficha · Resumen ejecutivo (pestaña por defecto):** riesgo (nivel + probabilidad), prioridad de atención y estado; un único diagnóstico consolidado con su evidencia; checklist de acciones; mapa de calor de asignaturas y línea de tiempo de intervenciones. Detalle en [`ExecutiveView.md`](./ExecutiveView.md).
- **Ficha · Expediente:** datos personales, académicos, financieros, de bienestar y materias del periodo.
- **Análisis:** no se muestran informes por agente, limitaciones, uso de tokens ni costos; esa información se conserva solo para auditoría y reportes.
- **Alertas y seguimiento:** registro de tareas después de una decisión humana, con actor, fecha y estado.
- **Revisión:** aprobar o rechazar propuestas pendientes. La decisión queda auditada; no se envían mensajes ni se ejecutan intervenciones automáticamente.
- **Reportes:** descarga CSV controlada desde la API de la misma plataforma.

## 2. Principios de interacción

1. La SPA no inventa datos cuando el API responde error; muestra un estado de indisponibilidad.
2. El score se presenta como probabilidad estimada junto a su nivel de riesgo; el diagnóstico textual usa lenguaje de asociación, no de causa.
3. Cada resultado registra si es sintético o institucional, el corte, la versión y sus limitaciones; la vista ejecutiva no las presenta, se conservan para auditoría y reportes.
4. Los controles de revisión y exportación requieren Entra ID y la allowlist institucional.
5. No se muestran nombres, documentos ni cifras de ejemplo como si fueran datos reales.
6. El LLM configurado en la POC es GPT-5-mini; genera propuestas para revisión humana.
7. Cada dato aparece una sola vez en la vista ejecutiva y el texto visible se limita a un diagnóstico de ≤ 150 palabras, independientemente del tamaño de la población.

## 3. Estado y límite de verificación

La Function App publicó la SPA y Azure indexó la función que sirve su contenido. Easy Auth está configurado: solicitudes anónimas a `/` respondieron `401` y `/.auth/login/aad` redirigió (`302`) a Microsoft. No se terminó un login interactivo ni se verificó la carga de la SPA/API con una respuesta autenticada `200`.

La POC opera contra datos sintéticos en Azure Tables/Blob; la API escribe además la auditoría de cada caso analizado en Azure SQL. La cohorte se puntuó con el endpoint Azure ML v2, que la interfaz no invoca en tiempo real. Los estados `Running` del host y `401` de una solicitud anónima no deben confundirse con disponibilidad de producción o con éxito de una sesión autorizada.

## 4. Origen de la información presentada

| Área visible | Origen actual | ¿GPT? |
|---|---|---|
| Conteo de estudiantes, niveles/probabilidades y filtros | Digital Twin sintético en Azure Tables | No; el score se genera en el Digital Twin, no lo produce el LLM |
| Distribución por sede/programa/facultad y matriz de riesgo | Agregaciones calculadas por la API sobre el snapshot sintético | No |
| Tendencia histórica | Filas explícitamente sembradas como `simulated-history` | No; es una tendencia simulada |
| Alertas iniciales | Regla sintética de riesgo alto/crítico | No. No deben titularse “generadas por IA” |
| Seguimientos iniciales | Registros sembrados de demostración en Tables | No |
| Diagnóstico consolidado y acciones propuestas | Resumen del sintetizador (`pending_approval` / `generated`) leído de Blob | Sí; solo tras ejecución de un lote de agentes |
| Factores, evidencia, prioridad y estado de acciones | Consolidación determinista en `sat_agents/executive.py` sobre expediente y seguimientos | No |
| Diagnóstico «Preliminar» | Plantilla determinista a partir de los factores | No |

## 5. Condición para mostrar resultados GPT

La carga inicial/refresco del dashboard solo consulta APIs y agregados; **no llama GPT**. Para crear resultados, el revisor debe completar login Entra, estar en la allowlist, tener la POC habilitada y casos pendientes, luego iniciar y confirmar un lote. `POST /api/batches` procesa como máximo veinte casos pendientes, del mayor al menor riesgo (no necesariamente el perfil abierto). La API envía mensajes a Service Bus; los tres workers consultan Azure OpenAI en paralelo y el sintetizador guarda la propuesta en Blob y en Azure SQL. Al terminar el lote, la SPA vuelve a consultar el dashboard y lista las propuestas guardadas.

Si no hay casos pendientes, la POC está pausada o el usuario no está autenticado, **Actualizar** solo refresca datos o no puede ejecutar el lote. Al 2026-11-09 el acceso anónimo devolvía `401`, no se completó el login interactivo ni un `200` autenticado, y Application Insights devolvió cero requests y cero dependencies en la consulta de los últimos 14 días. Por tanto no existe evidencia de una corrida GPT exitosa en Azure en esa ventana.
