# Preparación para Azure y operación institucional

## Estado comprobado de esta POC

La última ejecución batch local procesó 27.975 filas, creó 59 features y produjo las salidas Power BI/HTML. En calidad, 7 de 9 reglas evaluables pasaron; hubo 14 valores `avance_plan_pct` fuera del rango 0–100 (marcados como faltantes), faltantes sin motivo normalizado y cuatro reglas no evaluables.

- Los Parquet disponibles son un Digital Twin sintético: no existe aún un conector a SIS, LMS, finanzas ni bienestar.
- La unidad de evaluación es estudiante × periodo. Hay 27.975 registros sintéticos de 6.000 estudiantes y una tabla separada de trazabilidad/target. El generador impone un máximo de 35.000 filas en estas dos tablas; las tablas auxiliares pueden ser mayores.
- La red actual son etapas Python determinísticas (ingesta, calidad, features, scoring, reglas de intervención y monitoreo); no son agentes LLM autónomos ni ejecutores distribuidos.
- El entrenamiento Azure y local ahora comparten el contrato de features. La calidad bloquea llaves, etiquetas o cobertura inválidas y el endpoint comprueba el contrato del modelo.
- El agente implementa las 13 categorías de calidad del diccionario institucional; disponibilidad a fecha de corte y fairness quedan explícitamente no evaluables cuando faltan datos/etiquetas de referencia. Los valores fuera de rango se marcan faltantes para el imputador y se reportan.
- La ejecución genera Parquet/CSV para Power BI y un HTML agregado, autocontenido y sin identificadores individuales.
- Azure CLI y `azd` están autenticados localmente. Para la POC de agentes se creó una cuenta AI Services y un deployment GPT-5-mini; no se han creado jobs, endpoints de Azure ML, reportes Power BI ni conexiones a datos reales desde este entorno.
- Hay una app experimental separada en `azure/agent_platform` para agentes Semantic Kernel distribuidos; está configurada como código, pero no desplegada ni conectada a un modelo, índice RAG, cola o fuente institucional. Ver [DistributedAgentsAzure.md](./DistributedAgentsAzure.md).

El proyecto es una POC técnica; no está aprobado para decisiones estudiantiles productivas. Antes de usar datos reales se requieren autorización institucional, evaluación de privacidad, validación académica, plan de intervención humana y aprobación de TI/seguridad.

La nueva app de agentes LLM mantiene las mismas restricciones y no reemplaza el scoring determinístico existente. La recomendación LLM es solo un borrador; para iniciar una intervención, el equipo debe revisar y registrar una decisión.

La corrida reducida de entrenamiento (20 árboles, solo para validar el script) obtuvo Recall 1,00, precisión 0,105, AUC 0,648 y F1 0,190 en datos sintéticos. No es una evaluación de modelo aprobada: demuestra que Recall alto puede generar demasiadas alertas y que hay que validar precisión, calibración, carga de intervención y cohortes reales antes de escoger un umbral.

## Arquitectura recomendada por fases

### Fase 1 — POC con Parquet (ahora)

El batch actual procesa en memoria con pandas y se validó solo con 27.975 filas; no hay pruebas de carga ni SLA medido. Para volúmenes mayores se requiere benchmark y posiblemente procesamiento particionado con Fabric/Spark/Azure ML, más scoring batch escalable.

1. Mantener los Parquet versionados como entregas inmutables en Azure Blob Storage o ADLS Gen2. No es necesario crear una base transaccional solo para entrenar un modelo tabular.
2. Registrar el conjunto como Azure ML Data Asset `uri_folder`; entrenar y evaluar con un Azure ML Command Job.
3. Guardar modelo registrado, métricas, predicciones y reportes en el Workspace/ADLS. Ejecutar scoring batch por corte académico (o diario mientras se valida la operación).
4. Conectar Power BI/Fabric al Parquet de salida en ADLS/OneLake y programar la actualización de su modelo semántico. El HTML local es un resumen rápido; no reemplaza un PBIX/modelo semántico con identidad y seguridad institucional.

### Fase 2 — Integración con fuentes reales

Primero definir el sistema fuente, propietario, tablas/API, claves, semántica temporal, SLA, mecanismo de extracción y autorización. Para extracción programada usar Data Factory o Fabric Data Factory; para APIs/eventos que de verdad requieran segundos/minutos, evaluar Logic Apps/API Management o Event Hubs según el mecanismo que ofrezca el sistema fuente. En ambos casos validar y conservar los datos curados en el lake antes de usarlos.

Un endpoint online solo calcula un score a partir de atributos que ya recibió: no consulta ni sincroniza por sí mismo el SIS/LMS. Una frecuencia corta no convierte datos atrasados en tiempo real. La universidad debe confirmar si un corte diario/horario satisface el proceso de acompañamiento.

Considerar Azure SQL/Fabric Warehouse cuando haya una necesidad demostrada de transacciones, consulta concurrente de baja latencia, integración operacional de casos/intervenciones o contratos SQL. No usarlo como requisito previo para almacenar Parquet histórico de entrenamiento.

### Fase 3 — Producción institucional

- Despliegue IaC, ambientes dev/test/prod, aprobación de modelo y rollback; despliegues blue/green y pruebas de carga antes de habilitar tráfico.
- Managed Identity para Azure ML, Storage y Power BI; RBAC de mínimo privilegio, secretos en Key Vault, redes privadas cuando lo exija TI y auditoría de accesos.
- Clasificación de datos, minimización/pseudonimización, tabla de correspondencia protegida fuera del modelo, retención y borrado definidos por el responsable institucional.
- Revisiones periódicas de calibración, deriva, falsos negativos, cobertura y equidad con etiquetas reales. No llamar “drift” a una tasa alta de riesgo sin compararla con una línea base.
- Revisión humana de cada alerta/intervención; el sistema no debe negar servicios ni producir decisiones académicas/financieras automatizadas.

## Contrato de datos y ML

- `estudiante_periodo_corte.parquet`: una fila por `id_estudiante_anon + periodo_id`; llaves no nulas y únicas.
- `target_trazabilidad.parquet`: etiquetas de entrenamiento, binaria y separada de los predictores. Nunca se envía al endpoint de inferencia.
- La predicción acepta registros con las columnas esperadas por el modelo registrado y calcula las mismas features derivadas que el entrenamiento. Cambios al esquema requieren entrenar/versionar/publicar un nuevo modelo.
- La validación temporal usa por defecto los dos periodos más recientes disponibles; se deben confirmar las ventanas de etiqueta y que no exista leakage temporal antes de aceptar métricas.
- Las recomendaciones del agente de explicabilidad son reglas de negocio, no valores SHAP causales. La explicación debe mostrarse como apoyo al profesional, no como causa probada.

## Ejecución Azure ML

Requisitos: Azure CLI con extensión `ml`, acceso RBAC al Workspace, Storage disponible y un compute `cpu-cluster` creado (o actualizar `compute` en `azure/components/job.yaml` al recurso autorizado). Autenticarse en el terminal con `az login`; no almacenar credenciales en archivos.

Desde la raíz del repositorio, configurar la suscripción y valores por defecto del Workspace definidos en `config.json`:

```powershell
az extension add --name ml
az login
$config = Get-Content .\config.json | ConvertFrom-Json
az account set --subscription $config.subscription_id
az configure --defaults group=$config.resource_group workspace=$config.workspace_name

az ml data create --name fumc-sat-data --version 1 `
  --path ./data/raw --type uri_folder
```

El archivo `.amlignore` excluye datos, modelos, outputs, `mlruns` y documentos del snapshot de código; los Parquet solo se envían como input explícito del job/Data Asset. Revisar esta lista antes de incorporar nuevos directorios con datos institucionales.

Para una corrida de POC con los Parquet locales, revisar que `azure/components/job.yaml` apunte a `../../data/raw` y lanzar:

```powershell
az ml job create --file azure/components/job.yaml --stream
```

Al usar el Data Asset de Storage, sustituir el `path` de `data_folder` por `azureml:fumc-sat-data:1`. Revisar métricas, split temporal, artefactos, registro del modelo y salida HTML/Parquet antes de promoverlo. No considerar aprobado un modelo solo porque el job terminó correctamente.

Después de aprobar una versión del modelo, ejecutar la red completa de agentes sobre el lote de scoring:

```powershell
az ml job create --file azure/components/scoring_job.yaml --stream
```

El manifiesto de scoring referencia la versión 1 del modelo para la POC. Actualizarla a la versión realmente registrada y usar el Data Asset versionado para `data_folder`. Esta ejecución produce predicciones, reporte de calidad/monitoreo, recomendaciones heurísticas y dashboard agregado.

Para el endpoint de prueba, confirmar primero región, SKU, cuota, permisos y coste. Crear el entorno y los recursos con los nombres/versiones aprobados:

```powershell
az ml environment create --file azure/environments/online-environment.yaml
az ml online-endpoint create --file azure/endpoints/endpoint.yaml
az ml online-deployment create --file azure/endpoints/deployment.yaml --all-traffic
```

`deployment.yaml` referencia la versión 1 del modelo y un tamaño de instancia de ejemplo; actualizar ambos al modelo y SKU disponibles en el Workspace. Probar autenticación, esquema, latencia, lote máximo y errores con datos sintéticos antes de habilitar consumo institucional.

La configuración del Workspace se lee de `config.json` y puede sobrescribirse con `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP` y `AZUREML_WORKSPACE_NAME`. En Azure usar Managed Identity; localmente usar una sesión Azure CLI autorizada.

## Visualización

- El pipeline local produce `outputs/dashboard_resumen.html` y `outputs/predicciones_multiagente_powerbi.parquet`.
- El job de entrenamiento Azure produce `dashboard_resumen.html` y `predicciones_powerbi.parquet` en su carpeta de salida.
- El dashboard HTML contiene agregados por riesgo, sede y programa; no expone IDs individuales. El acceso a las tablas de detalle en Power BI debe tener roles, propósito definido y controles institucionales.
- No hay un archivo PBIX publicado ni un modelo semántico Power BI dentro del repositorio. Deben construirse en el tenant autorizado usando las salidas curadas y medidas validadas por la Universidad.

## Criterios de aceptación antes de producción

1. Conector a fuente real autorizado, contrato de datos y SLA de actualización acordados.
2. Tests de calidad/leakage, integración, scoring, carga, seguridad y recuperación aprobados.
3. Recall, precisión, calibración y brechas entre grupos validados con cohortes reales y aprobados por responsables académicos; resolver el objetivo documentado de Recall ≥ 0,80 frente al 73,2% reportado en una prueba anterior.
4. Dataset Power BI y HTML con cifras reconciliadas con la corrida, control de acceso y revisión de privacidad.
5. Propietarios operativos, alertas, revisión humana, retención, soporte, rollback y reentrenamiento documentados.
