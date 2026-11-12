# Runbook de validación de producción

Procedimiento para verificar los bloques 4 a 9 del checklist de preparación. Cada ítem queda en uno de estos estados: PASS, FAIL, PENDING (falta entorno Azure) o MANUAL (evidencia humana).

## Ejecución

```powershell
# Solo chequeos locales (no requiere Azure)
python scripts/validate_readiness.py

# Contra el despliegue (solo lectura)
$env:SAT_BASE_URL = "https://<function-app>.azurewebsites.net"
$env:SAT_BEARER_TOKEN = "<token de un reviewer autorizado>"
python scripts/validate_readiness.py

# Con escrituras de prueba (crea seguimientos y blobs de validación)
python scripts/validate_readiness.py --allow-writes
```

Variables opcionales: `SAT_SQL_CONNECTION` (requiere `pyodbc`), `SAT_STORAGE_CONNECTION`, `SAT_STORAGE_CONTAINER`, `SAT_PREDICT_PAYLOAD` (ruta a un JSON con el contrato de `/api/ml/predict`).

Salida: `outputs/readiness_report.md`. El código de salida es 1 si hay algún FAIL. Un PASS local no sustituye la verificación en Azure: el informe indica en la evidencia qué se comprobó.

## Procedimientos por bloque

### 4. Datos y almacenamiento

| Ítem | Cómo verificar |
|---|---|
| Blob carga/recupera | Verificador con `--allow-writes` y variables de storage. |
| Permisos de contenedores | `az role assignment list --scope <storage-id>`: la identidad de la Function debe tener `Storage Blob Data Contributor` y nadie más con acceso amplio. |
| SQL acepta conexiones | Verificador con `SAT_SQL_CONNECTION`; revisar reglas de firewall y Entra ID. |
| Migraciones | Aplicar `infra/sql_schema.sql`; hoy no hay tabla de versiones (ver F2 del plan). |
| Tablas, índices, relaciones | Verificador: espera 10 tablas (incluye `SchemaVersion`) y FK en `dbo`. |
| CRUD | Pendiente: el repositorio no tiene driver real ni lecturas (el verificador marca FAIL). |
| Sintético separado | Verificador: target fuera de snapshots y `DataMode='synthetic'` en SQL. |
| Estudiante/periodo/corte | Verificador: columnas de `StudentSnapshot`. |
| Respaldos y retención | `az sql db show` / `az sql db ltr-policy show` / `az sql db str-policy show`. |

### 5. Pipeline de ML

- Entrenar en AML con `python azure/train_azure.py` y adjuntar el enlace del job.
- Tests locales de esquema, características compartidas y particiones temporales: los ejecuta el verificador.
- MLflow: hoy el tracking es una carpeta local (`mlruns`), no el workspace de AML. Para marcar este ítem como cumplido en Azure hay que apuntar `mlflow.set_tracking_uri` al workspace.
- Versión aprobada: `az ml model list` y registro en `dbo.ModelRelease`.
- Bloqueo de promoción: `select_recall_threshold` con `minimum_recall=0.80` rechaza umbrales que no cumplen; cubierto por `tests/test_model_selection.py`.

### 6. Validación predictiva

1. Cargar el modelo registrado en un script independiente del entrenamiento.
2. Evaluar sobre el conjunto de prueba reservado usando el umbral fijado en validación.
3. Reportar Recall, Precision, F1, AUC-ROC, AUC-PR, Brier, matriz de confusión (FP y FN) y si Recall >= 0,80.
4. Declarar explícitamente que los resultados son sintéticos.

Las métricas existen en `train_pipeline.py`, pero ese cálculo ocurre en el mismo proceso de entrenamiento; no cuenta como evaluación independiente.

### 7. Red multiagente

- Contratos y esquemas JSON: `tests/test_distributed_agent_contracts.py` (los ejecuta el verificador).
- GPT-5-mini: ejecutar un caso y confirmar en la respuesta/telemetría el despliegue `sat-gpt5-mini` del recurso `FUMCAnalitysReviewer`.
- Trazabilidad: buscar el `instance_id` del caso en Application Insights.
- Fallos: forzar timeout y error del modelo, y confirmar estado del caso, reintento y DLQ en Service Bus.

### 8. API y frontend

El verificador comprueba SPA, autenticación (401/403 sin token), dashboard, estudiantes, ficha, revisiones, seguimiento (con `--allow-writes`) y errores de API. Sigue siendo manual: consistencia predicción/endpoint, visualización de resúmenes y flujo de aprobación/rechazo en navegador.

### 9. End-to-end

1. Elegir un estudiante sintético y ejecutar `POST /api/cases`.
2. Consultar `GET /api/cases/{instance_id}` hasta estado final.
3. Revisar la propuesta en `/api/reviews` y aprobar/rechazar.
4. Crear la intervención con `POST /api/poc/followups` y consultarla.
5. Confirmar que cada paso queda en SQL (bloqueado hasta completar F2).

## Hallazgos abiertos del primer informe local

| Hallazgo | Impacto |
|---|---|
| Repositorio SQL con `FakeConnection` por defecto, sin driver ni lecturas | Bloquea CRUD y persistencia end-to-end; las escrituras se descartarían en silencio. |
| MLflow con tracking local | El registro de experimentos no está en AML. |
| Sin evaluación independiente del modelo | Bloque 6 no puede declararse cumplido. |
| Sin historial de migraciones SQL | No se puede demostrar qué esquema está aplicado. |
