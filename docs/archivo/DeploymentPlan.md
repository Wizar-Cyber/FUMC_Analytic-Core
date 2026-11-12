# Plan de despliegue por fases

Alcance: llevar la POC sintética de SAT-FUMC desde el estado actual hasta una validación end-to-end en Azure. Todos los resultados siguen siendo sintéticos; ninguna fase habilita uso con estudiantes reales.

Estado de partida y evidencia: `python scripts/validate_readiness.py` (informe en `outputs/readiness_report.md`).

## Dependencias entre fases

```
F0 Línea base ──► F1 Cohorte 10k ──► F4 Frontend/API reales ──┐
      │                                                        ├─► F6 End-to-end
      ├──► F2 Persistencia SQL ───────────────────────────────┤
      └──► F3 ML + validación independiente ──► F5 AML ↔ Functions
```

F2 y F3 son independientes y pueden avanzar en paralelo. F5 requiere F3 (modelo aprobado) y F6 requiere F2 y F5.

## F0. Línea base (hecha en local)

- Suite completa en verde (73 tests) y CI ejecutándose.
- Tests de catálogo y cohorte alineados con 10.000 estudiantes, 10 programas y 5 sedes.
- Criterio de salida: `pytest -q` sin fallos en `main`.

## F1. Cohorte de 10.000 sin resembrar

Cambio de código ya aplicado en `sat_agents/synthetic_database.py`:

- `_ensure_database` inserta solo IDs mayores que `StudentCount` guardado en `SyntheticControl`; usa `create_if_missing`.
- `_ensure_operational_data` ya no borra alertas ni seguimientos; solo agrega los faltantes y reescribe las tendencias simuladas. Se dispara por versión o por crecimiento de la cohorte (`OperationalStudentCount`).
- Reducir `SYNTHETIC_STUDENT_COUNT` por debajo de lo sembrado aborta con error.

Pasos:

1. Respaldar las tablas `Synthetic*` (copia de Table Storage con AzCopy o export a otra cuenta).
2. Registrar línea base: conteo de estudiantes, alertas por estado, seguimientos por estado.
3. Publicar la Function App con `SYNTHETIC_STUDENT_COUNT=10000` (o sin la variable).
4. Primera llamada a cualquier endpoint `/api/poc/*` dispara la ampliación (cold start más lento; puede tardar varios minutos con 5.000 estudiantes nuevos y 5 tablas).
5. Verificar: `SyntheticStudents` = 10.000; IDs 1–5000 sin cambios; estados de alertas/seguimientos previos intactos; alertas nuevas solo para IDs 5001–10000.

Criterio de salida: conteos esperados y estados previos idénticos a la línea base.

Riesgos:
- El sembrado carga estudiantes y snapshots completos en memoria. Con 10.000 es aceptable; antes de subir hacia 100.000 hay que paginar o mover el sembrado a un job fuera del cold start.
- El sembrado corre en la primera petición HTTP; si excede el timeout de la Function, reintenta de forma idempotente, pero el primer usuario ve error.

## F2. Persistencia en Azure SQL

Bloqueo confirmado por el verificador: `src/persistence/sql_repository.py` usa `FakeConnection` por defecto, no tiene driver real ni operaciones de lectura.

1. Decidir el driver (`pyodbc` con ODBC Driver 18 en Linux Functions, o `mssql-python`) y autenticación (Managed Identity recomendada sobre contraseña).
2. Quitar el fallback a `FakeConnection` en el repositorio; moverlo al fixture de tests.
3. Agregar lecturas (`get_*`/`list_*`) y una tabla de versiones de esquema para registrar migraciones.
4. Aplicar `sql_schema.sql` en un entorno no productivo y ejecutar `SAT_SQL_CONNECTION=... python scripts/validate_readiness.py`.
5. Conectar Functions a SQL tras flag de configuración; mantener Table Storage hasta validar paridad.
6. Configurar retención a corto y largo plazo y probar un restore.

Criterio de salida: roundtrip real escribir/leer de `Prediction`, `ReviewProposal`, `HumanDecision`, `Intervention`.

## F3. ML y validación independiente

1. Ejecutar `azure/train_azure.py` en AML con el dataset del generador (10 programas, 5 sedes).
2. Registrar el modelo con versión y vincularlo a `dbo.ModelRelease`.
3. Crear un script de evaluación independiente que cargue el modelo registrado y evalúe sobre el conjunto de prueba reservado con el umbral fijado en validación. Hoy las métricas se calculan dentro de `train_pipeline.py`, por lo que no cuentan como evaluación independiente.
4. Reportar Recall, Precision, F1, AUC-ROC, AUC-PR, Brier, matriz de confusión, FP y FN, y si Recall >= 0,80 se alcanzó. Etiquetar todo como sintético.

Criterio de salida: informe de evaluación versionado junto al modelo.

## F4. Frontend y API sobre datos reales del backend

1. Ejecutar el verificador con `SAT_BASE_URL` y `SAT_BEARER_TOKEN` (reviewer autorizado).
2. Confirmar `REVIEWER_AUTH_ENFORCED=true` en la Function App.
3. Revisión visual de dashboard, ficha y errores en navegador.

Criterio de salida: bloque 8 sin FAIL ni PENDING remoto.

## F5. Integración AML ↔ Functions

Actualización 2026-11-12: la cohorte operativa (15.000 estudiantes, que reemplazó a los 5.000 iniciales) se puntuó con el endpoint AML v2; ver [`E2EValidation.md`](./E2EValidation.md).

1. Definir el contrato común (snapshot/versión) y registrar `AZURE_ML_ENDPOINT_URL`, `AZURE_ML_ENDPOINT_KEY` y `AZURE_ML_DEPLOYMENT_NAME` en Key Vault.
2. Probar `/api/ml/predict` con `SAT_PREDICT_PAYLOAD`.
3. Verificar que la versión desplegada es la aprobada en F3 y que los agentes no alteran la probabilidad.
4. Probar errores, timeout, idempotencia y DLQ.

## F6. End-to-end

Ejecutar un caso completo con `--allow-writes`: registro, predicción, orquestación, resumen, recomendaciones, almacenamiento en SQL, recuperación por API, revisión humana, intervención y consulta posterior. Criterio de salida: bloque 9 completo con evidencia adjunta.

## Reversa

- Código: redeploy del paquete anterior (la versión 5 no entiende `OperationalStudentCount`, pero lo ignora).
- Datos F1: las inserciones son aditivas; revertir implica borrar IDs 5001+ de las tablas `Synthetic*` (nunca los 5.000 originales) y restaurar `StudentCount=5000` en `SyntheticControl`. Hacerlo solo con el respaldo del paso 1.
