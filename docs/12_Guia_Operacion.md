# 12 | Guía de operación

> Procedimientos para ejecutar, desplegar, verificar, operar, mantener, escalar y apagar la POC. La evidencia del despliegue del 2026-11-12 está en la [§9](#9-validación-e2e-del-2026-11-12) y el estado del plan por fases en la [§10](#10-despliegue-por-fases). Todos los datos son sintéticos; nada de lo aquí descrito habilita uso con estudiantes reales.

## 1. Entorno local

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r azure/agent_platform/requirements.txt
python -m pytest -q                       # 118 aprobadas, 1 omitida (SQL en vivo)
```

| Tarea | Comando |
|---|---|
| Generar datos sintéticos | `python src/data_generation/generate_digital_twin.py` (ajustes con `SAT_SYNTHETIC_*`) |
| Entrenar localmente | `python -m src.ml.train_pipeline` desde la raíz (`SAT_DATA_DIR`, `SAT_MAX_ALERT_RATE`) |
| Pipeline local por agentes | `python -m src.run_multiagent_system` desde la raíz |
| Ejecutar la Function App | Copiar `local.settings.example.json` a `local.settings.json` y `func start` en `azure/agent_platform` (Core Tools v4, Python 3.11) |
| Regenerar diagramas | `python docs/diagramas/build_diagrams.py` |

## 2. Despliegue

Ver [11 DevOps y CI/CD](./11_DevOps_CICD.md#2-despliegue-manual). Tras desplegar:

1. Abrir la URL de la Function App, iniciar sesión con un usuario de la allowlist y comprobar `200` en `/api/poc/status`.
2. Confirmar que una solicitud anónima a `/api/poc/status` devuelve `401`.
3. Revisar en Application Insights el mensaje «Persistencia SQL activa».
4. Lanzar un lote acotado y comprobar 20/20 casos procesados y filas nuevas en `Prediction` y `AgentExecution`.
5. Ejecutar `python scripts/validate_readiness.py` (variables `SAT_BASE_URL`, `SAT_BEARER_TOKEN`, `SAT_SQL_SERVER`, `SAT_SQL_DATABASE`, `SAT_STORAGE_*`); usar `--allow-writes` solo en entornos de prueba.

Un `401` anónimo y el `302` de `/.auth/login/aad` hacia `login.microsoftonline.com` solo prueban que el acceso anónimo está bloqueado; la aceptación exige un `200` con un revisor autorizado (SPA sin datos locales de fallback, JSON válido en `/api/poc/status`). No registrar cookies, cabeceras `Authorization`, tokens ni secretos durante las pruebas.

### 2.1 Verificador de preparación

`scripts/validate_readiness.py` recorre los bloques 4 a 9 del checklist de producción y asigna a cada ítem `PASS` (evidencia obtenida en la ejecución), `FAIL`, `PENDING` (faltan variables del entorno Azure) o `MANUAL` (requiere evidencia humana).

```powershell
# Solo chequeos locales (no requiere Azure)
python scripts/validate_readiness.py

# Contra el despliegue, solo lectura
$env:SAT_BASE_URL = "https://<function-app>.azurewebsites.net"
$env:SAT_BEARER_TOKEN = "<token de un revisor autorizado>"
$env:SAT_SQL_SERVER = "<servidor>.database.windows.net"
$env:SAT_SQL_DATABASE = "SATFUMCOperational"
python scripts/validate_readiness.py

# Con escrituras de prueba (crea seguimientos y blobs de validación)
python scripts/validate_readiness.py --allow-writes
```

| Variable opcional | Uso |
|---|---|
| `SAT_SQL_SERVER`, `SAT_SQL_DATABASE` | Conexión Entra (`az login` o identidad administrada); requiere `pyodbc`, `azure-identity` y ODBC Driver 18 |
| `SAT_STORAGE_CONNECTION`, `SAT_STORAGE_CONTAINER` | Carga y recuperación de blobs |
| `SAT_PREDICT_PAYLOAD` | Ruta a un JSON con el contrato de `/api/ml/predict` |

Salida en `outputs/readiness_report.md` (`--output` para cambiarla); código de salida 1 si hay algún `FAIL`. Un `PASS` local no sustituye la verificación en Azure: la evidencia de cada ítem indica qué se comprobó.

| Bloque | Verificación complementaria (manual o con CLI) |
|---|---|
| 4. Datos y almacenamiento | Permisos: `az role assignment list --scope <storage-id> -o table` debe mostrar a la identidad de la app con los roles de Bicep (Blob Data Owner, Queue y Table Data Contributor) y ningún acceso amplio adicional. Migraciones: versiones en `dbo.SchemaVersion`. Respaldos: ver §2.2 |
| 5. Pipeline de ML | Enlace del job de AML; `az ml model list`; registro en `dbo.ModelRelease`. `train_pipeline.py` usa tracking MLflow local (`mlruns`); `train_azure.py` acepta `--tracking-uri` para el workspace |
| 6. Validación predictiva | `python scripts/evaluate_model.py --data_dir <carpeta> --model_version <n>`: evalúa solo la partición de prueba con el umbral fijado en validación; reportar Recall, Precision, F1, AUC-ROC, AUC-PR, Brier, matriz de confusión y si Recall ≥ 0,80, declarando que los datos son sintéticos |
| 7. Red multiagente | Confirmar en telemetría el despliegue `sat-gpt5-mini` de `FUMCAnalitysReviewer`; rastrear el caso en Application Insights; forzar timeout y error del modelo y comprobar estado del caso, reintento y dead-letter |
| 8. API y frontend | Manual: coherencia predicción/endpoint, visualización de resúmenes y flujo aprobar/rechazar en navegador |
| 9. End-to-end | `POST /api/batches` con `student_id` → `GET /api/batches/{id}` hasta estado final → `GET /api/reviews` → `POST /api/reviews/{id}/approval` → `POST /api/poc/followups` → comprobar las filas correspondientes en SQL (§9.2) |

### 2.2 Comprobaciones con Azure CLI

Ejecutar con la suscripción correcta y sin pasar secretos en línea:

```powershell
az functionapp show -g FUMC.CaseReviewer -n FUMCanalyticscore --query state -o tsv
az functionapp function list -g FUMC.CaseReviewer -n FUMCanalyticscore --query "[].name" -o table
az functionapp config appsettings list -g FUMC.CaseReviewer -n FUMCanalyticscore --query "[?name=='DATA_MODE'].value" -o tsv
az sql db show -g FUMC.CaseReviewer -s <servidor-sql> -n SATFUMCOperational --query "{status:status,sku:sku.name}" -o json
az sql db ltr-policy show -g FUMC.CaseReviewer -s <servidor-sql> -n SATFUMCOperational
az sql db str-policy show -g FUMC.CaseReviewer -s <servidor-sql> -n SATFUMCOperational
az ml online-endpoint show -n sat-fumc-endpoint --query provisioning_state -o tsv
```

`<servidor-sql>`: documentado como `satfumc-sql-fumc01`; confirmarlo con `az sql server list -g FUMC.CaseReviewer -o table`. El comando de AML requiere `-g`/`-w` del workspace `FUMC_Analytics_Core` (o `az configure --defaults`). La lista de funciones incluye cuatro actividades Durable heredadas que fallan al indexarse y no se usan. La presencia del esquema SQL se verifica por catálogo desde una sesión de base autorizada.

## 3. Operación diaria

| Tarea | Cómo |
|---|---|
| Analizar casos | Dashboard → "Analizar casos prioritarios" (hasta 20 de mayor riesgo) o perfil → "Generar plan" |
| Seguir un lote | La SPA sondea `GET /api/batches/{id}` cada 3 s |
| Validar un plan | Perfil → Resumen ejecutivo → "Validar plan" / "Descartar" |
| Gestionar alertas y seguimientos | Vistas Alertas y Seguimientos |
| Exportar | Reportes → CSV; Estudiantes → CSV |
| Agregar un revisor | Añadir su object ID de Entra a `CASE_REVIEWER_ALLOWED_PRINCIPAL_IDS` (parámetro `reviewerPrincipalIds`) |

## 4. Pausa, reanudación y apagado

| Nivel | Acción | Efecto |
|---|---|---|
| Pausar análisis | `POST /api/poc/state {"enabled": false}` o `POC_ENABLED=false` | Rechaza lotes nuevos; la consulta sigue disponible. Se rechaza (409) si hay un lote activo |
| Detener la app | `az functionapp stop` | Detiene API, workers y timers. **No detiene** costos de SQL, Storage, Service Bus, OpenAI, Key Vault, monitoreo ni del endpoint AML |
| Endpoint AML | Eliminar el despliegue `blue` o el endpoint | Elimina el costo de la instancia `Standard_DS2_v2` |
| Reanudar | `az functionapp start`; verificar Python 3.11, `DATA_MODE=synthetic` y un `200` autenticado | — |
| Eliminar | No ejecutar `az group delete` sin aprobación explícita y exportación previa | Irreversible |

```powershell
az functionapp stop  -g FUMC.CaseReviewer -n FUMCanalyticscore
az functionapp start -g FUMC.CaseReviewer -n FUMCanalyticscore
az ml online-deployment delete -e sat-fumc-endpoint -n blue --yes   # requiere -g/-w del workspace
```

`POST /api/poc/state` exige sesión de revisor autorizado y no borra recursos. Tras detener la app, revisar Cost Management por recurso: los cargos de los servicios no detenidos continúan.

**Antes de eliminar el grupo de recursos** (borra app, base SQL, almacenamiento, colas, secretos y telemetría):

1. Confirmar suscripción y grupo con el propietario del proyecto.
2. Exportar solo los datos sintéticos, logs y artefactos que deban conservarse.
3. Comprobar que la contraseña SQL y los secretos rotados no los use otra aplicación.
4. Verificar que no haya información institucional ni evidencia que deba preservarse.
5. Obtener aprobación explícita. No automatizar `az group delete` ni usarlo como primera medida de control de costos.

**Reactivación**: iniciar la app; comprobar el estado del host y las funciones indexadas; confirmar Python 3.11, `DATA_MODE=synthetic` y referencias a Key Vault (sin mostrar valores); repetir el login Entra y obtener `200` en un endpoint de solo lectura; solo después lanzar un lote acotado y revisar logs, Service Bus, Tables/Blob y filas nuevas en SQL.

## 5. Procesos automáticos

| Proceso | Frecuencia | Qué hace |
|---|---|---|
| `cache_warmer` | Cada 4 min y al arrancar | Refresca cachés; comprueba SQL (puede reanudar la base serverless) |
| `batch_reaper` | Cada 2 min | Marca como fallidos los lotes de más de 20 min y libera el cupo |
| Lote automático inicial | Una vez por cohorte | Al cargar el dashboard sin ningún caso analizado |
| Refresco de la SPA | 30 s | Solo con la pestaña visible |

## 6. Mantenimiento

| Tarea | Procedimiento |
|---|---|
| Nuevo modelo | Entrenar (`job.yaml`) → evaluar (`scripts/evaluate_model.py`) → desplegar (`deployment.yaml`) → `scripts/rescore_students.py` → actualizar `SQL_MODEL_VERSION` |
| Nueva cohorte | `scripts/seed_operational_data.py` o `scripts/replace_legacy_cohort.py` (genera respaldo en `outputs/backups/`) |
| Cambio de esquema SQL | Editar `sql_schema.sql` de forma idempotente y registrar la versión en `SchemaVersion` |
| Ajustar límites | `MAX_BATCH_SIZE` (código), `BATCH_TIMEOUT_MINUTES`, `SYNTHETIC_STUDENT_COUNT`, `MAX_EVALUATIONS_PER_PILOT` |
| Dependencias | Mantener alineados `requirements.txt` raíz, `azure/agent_platform/requirements.txt` y `environments/*.yaml` |

## 7. Escalabilidad

| Dimensión | Límite actual | Cómo escalar |
|---|---|---|
| Cohorte | 20.000 por defecto, 100.000 máx.; 15.000 desplegados | `SYNTHETIC_STUDENT_COUNT` + resiembra; la vista ejecutiva mantiene tamaño constante (validado 5k–100k) |
| Análisis | 20 casos por lote, 1 lote concurrente, hasta 80 llamadas LLM por lote | Subir `MAX_BATCH_SIZE`, `MAX_CONCURRENT_CASES` y la capacidad del despliegue OpenAI (50 en Bicep, 200 en vivo) |
| Cómputo | Function App con 1 instancia | `maximumInstanceCount` en Bicep |
| Mensajería | Service Bus Standard, `maxConcurrentCalls` 50 | Ajustar `host.json` |
| Base de datos | Serverless 1 vCore | Subir `maxCapacity` / SKU |
| Inferencia | 1 × `Standard_DS2_v2`, lotes de 200 | `instance_count` o autoscalado del endpoint |

## 8. Diagnóstico

| Síntoma | Causa probable | Acción |
|---|---|---|
| 401 en la SPA | Sesión caducada | Volver a iniciar sesión (`/.auth/login/aad`) |
| 403 | Usuario fuera de la allowlist | Añadir su object ID |
| 503 en todas las rutas | `DATA_MODE` distinto de `synthetic` o allowlist sin configurar | Revisar app settings |
| 429 al analizar | Ya hay un lote activo o se alcanzó el límite del piloto | Esperar (`Retry-After: 10`) o revisar `pilot/evaluation-counter.json` |
| Lote "Running" indefinido | Worker con error y mensajes reintentándose | `batch_reaper` lo cierra a los 20 min; revisar dead-letter de Service Bus |
| `POST /api/cases` nunca termina | Defecto del flujo Durable heredado | Usar `POST /api/batches` con `student_id` |
| Sin filas nuevas en SQL | Error silenciado en `audit_sql` o base en pausa | Buscar excepciones de `audit_sql` en Application Insights |
| La app no arranca tras desplegar | Paquete sin `src/` | Republicar desde una carpeta preparada con `src/` |
| `/api/ml/predict` devuelve 500 | Variables `AZURE_ML_ENDPOINT_*` no configuradas | Configurarlas o no usar la ruta |
| `POST` desde la SPA responde «La solicitud no fue aceptada» (`403`) | Dominio ausente de "Allowed external redirect URLs" de Easy Auth (protección CSRF) | Añadir el dominio de la app a esa lista y a CORS |
| `429` de Azure OpenAI | Capacidad insuficiente del despliegue `sat-gpt5-mini` | Subir la capacidad (en vivo: 200) |

## 9. Validación E2E del 2026-11-12

Registro de lo desplegado, corregido y verificado sobre `FUMCanalyticscore` (grupo `FUMC.CaseReviewer`, Brazil South, Flex Consumption, Python 3.11) con un usuario autenticado desde la interfaz. Flujo: Dashboard → «Analizar casos prioritarios» → Service Bus → 3 agentes (GPT-5-mini) → síntesis → revisión pendiente + Azure SQL.

### 9.1 Resultados

| Comprobación | Resultado |
|---|---|
| Lote lanzado desde la interfaz | **20 de 20 casos procesados, 0 fallidos**, en menos de 1 minuto |
| Orden de selección | Del mayor al menor riesgo (probabilidad del modelo descendente) |
| Persistencia en Azure SQL desde la app | **Verificada**: 20 predicciones, 20 propuestas, 80 ejecuciones de agente (4 por caso) y 20 eventos de auditoría |
| Conexión de la app a SQL | Registrada por la app: «Persistencia SQL activa: conexión a Azure SQL verificada» |
| Esquema SQL | 10 tablas, versión de esquema 1 (`baseline`) |
| Puntuación de la cohorte | 15.000 estudiantes puntuados por `sat-fumc-endpoint` (`blue`, `SAT_FUMC_LightGBM_Model` v2) |
| Pruebas automatizadas | 118 aprobadas, 1 omitida |

Cohorte desplegada: 15.000 filas en estudiantes, snapshots, targets, finanzas y bienestar; 44.994 registros académicos; 1.953 alertas; 11.035 seguimientos. Niveles de riesgo: Medio 9.082, Bajo 3.965, Alto 1.953 (105 críticos, probabilidad ≥ 0,80). La cohorte solo contiene semestres 7, 8 y 9 (estudiantes vigentes en 2025-2 del generador de entrenamiento). Los 5.000 estudiantes heredados se reemplazaron con respaldo en `outputs/backups/legacy_replacement_20261110T021848Z`.

### 9.2 Qué se guarda en Azure SQL

| Momento | Tablas |
|---|---|
| Al terminar cada caso | `ModelRelease`, `StudentSnapshot`, `Prediction`, `ReviewProposal`, `AgentExecution` (socioeconómico, académico, bienestar y síntesis, con salida, tokens, modelo e intento) y `AuditEvent` |
| Al aprobar, editar o rechazar una propuesta | `HumanDecision`, `Intervention` y `AuditEvent` |
| Al cambiar un seguimiento | `AuditEvent` |

La app se conecta con su identidad administrada (`db_datareader`, `db_datawriter`). Si SQL falla, el análisis continúa y el error queda en Application Insights.

### 9.3 Problemas encontrados y corregidos

| Síntoma | Causa | Corrección |
|---|---|---|
| «Procesar GPT» devolvía «La solicitud no fue aceptada» | Easy Auth rechazaba con `403` todo `POST` con cookie de sesión (CSRF): el origen no estaba en "Allowed external redirect URLs" | Dominio añadido a esa lista y a CORS |
| Actividades Durable sin registrar (`Can't bind parameter 'data' to type 'System.String'`) | Incompatibilidad del host con actividades Python | Flujo rehecho sobre Service Bus y Azure Tables |
| Workers con `TypeError … ChatMessageContent` | Semantic Kernel devuelve un objeto en `response.content` | Texto leído de `response.message.content` |
| Respuestas vacías de GPT-5-mini | El límite de 512 tokens incluía el razonamiento | 2.048 tokens por analista, 3.072 para la síntesis, esfuerzo de razonamiento `low` |
| `429` de Azure OpenAI | Capacidad de `sat-gpt5-mini` en 5 | Capacidad 200 (se factura por tokens) |
| Faltaba la cola `wellbeing-analysis` | Infraestructura anterior al Bicep actual | Cola creada con las mismas propiedades |
| Contratos rechazaban salidas válidas | Textos largos, campos ajenos, acciones en texto libre | Saneamiento previo al contrato estricto (recorte, descarte de campos, traducción a los cuatro códigos de acción) |
| 1 de 20 casos no llegó a SQL | Carrera al registrar la misma versión del modelo | `UPDLOCK, HOLDLOCK` en las comprobaciones y un reintento |
| Filtro de programa sin efecto | Opciones mal construidas; alertas filtradas por código y no por nombre | Cinco filtros acumulativos (sede, facultad, programa, semestre, riesgo) y resolución código → nombre |
| Dashboard y perfil lentos con 15.000 estudiantes | Escaneos completos y caché de 20 s | Columnas selectivas, cachés compartidas y renovación en segundo plano (filtros en 9–40 ms con caché caliente) |

### 9.4 Ejemplo de salida (caso sintético)

> **Diagnóstico — Crítico:** asociado a mora de 2 meses y saldo en mora de $1.084.663, estrato 6 y sin dependientes; coincide con tres asignaturas con nota inferior a 3,0 (TOP-A044: 2,0 y asistencia 15,1 %; TOP-A045: 2,1 y asistencia 49,3 %; TOP-A043: 2,3 y asistencia 51,3 %) y ausencia de acompañamiento registrado (0 sesiones, soporte no registrado). El foco prioritario de atención es la revisión financiera inmediata y la coordinación con apoyo académico y de bienestar para estabilizar condiciones administrativas y educativas mientras se verifican datos faltantes.

La salida es un borrador para revisión profesional: no ejecuta acciones ni contacta al estudiante.

### 9.5 Pendientes tras la validación

1. Reentrenamiento en Azure ML: los tres jobs fallaron al construir el entorno; se mantiene el modelo v2.
2. Puntuación en tiempo real: la cohorte se puntuó por script; la interfaz no llama al endpoint.
3. Cuatro actividades Durable heredadas siguen definidas y fallan al indexarse.
4. 360 mensajes de intentos anteriores en las colas dead-letter.
5. Retirar accesos temporales: roles del usuario de despliegue (Table, Blob, Service Bus Data Sender), regla de firewall `deploy-workstation` y diagnóstico `diag-http-auth`.
6. Revisar las métricas del experimento de 100k (prevalencia cercana al 84 % en la partición de prueba) antes de citarlas.
7. Validación visual de los modos claro y oscuro del dashboard.

## 10. Despliegue por fases

Plan para llevar la POC sintética a validación E2E en Azure. F2 y F3 son independientes; F5 requiere F3 y F6 requiere F2 y F5. Ninguna fase habilita uso con estudiantes reales.

| Fase | Objetivo y criterio de salida | Estado (2026-11-12) |
|---|---|---|
| F0 Línea base | Suite de pruebas en verde y CI activo | Cumplida localmente (118/1); ver riesgo de dependencias en [11 DevOps](./11_DevOps_CICD.md) |
| F1 Cohorte | Ampliar la cohorte sin resembrar ni alterar estados previos de alertas y seguimientos | Cohorte de 15.000 mediante `replace_legacy_cohort.py` (§9.1) |
| F2 Persistencia SQL | Escritura real en `Prediction`, `ReviewProposal`, `HumanDecision`, `Intervention` con identidad administrada | Escritura verificada (§9.2). Pendiente: políticas de retención y prueba de restauración |
| F3 ML y evaluación independiente | Modelo registrado y vinculado a `dbo.ModelRelease`; informe de `evaluate_model.py` versionado | Modelo v2 en producción de la POC; reentrenamiento en AML fallido |
| F4 Frontend/API | Verificador con `SAT_BASE_URL`/`SAT_BEARER_TOKEN` sin `FAIL` en el bloque 8; `REVIEWER_AUTH_ENFORCED=true` | `200` autenticado y lote desde la SPA; falta revisión visual |
| F5 AML ↔ Functions | Contrato común, versión aprobada, `/api/ml/predict` probado (errores, timeout, idempotencia, dead-letter) | Cohorte puntuada por el endpoint v2 vía script; sin puntuación en tiempo real |
| F6 End-to-end | Caso completo con `--allow-writes` hasta revisión humana, intervención y consulta posterior en SQL (bloque 9) | Flujo de lote verificado; falta registrar evidencia de decisión humana e intervención |

**Ampliación de cohorte sin resembrar.** `_ensure_database` solo inserta IDs mayores que `StudentCount` (en `SyntheticControl`) con `create_if_missing`, y los datos operativos solo agregan los faltantes. En el arranque en frío la siembra se limita a `SYNTHETIC_COLD_START_LIMIT` (5.000 por defecto); cohortes mayores se cargan con `seed_operational_data.py` o `replace_legacy_cohort.py`. Reducir `SYNTHETIC_STUDENT_COUNT` por debajo de lo sembrado aborta con error. Procedimiento: respaldar las tablas `Synthetic*`, registrar conteos de estudiantes, alertas y seguimientos por estado, ampliar y comprobar que los IDs previos y sus estados no cambiaron. La siembra en frío ocurre en la primera petición HTTP: si excede el tiempo límite se reintenta de forma idempotente, pero el primer usuario recibe un error.
