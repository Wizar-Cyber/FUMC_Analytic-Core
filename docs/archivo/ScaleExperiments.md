# 04.02 | Experimentos de escala, métricas y visualización GPT

> **Corte de evidencia: 2026-11-10 UTC.** Esta bitácora consolida los manifests y runs aislados disponibles en `%TEMP%\fumc-phase2-*` y las comprobaciones del código/Azure. Separa explícitamente generación sintética, entrenamiento/evaluación ML y procesamiento GPT en la aplicación. Ninguno equivale a validación institucional.

> **Actualización 2026-11-11.** La recalibración integral (7 tamaños, 10 semillas, generador 2.1.0) está en [`Recalibration.md`](./Recalibration.md) y es la referencia vigente. Las corridas de este documento se hicieron con el generador 2.0.0, cuyas etiquetas de los dos últimos periodos tenían un sorteo de deserción adicional (prevalencia 27–30 % frente a 19–22 %). No se deben mezclar con las cifras del generador 2.1.0.

## 1. Resumen ejecutivo

Sí se ejecutó el generador sintético hasta **100.000 estudiantes**. La corrida optimizada terminó con 552.847 snapshots, 485.421 etiquetas maduras y 2.394.881 filas de detalle de asignaturas. Después se entrenó y evaluó LightGBM localmente sobre ese dataset, junto con una nueva cohorte 10k. Ambos outputs se cargaron como assets URI-folder al Workspace AML; no se ejecutó el job en compute remoto ni se promovió un modelo.

Existen runs de entrenamiento/evaluación en escalas **6k, 10k, 15k, 30k y 100k**, además de variantes calibradas y de prevalencia. Sus resultados son sintéticos y usan versiones/splits distintos. Ninguno es elegible para promoción y no acreditan desempeño institucional. A 50k solo se generó el dataset, sin evaluar el modelo.

## 2. Generación de datos por escala

| Estudiantes solicitados | Escenario/semilla | Snapshots | Etiquetas maduras | Etiquetas inmaduras | Filas de asignaturas | Prevalencia madura | Estado |
|---:|---|---:|---:|---:|---:|---:|---|
| 6.000 | baseline / 42 | 33.122 en la generación corregida calibrada | 33.122 | 0 | 143.328 | 21,12% | Generación aislada en TEMP; usada en un run calibrado de 6k |
| 10.000 | baseline / 42 | 55.105 | 55.105 | 0 | 238.518 | 20,86% | Dataset generado, evaluado con LightGBM local y subido al Workspace AML |
| 30.000 | baseline / 42 | 166.163 en una variante calibrada; 165.626 en la variante censurada final | 166.163 / 165.626 | 0 / 20.352 | 719.912 / 717.489 | 20,79% / 21,72% | Más de una versión de dataset; no combinar sus métricas |
| 50.000 | baseline / 42 | 277.814 | 260.668 | 17.146 | 1.203.610 | 20,11% | Generación completa; sin run de modelo |
| 100.000 | baseline / 42 | 552.847 | 485.421 | 67.426 | 2.394.881 | 21,78% | Generación optimizada completa; modelo también evaluado en local y artefactos subidos al Workspace AML |

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

### 3.2. Entrenamientos locales 10k y 100k

Se entrenó LightGBM con la misma configuración acotada para comparar ambas escalas. Los manifests, métricas, predicciones, curvas, fairness report y joblib quedaron en directorios temporales; se subieron copias como assets AML (ver sección 7). El umbral se escogió en validación. En ambos runs el entrenamiento mostró Recall de test superior a 0,80, pero la alerta de test fue muy alta y el Brier del 100k deficiente. `promotion_eligible=0` en ambos.

| Estudiantes | Snapshots total / maduros | Test (estudiantes) | Recall | Precisión | F1 | AUC-ROC | AUC-PR | Brier | Tasa de alertas | Umbral | Promoción |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 10.000 | 55.105 / 55.105 | 1.656 | 0,8453 | 0,3244 | 0,4689 | 0,6547 | 0,4050 | 0,1855 | 70,17% | 0,216940 | No |
| 100.000 | 552.847 / 485.421 | 3.321 | 0,8162 | 0,8737 | 0,8440 | 0,6480 | 0,9001 | 0,4367 | 78,68% | 0,188067 | No |

La métrica de precisión/F1 alta reportada para el 100k contrasta con su Brier 0,4367 y una tasa de alerta de 78,68%; requiere revisión antes de interpretarse como una mejora. Todas estas métricas son de datos sintéticos, la tasa de alertas está por encima de una capacidad operativa razonable, y no deben utilizarse para habilitar o priorizar población real. El split de test contiene estudiantes no vistos; el umbral no se seleccionó en test.

### 3.3. Corridas calibradas con versiones posteriores

Se ejecutaron corridas adicionales con selección/calibración y separación de estudiantes para validación y test. No se deben mezclar con la tabla baseline: cambian el `dataset_version`, el tratamiento de outcomes inmaduros, la calibración y/o el split.

| Escala / variante | `dataset_version` (prefijo) | Test (estudiantes, si registrado) | Recall | Precisión | F1 | AUC-ROC | AUC-PR | Brier | Alertas | Elegible |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 6k calibrado | `f8ad0e29` | 544 | 0,7796 | 0,3522 | 0,4852 | 0,6478 | 0,4748 | 0,1998 | 66,70% | No |
| 30k calibrado, todos los targets maduros en esa variante | `d1eb8027` | 2.706 | 0,7917 | 0,3618 | 0,4966 | 0,6741 | 0,4473 | 0,1882 | 62,03% | No |
| 30k variante censurada | `3111774d` | 642 | 0,7876 | 0,8614 | 0,8228 | 0,6141 | 0,9027 | 0,2365 | 77,15% | No |

La variante censurada 30k tiene 145.274 outcomes maduros y 20.352 inmaduros en 165.626 snapshots; sus resultados no son directamente comparables con la variante de 30k calibrada. Los hashes completos, parámetros y artefactos permanecen en los directorios temporales/MLflow locales identificados por los prefijos; esta tabla resume sus valores, no sustituye un paquete experimental archivado y reproducible.

### 3.4. Sensibilidad a prevalencia en 6k

| Escenario | Prevalencia del target maduro | Recall | Precisión | F1 | AUC-ROC | AUC-PR | Brier | Alertas | Elegible |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Baja | 13,51% | 0,7482 | 0,2409 | 0,3644 | 0,6233 | 0,2931 | 0,1552 | 61,71% | No |
| Alta | 28,54% | 0,7617 | 0,4953 | 0,6003 | 0,6922 | 0,5650 | 0,2209 | 60,34% | No |

### 3.5. Recalibración 5k–100k con el generador 2.1.0

Configuración final: regresión logística (C = 0,1), variables del contrato más transformaciones determinísticas de las mismas columnas, sin pesos de clase ni muestreo, política de capacidad (alertar al 40 % de mayor riesgo). Media de 10 semillas de partición por tamaño, test = dos últimos periodos con estudiantes no vistos.

| Estudiantes | AUC (media 10 semillas) | Recall | Precisión | F1 | Alertas | Alertas necesarias para recall 0,80 (IC95 %) |
|---:|---:|---:|---:|---:|---:|---|
| 5.000 | 0,670 | 0,595 | 0,301 | 0,399 | 40 % | 64,3 % (59,5–69,6) |
| 10.000 | 0,687 | 0,615 | 0,334 | 0,433 | 40 % | 64,2 % (59,5–70,8) |
| 15.000 | 0,680 | 0,605 | 0,313 | 0,412 | 40 % | 62,3 % (57,7–66,7) |
| 25.000 | 0,672 | 0,596 | 0,302 | 0,401 | 40 % | 62,9 % (59,4–67,3) |
| 50.000 | 0,672 | 0,597 | 0,312 | 0,410 | 40 % | 64,0 % (60,1–66,9) |
| 75.000 | 0,677 | 0,603 | 0,319 | 0,417 | 40 % | 64,7 % (62,9–67,0) |
| 100.000 | 0,673 | 0,600 | 0,314 | 0,412 | 40 % | 63,5 % (61,7–65,5) |

- El recall a capacidad fija es homogéneo entre tamaños (ANOVA p = 0,18; media 0,601 ± 0,004). Frente a 0,80, p ≈ 2·10⁻⁷³.
- El AUC del modelo queda a ≤ 0,007 del oráculo (riesgo real del generador) en todos los tamaños: no hay margen de ajuste.
- Frente al baseline del proyecto (LightGBM): AUC +0,015, recall a 40 % +0,021, Brier 0,237 → 0,154, alertas con la regla recall ≥ 0,80 de 62,6 % a 54,2 %.
- **0 de 210 corridas** cumplen recall ≥ 0,75, alertas ≤ 50 % y precisión ≥ 0,30. Hallazgos detallados en [`Recalibration.md`](./Recalibration.md) §12.

## 4. Interpretación de las métricas

- **Hay resultado ML para 100k, pero es sintético y no promovible.** Se entrenó localmente; el Brier es 0,4367 y el alert rate 78,68%, así que no debe presentarse como una mejora aceptable ni como desempeño institucional.
- **Las contradicciones entre tamaños tienen causa identificada.** Techo de información del generador (AUC del oráculo ≈ 0,67), etiquetas no estacionarias en los dos últimos periodos (corregidas en 2.1.0), ruido de muestreo con 5k–10k estudiantes y una regla de umbral inestable. Ver [`Recalibration.md`](./Recalibration.md) §3 y §12.
- **Recall no basta para promover.** Algunas corridas cruzan 0,80, pero tienen alertas excesivas; las corridas posteriores no alcanzan 0,80. Todos los flags guardados indican `promotion_eligible=0`.
- Las salidas son sintéticas y no estiman validez, calibración ni fairness en población FUMC.
- Las métricas de experimentos diferentes no se promedian. Se debe informar `dataset_version`, target maduro, split, modelo/calibración, threshold, métricas completas y alert rate.
- La suite de 71 pruebas valida código/contratos; no es una métrica del modelo ni prueba de un experimento de 100k.

## 5. Qué muestra la interfaz

La SPA presenta dos categorías diferentes de información:

1. **Digital Twin/indicadores:** conteos de estudiantes, niveles/probabilidades de riesgo, distribución por sede/programa/facultad, alertas por regla, seguimientos sembrados y tendencias sintéticas. Estos valores se calculan desde Azure Tables y el código de generación. La probabilidad de demo proviene del Digital Twin; no proviene de GPT ni del endpoint AML. Las tendencias se marcan en el API como `trend_is_simulated: true`.
2. **Resultados GPT de casos:** análisis académico, socioeconómico y de bienestar, síntesis, acciones propuestas, limitaciones, uso de tokens y costo estimado. Solo aparecen cuando un lote procesa casos y las propuestas quedan guardadas en Blob como `pending_approval`.

Las alertas iniciales se crean por una regla sobre `RiskLevel`/probabilidad sintética (`Source=synthetic-risk-rule`); no las genera el LLM. El rótulo “Alertas generadas por IA” se corrigió a “Alertas sintéticas por reglas de riesgo”; no son una salida GPT.

## 6. Por qué pueden no verse resultados GPT

El dashboard **no invoca GPT al abrirse ni al refrescar sus gráficos**. El flujo requiere: (a) login Entra y allowlist de revisor; (b) `DATA_MODE=synthetic`; (c) `POC_ENABLED=true`; (d) casos pendientes; y (e) pulsar **Actualizar/Procesar** y confirmar el lote. El botón inicia como máximo veinte casos pendientes ordenados por probabilidad del modelo descendente (desempate por ID), no necesariamente el perfil abierto. La operación envía mensajes a Service Bus; tres workers llaman a Azure OpenAI y el sintetizador guarda la propuesta en Blob. Un lote completo puede generar hasta 200 llamadas GPT y ejecutarse secuencialmente; la UI refresca y lista las propuestas `pending_approval`/`generated` al terminar.

En la verificación Azure del 2026-11-09, las rutas anónimas devolvieron `401`, no se completó el inicio de sesión interactivo ni una petición autenticada `200`. Application Insights devolvió cero requests y cero dependencies en la consulta de los últimos 14 días (y 272 traces); por tanto no hay evidencia de que una solicitud de Functions o una llamada GPT llegara a ejecutarse en esa ventana. Esto apunta a que todavía no se inició el flujo autenticado, no a que GPT genere resultados invisibles. Si una ejecución posterior falla, hay que revisar trazas/excepciones, permisos de Managed Identity, Service Bus y deployment/uso de Azure OpenAI.

> Actualización 2026-11-12: el flujo autenticado ya se ejecutó en `FUMCanalyticscore` (lote de 20 casos sin fallos). Ver [`E2EValidation.md`](./E2EValidation.md).

## 7. Assets cargados en Azure Machine Learning

El Workspace `FUMC_Analytics_Core` del grupo `FUMC.CaseReviewer` usa el datastore `workspaceblobstore`. Se cargaron los siguientes assets URI-folder, versión `1`:

| Asset AML | Contenido | Tamaño local aproximado |
|---|---|---:|
| `sat-fumc-synthetic-10k:1` | Dataset de 10.000 estudiantes, seed 42, baseline; manifest, calidad y Parquet | 5,24 MiB |
| `sat-fumc-10k-training-results:1` | Joblib, manifest/umbral, métricas, predicciones, fairness, SHAP y curvas | 7,93 MiB |
| `sat-fumc-synthetic-100k:1` | Dataset de 100.000 estudiantes y 552.847 snapshots maduros/inmaduros con manifest | 52,11 MiB |
| `sat-fumc-100k-training-results:1` | Joblib y artefactos de evaluación 100k; candidato no promovido | 55,06 MiB |

La generación y el entrenamiento se hicieron localmente en directorios TEMP aislados. **Los assets se almacenaron en Azure, pero no se ejecutó el entrenamiento en un compute de Azure ML**: el Workspace no tenía compute configurado en la verificación y no se creó un clúster para evitar cargos sin aprobación explícita. Los archivos temporales fuente de estas cargas permanecen en la máquina del trabajo; los assets son las copias remotas en AML. No se registró un modelo promovido.

## 8. Validación para una demostración autenticada

1. Abrir `https://fumcanalyticscore.azurewebsites.net/.auth/login/aad?post_login_redirect_uri=%2F` y autenticar una cuenta cuyo object ID esté en la allowlist.
2. Confirmar que `/api/poc/status` responde `200` y muestra `enabled=true` y `database.pending > 0`.
3. En el dashboard, pulsar **Analizar casos prioritarios** y confirmar el lote. Cada lote procesa hasta veinte casos pendientes, con los tres agentes en paralelo.
4. Esperar que el estado llegue a terminal; comprobar los indicadores de procesados/fallidos y que **Resultados recientes de agentes** deje de estar vacío.
5. Abrir un resultado y confirmar resumen GPT, análisis de los tres agentes, acciones, limitaciones y metadatos de tokens.
6. Si no aparece: revisar la respuesta de `/api/batches/{batchId}`, traces/exceptions/dependencies de Application Insights y DLQ/actividad de las cuatro colas. No abrir claves ni registrar tokens en la UI.

No se debe afirmar que esta prueba está completada hasta observar una respuesta autenticada y un resultado persistido real de la corrida.
