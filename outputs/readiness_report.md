# Informe de preparación para producción

Generado: 2026-11-10T01:25:59+00:00
Modo remoto: no (solo chequeos locales)
Resumen: PASS=25, FAIL=2, PENDING=18, MANUAL=23


## 4. Datos y almacenamiento (2/9)

- [ ] Blob Storage permite cargar y recuperar archivos. **PENDING** — define SAT_STORAGE_CONNECTION y SAT_STORAGE_CONTAINER
- [ ] Los contenedores tienen permisos adecuados. **MANUAL** — revisar RBAC de la cuenta en el portal (Storage Blob Data *)
- [ ] Azure SQL acepta conexiones autorizadas. **PENDING** — define SAT_SQL_CONNECTION
- [ ] Las migraciones de base de datos se ejecutaron correctamente. **MANUAL** — no existe tabla de versiones de esquema; sql_schema.sql es idempotente pero sin historial
- [ ] Las tablas, índices y relaciones existen. **PENDING** — define SAT_SQL_CONNECTION. Solo evidencia local del script: 9 tablas, 4 índices, 7 FK en sql_schema.sql
- [ ] Las operaciones CRUD funcionan. **FAIL** — usa FakeConnection por defecto (escrituras se descartan en silencio); no hay driver real (pyodbc/pymssql); no hay operaciones de lectura (solo record_*)
- [x] Los datos sintéticos están identificados y separados. **PASS** — target fuera de snapshots=True; DataMode synthetic en SQL=True
- [x] Los registros mantienen estudiante, periodo y fecha de corte. **PASS** — StudentSnapshot conserva estudiante, periodo, corte y fecha
- [ ] Los respaldos y políticas de retención están configurados. **MANUAL** — az sql db ltr-policy show / short-term-retention-policy show

## 5. Pipeline de Machine Learning (6/10)

- [ ] El pipeline de entrenamiento se ejecuta en el entorno esperado. **MANUAL** — ejecutar azure/train_azure.py y adjuntar el job de AML
- [x] Los datasets se cargan correctamente. **PASS** — pytest tests/test_production_contracts.py: 13 passed, 31 warnings in 5.72s
- [x] La validación de esquemas funciona. **PASS** — pytest tests/test_production_contracts.py: 13 passed, 31 warnings in 5.72s
- [x] La ingeniería de características coincide con entrenamiento e inferencia. **PASS** — pytest tests/test_production_contracts.py: 13 passed, 31 warnings in 5.72s
- [x] Las particiones temporales no presentan fuga de información. **PASS** — pytest tests/test_model_selection.py: 7 passed in 2.18s
- [x] Los experimentos quedan registrados en MLflow. **PASS** — registro de métricas declarado; tracking local (carpeta mlruns), no un workspace AML
- [ ] Los artefactos del modelo se almacenan correctamente. **MANUAL** — verificar registro del modelo en AML (az ml model list)
- [ ] El modelo aprobado tiene versión identificable. **MANUAL** — depende de AML Model Registry / dbo.ModelRelease
- [x] El bloqueo de promoción funciona cuando no se cumplen las métricas. **PASS** — pytest tests/test_model_selection.py: 7 passed in 2.18s
- [ ] El endpoint utiliza la versión aprobada del modelo. **PENDING** — define SAT_BASE_URL

## 6. Validación predictiva (6/12)

- [ ] Se ejecutó una evaluación independiente del entrenamiento. **MANUAL** — falta script de evaluación sobre el conjunto de prueba reservado
- [x] Se reporta Recall. **PASS** — métricas calculadas en el código de entrenamiento (no es una evaluación independiente)
- [x] Se reporta Precision. **PASS** — métricas calculadas en el código de entrenamiento (no es una evaluación independiente)
- [x] Se reporta F1-score. **PASS** — métricas calculadas en el código de entrenamiento (no es una evaluación independiente)
- [x] Se reporta AUC-ROC y AUC-PR. **PASS** — métricas calculadas en el código de entrenamiento (no es una evaluación independiente)
- [x] Se reporta Brier Score. **PASS** — métricas calculadas en el código de entrenamiento (no es una evaluación independiente)
- [ ] Se revisó la matriz de confusión. **MANUAL** — registrar la matriz en el informe de evaluación
- [x] Se validó el umbral con datos de validación, no de prueba. **PASS** — pytest tests/test_model_selection.py: 7 passed in 2.18s
- [ ] Se conoce el volumen de falsos positivos. **MANUAL** — derivar de la matriz de confusión
- [ ] Se conoce el volumen de falsos negativos. **MANUAL** — derivar de la matriz de confusión
- [ ] Se documentó si Recall >= 0,80 fue alcanzado. **MANUAL** — documentar el resultado del run independiente
- [ ] Los resultados sintéticos no se presentan como resultados institucionales reales. **MANUAL** — revisar artículo y dashboards: etiqueta 'sintético' visible

## 7. Red multiagente y GPT-5-mini (8/12)

- [x] Semantic Kernel se inicializa correctamente. **PASS** — pytest tests/test_distributed_agent_contracts.py: 40 passed, 1 warning in 4.57s
- [x] El coordinador recibe el contexto del estudiante. **PASS** — pytest tests/test_distributed_agent_contracts.py: 40 passed, 1 warning in 4.57s
- [x] El agente académico ejecuta su análisis. **PASS** — pytest tests/test_distributed_agent_contracts.py: 40 passed, 1 warning in 4.57s
- [x] El agente financiero maneja correctamente datos ausentes. **PASS** — pytest tests/test_distributed_agent_contracts.py: 40 passed, 1 warning in 4.57s
- [ ] El agente de bienestar respeta los permisos. **MANUAL** — revisar política de permisos del agente de bienestar
- [x] El agente de síntesis consolida los resultados. **PASS** — pytest tests/test_distributed_agent_contracts.py: 40 passed, 1 warning in 4.57s
- [x] El agente de recomendaciones genera propuestas verificables. **PASS** — pytest tests/test_distributed_agent_contracts.py: 40 passed, 1 warning in 4.57s
- [ ] GPT-5-mini responde desde el recurso Azure esperado. **MANUAL** — ejecutar un caso con --allow-writes y revisar el recurso/despliegue sat-gpt5-mini
- [x] Las salidas cumplen el esquema JSON definido. **PASS** — pytest tests/test_distributed_agent_contracts.py: 40 passed, 1 warning in 4.57s
- [x] Los agentes no modifican la predicción de LightGBM. **PASS** — pytest tests/test_distributed_agent_contracts.py: 40 passed, 1 warning in 4.57s
- [ ] Los errores y timeouts se gestionan correctamente. **MANUAL** — pruebas de fallo contra Azure OpenAI y Service Bus (DLQ)
- [ ] Cada ejecución tiene trazabilidad. **MANUAL** — verificar correlación en Application Insights

## 8. API y frontend (1/12)

- [ ] La SPA carga correctamente desde su URL de despliegue. **PENDING** — define SAT_BASE_URL
- [ ] La autenticación funciona desde el navegador. **PENDING** — define SAT_BASE_URL
- [ ] El dashboard consume datos reales del backend. **PENDING** — define SAT_BASE_URL
- [ ] El listado de estudiantes funciona. **PENDING** — define SAT_BASE_URL
- [ ] La ficha integral muestra información consistente. **PENDING** — define SAT_BASE_URL
- [ ] La predicción coincide con la respuesta del endpoint. **MANUAL** — comparar probabilidad de la ficha con /api/ml/predict para un mismo caso
- [ ] Los resúmenes generados se visualizan correctamente. **MANUAL** — revisión visual en navegador
- [ ] Las recomendaciones se pueden revisar. **PENDING** — define SAT_BASE_URL
- [ ] La aprobación y el rechazo quedan registrados. **MANUAL** — POST /api/reviews/{id}/approval y verificar en /api/reports/reviews
- [ ] Las intervenciones se pueden registrar y consultar. **PENDING** — define SAT_BASE_URL
- [ ] Los errores de API se muestran adecuadamente. **PENDING** — define SAT_BASE_URL
- [x] No quedan mocks presentados como datos reales. **PASS** — sin marcadores mock en la SPA

## 9. Integración end-to-end (2/13)

- [x] Se genera o carga un registro de estudiante. **PASS** — default=10000, max=100000
- [x] Se procesa y valida su información. **PASS** — pytest tests/test_production_contracts.py: 13 passed, 31 warnings in 5.72s
- [ ] Se ejecuta una predicción. **PENDING** — define SAT_BASE_URL
- [ ] Se obtiene la probabilidad y clasificación de riesgo. **PENDING** — define SAT_BASE_URL
- [ ] Se inicia la orquestación de agentes. **MANUAL** — POST /api/cases con --allow-writes
- [ ] Se genera un resumen. **MANUAL** — depende del caso end-to-end
- [ ] Se generan recomendaciones. **MANUAL** — depende del caso end-to-end
- [ ] Se almacenan los resultados en Azure SQL. **FAIL** — usa FakeConnection por defecto (escrituras se descartan en silencio); no hay driver real (pyodbc/pymssql); no hay operaciones de lectura (solo record_*)
- [ ] La API recupera la información almacenada. **PENDING** — define SAT_BASE_URL
- [ ] La SPA muestra la información correctamente. **MANUAL** — revisión visual en navegador
- [ ] Un profesional puede revisar el caso. **PENDING** — define SAT_BASE_URL
- [ ] La intervención queda registrada. **PENDING** — define SAT_BASE_URL
- [ ] El seguimiento puede consultarse posteriormente. **PENDING** — define SAT_BASE_URL
