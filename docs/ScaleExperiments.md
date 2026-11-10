# 04.02 | Experimentos de escala, métricas y visualización GPT

> **Corte de evidencia: 2026-11-09.** Esta bitácora consolida los manifests y runs aislados disponibles en `%TEMP%\fumc-phase2-*` y las comprobaciones del código/Azure. Separa explícitamente generación sintética, entrenamiento/evaluación ML y procesamiento GPT en la aplicación. Ninguno equivale a validación institucional.

## 1. Resumen ejecutivo

Sí se ejecutó el generador sintético hasta **100.000 estudiantes**. La corrida optimizada terminó en un directorio temporal con 552.847 snapshots, 485.421 etiquetas maduras y 2.394.881 filas de detalle de asignaturas.

**No se entrenó ni evaluó el modelo a 100.000 estudiantes.** La carpeta 100k contiene los Parquet y el manifest del generador, pero no un run MLflow con métricas. Tampoco hay una salida de Recall/F1/AUC para 50k: ese volumen fue generado, no modelado.

Sí existen runs MLflow de entrenamiento/evaluación en escalas **6k, 15k y 30k**, además de variantes calibradas y de prevalencia. Sus resultados son sintéticos, de versiones/splits distintos y todos quedan no promovidos. No se debe atribuir ninguna métrica a 100k ni usarla como desempeño institucional.

## 2. Generación de datos por escala

| Estudiantes solicitados | Escenario/semilla | Snapshots | Etiquetas maduras | Etiquetas inmaduras | Filas de asignaturas | Prevalencia madura | Estado |
|---:|---|---:|---:|---:|---:|---:|---|
| 6.000 | baseline / 42 | 33.122 en la generación corregida calibrada | 33.122 | 0 | 143.328 | 21,12% | Generación aislada en TEMP; usada en un run calibrado de 6k |
| 30.000 | baseline / 42 | 166.163 en una variante calibrada; 165.626 en la variante censurada final | 166.163 / 165.626 | 0 / 20.352 | 719.912 / 717.489 | 20,79% / 21,72% | Más de una versión de dataset; no combinar sus métricas |
| 50.000 | baseline / 42 | 277.814 | 260.668 | 17.146 | 1.203.610 | 20,11% | Generación completa; sin run de modelo |
| 100.000 | baseline / 42 | 552.847 | 485.421 | 67.426 | 2.394.881 | 21,78% | Generación optimizada completa; sin run de modelo |

La variante final de 100k tiene `dataset_version` **`f20993a132c5cea0c50dd682c444e42e2785a3e1dc7ad35372516a5793348cbe`**. La variante de 50k tiene `dataset_version` **`36182991a506b11ae2d9815a69591fe79dbfdd9941dafb09849427639bd3c219`**. Los Parquet completos están fuera del repositorio en TEMP; el manifest y esta tabla registran los conteos relevantes.

El dataset tabular versionado en `data/raw/` es otro artefacto: 6.000 estudiantes, 27.975 snapshots. No debe confundirse con las corridas temporales de 6k (que tienen 33.122–33.228 snapshots), ni con los 5.000 perfiles por defecto del Digital Twin de Functions. Son poblaciones y cortes distintos.

## 3. Evaluaciones ML registradas

### 3.1. Comparación baseline por escala

Estas tres corridas aisladas aparecen en los logs de MLflow locales, con escenario baseline y semilla común de la generación registrada. El número de estudiantes es la escala del conjunto solicitado; no es el número de ejemplos del test. El test no se usa para escoger el umbral.

| Escala | `dataset_version` (prefijo) | Recall test | Precisión | F1 | AUC-ROC | AUC-PR | Brier | Tasa de alertas | Elegible para promoción |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---|
| 6k | `64c9f682` | 0,6971 | 0,3194 | 0,4381 | 0,6071 | 0,3929 | 0,2348 | 62,52% | No |
| 15k | `45d5bab6` | 0,8069 | 0,3090 | 0,4469 | 0,6456 | 0,3827 | 0,2328 | 65,32% | No |
| 30k | `26a379ce` | 0,7731 | 0,3313 | 0,4639 | 0,6679 | 0,4236 | 0,2333 | 61,31% | No |

El 15k supera Recall 0,80 en ese run sintético, pero la tasa de alertas supera 65% y el flag `promotion_eligible` es `0`. No se considera promovible ni evidencia de Recall institucional.

### 3.2. Corridas calibradas con versiones posteriores

Se ejecutaron corridas adicionales con selección/calibración y separación de estudiantes para validación y test. No se deben mezclar con la tabla baseline: cambian el `dataset_version`, el tratamiento de outcomes inmaduros, la calibración y/o el split.

| Escala / variante | `dataset_version` (prefijo) | Test (estudiantes, si registrado) | Recall | Precisión | F1 | AUC-ROC | AUC-PR | Brier | Alertas | Elegible |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 6k calibrado | `f8ad0e29` | 544 | 0,7796 | 0,3522 | 0,4852 | 0,6478 | 0,4748 | 0,1998 | 66,70% | No |
| 30k calibrado, todos los targets maduros en esa variante | `d1eb8027` | 2.706 | 0,7917 | 0,3618 | 0,4966 | 0,6741 | 0,4473 | 0,1882 | 62,03% | No |
| 30k variante censurada | `3111774d` | 642 | 0,7876 | 0,8614 | 0,8228 | 0,6141 | 0,9027 | 0,2365 | 77,15% | No |

La variante censurada 30k tiene 145.274 outcomes maduros y 20.352 inmaduros en 165.626 snapshots; sus resultados no son directamente comparables con la variante de 30k calibrada. Los hashes completos, parámetros y artefactos permanecen en los directorios temporales/MLflow locales identificados por los prefijos; esta tabla resume sus valores, no sustituye un paquete experimental archivado y reproducible.

### 3.3. Sensibilidad a prevalencia en 6k

| Escenario | Prevalencia del target maduro | Recall | Precisión | F1 | AUC-ROC | AUC-PR | Brier | Alertas | Elegible |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Baja | 13,51% | 0,7482 | 0,2409 | 0,3644 | 0,6233 | 0,2931 | 0,1552 | 61,71% | No |
| Alta | 28,54% | 0,7617 | 0,4953 | 0,6003 | 0,6922 | 0,5650 | 0,2209 | 60,34% | No |

## 4. Interpretación de las métricas

- **No existe un resultado ML para 100k.** 100k es una prueba de escala del generador, no del clasificador.
- **Recall no basta para promover.** Algunas corridas cruzan 0,80, pero tienen alertas excesivas; las corridas posteriores no alcanzan 0,80. Todos los flags guardados indican `promotion_eligible=0`.
- Las salidas son sintéticas y no estiman validez, calibración ni fairness en población FUMC.
- Las métricas de experimentos diferentes no se promedian. Se debe informar `dataset_version`, target maduro, split, modelo/calibración, threshold, métricas completas y alert rate.
- La suite de 71 pruebas valida código/contratos; no es una métrica del modelo ni prueba de un experimento de 100k.

## 5. Qué muestra la interfaz

La SPA presenta dos categorías diferentes de información:

1. **Digital Twin/indicadores:** conteos de estudiantes, niveles/probabilidades de riesgo, distribución por sede/programa/facultad, alertas por regla, seguimientos sembrados y tendencias sintéticas. Estos valores se calculan desde Azure Tables y el código de generación. La probabilidad de demo proviene del Digital Twin; no proviene de GPT ni del endpoint AML. Las tendencias se marcan en el API como `trend_is_simulated: true`.
2. **Resultados GPT de casos:** análisis académico, socioeconómico y de bienestar, síntesis, acciones propuestas, limitaciones, uso de tokens y costo estimado. Solo aparecen cuando un lote procesa casos y las propuestas quedan guardadas en Blob como `pending_approval`.

Las alertas iniciales se crean por una regla sobre `RiskLevel`/probabilidad sintética (`Source=synthetic-risk-rule`); no las genera el LLM. El texto de interfaz “Alertas generadas por IA” era impreciso y debe leerse como alertas sintéticas por reglas, no como una salida GPT.

## 6. Por qué pueden no verse resultados GPT

El dashboard **no invoca GPT al abrirse ni al refrescar sus gráficos**. El flujo requiere: (a) login Entra y allowlist de revisor; (b) `DATA_MODE=synthetic`; (c) `POC_ENABLED=true`; (d) casos pendientes; y (e) pulsar **Actualizar/Procesar** y confirmar el lote. El botón inicia como máximo cinco casos pendientes, no necesariamente el perfil que el usuario estaba viendo. La operación envía mensajes a Service Bus; tres workers llaman a Azure OpenAI; el sintetizador guarda la propuesta en Blob. Al completarse, la UI refresca y lista los blobs `pending_approval`/`generated`.

En la verificación Azure del 2026-11-09, las rutas anónimas devolvieron `401`, no se completó el inicio de sesión interactivo ni una petición autenticada `200`. Application Insights devolvió cero requests y cero dependencies en la consulta de los últimos 14 días (y 272 traces); por tanto no hay evidencia de que una solicitud de Functions o una llamada GPT llegara a ejecutarse en esa ventana. Esto apunta a que todavía no se inició el flujo autenticado, no a que GPT genere resultados invisibles. Si una ejecución posterior falla, hay que revisar trazas/excepciones, permisos de Managed Identity, Service Bus y deployment/uso de Azure OpenAI.

## 7. Validación para una demostración autenticada

1. Abrir `https://satfumcfunc0e83b2486979.azurewebsites.net/.auth/login/aad?post_login_redirect_uri=%2F` y autenticar una cuenta cuyo object ID esté en la allowlist.
2. Confirmar que `/api/poc/status` responde `200` y muestra `enabled=true` y `database.pending > 0`.
3. En el dashboard, pulsar **Actualizar** y confirmar el lote. Cada lote procesa hasta cinco casos pendientes.
4. Esperar que el estado llegue a terminal; comprobar los indicadores de procesados/fallidos y que **Resultados recientes de agentes** deje de estar vacío.
5. Abrir un resultado y confirmar resumen GPT, análisis de los tres agentes, acciones, limitaciones y metadatos de tokens.
6. Si no aparece: revisar la respuesta de `/api/batches/{batchId}`, traces/exceptions/dependencies de Application Insights y DLQ/actividad de las cuatro colas. No abrir claves ni registrar tokens en la UI.

No se debe afirmar que esta prueba está completada hasta observar una respuesta autenticada y un resultado persistido real de la corrida.
