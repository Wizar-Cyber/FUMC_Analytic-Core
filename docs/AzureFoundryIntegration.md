# Integración SAT-FUMC con Azure Machine Learning y Fabric/Power BI

Este documento describe el flujo implementado para una POC con Parquet sintético. Requisitos institucionales, integración de fuentes reales, privacidad y criterios de aceptación están en [ProductionReadiness.md](./ProductionReadiness.md).

La arquitectura nueva de agentes LLM está separada del flujo de Azure ML en [DistributedAgentsAzure.md](./DistributedAgentsAzure.md). El preflight confirmó GPT-5-mini GlobalStandard (`2025-08-07`) con 500.000 TPM disponibles en Brazil South; no se envió solicitud de aumento ni se requiere tarjeta/formulario de cuota para el POC autorizado. Ya se aprovisionaron la cuenta AI Services y el deployment GPT-5-mini con capacidad 5; aún no se ha ejecutado inferencia ni desplegado la app, AI Search, Service Bus o Functions. El código usa Chat Completions API `2025-04-01-preview`, `max_completion_tokens` y omite `temperature` para GPT-5. El piloto queda limitado a 10.000 evaluaciones, una concurrente, solo datos sintéticos y revisión humana; el primer test será un caso manual y luego se pausa. Revisar [el estado de preflight, costos y tareas pendientes](./DistributedAgentsAzure.md) antes de aprovisionar más recursos; no existe un hard cap de costo de Azure.

## Alcance actual

- Entrenamiento LightGBM en Azure ML con split temporal y tracking MLflow del Workspace.
- Registro del modelo `SAT_FUMC_LightGBM_Model` y artefactos de evaluación.
- Predicciones batch exportadas como Parquet y CSV.
- Dashboard HTML agregado para verificación rápida y consumo Power BI/Fabric desde el almacenamiento autorizado.
- Endpoint administrado opcional que recibe un lote acotado y valida las variables requeridas por el modelo.

El endpoint no extrae datos de SIS/LMS. Para producir scores se debe entregar el vector vigente de variables al endpoint o ejecutar el flujo batch sobre el Data Lake.

## Entrenamiento por lotes

Con Azure CLI, extensión ML, acceso al Workspace y un compute válido:

```powershell
az extension add --name ml
az login
az ml job create --file azure/components/job.yaml --stream
```

El job de `azure/components/job.yaml` recibe `data_folder` como `uri_folder`; el path incluido apunta a los Parquet sintéticos del repositorio para la POC. Para un Data Asset remoto, actualizar ese input a `azureml:<nombre>:<versión>`. El nombre del compute `cpu-cluster` debe existir en el Workspace o sustituirse por uno aprobado.

En cada ejecución validar el reporte temporal, target, Recall, precisión, AUC, Brier, explicabilidad, artefactos y estado de registro. Un resultado histórico de Recall 73,2% es una cifra reportada en documentación previa, no un resultado reproducido en este job ni cumplimiento del objetivo documental ≥0,80.

Una vez aprobado el modelo, ejecutar `azure/components/scoring_job.yaml` para correr la secuencia completa de agentes en Azure ML. Actualizar en ese manifiesto la versión del modelo y el Data Asset de scoring; produce el Parquet para Power BI, el reporte de monitoreo y el dashboard HTML.

## Endpoint de scoring

Los manifiestos están en `azure/endpoints/endpoint.yaml` y `azure/endpoints/deployment.yaml`; el entorno está definido en `azure/environments/online-environment.yaml`. Actualizar el ID de versión del modelo y confirmar SKU/región/cuota antes de crear recursos:

```powershell
az ml environment create --file azure/environments/online-environment.yaml
az ml online-endpoint create --file azure/endpoints/endpoint.yaml
az ml online-deployment create --file azure/endpoints/deployment.yaml --all-traffic
```

`azure/endpoints/score.py` acepta `{"data": [...]}`, valida el contrato del modelo y limita cada solicitud a 1.000 filas (configurable por `MAX_BATCH_SIZE`). El umbral inicial es 0,35 (`ALERT_THRESHOLD`). Ambos valores son parámetros de POC y deben aprobarse con validación institucional, latencia y capacidad antes de producción.

Para una prueba de endpoint usar solo datos sintéticos, la autenticación del endpoint y `az ml online-endpoint invoke`. No guardar claves de endpoint en código, notebooks o logs. Las respuestas son predicciones de apoyo; un profesional debe revisar cualquier intervención.

## Power BI / Fabric

El job escribe `predicciones_powerbi.parquet`, `predicciones_powerbi.csv` y `dashboard_resumen.html` en su carpeta de salida Azure ML. El HTML es autocontenido y agregado; no es un reporte PBIX ni un modelo semántico publicado. Para visualización institucional copiar/publicar el Parquet en ADLS Gen2/OneLake autorizado, crear el modelo semántico y reporte Power BI, configurar actualización y aplicar identidad, roles y políticas de acceso aprobadas.

Para datos por corte/diarios, el batch score más la actualización programada de Power BI es el patrón inicial recomendado. Un endpoint online no garantiza actualización en tiempo real de Power BI ni disponibilidad de la fuente.
