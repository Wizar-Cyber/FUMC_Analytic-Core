# 10.01 | Azure Machine Learning, Azure OpenAI y Foundry

> Documento subordinado a [`ProductionArchitecture.md`](./ProductionArchitecture.md), que es la fuente de verdad de arquitectura y estado.

## 1. Componentes en código y Azure

- `azure/train_azure.py` entrena LightGBM en un job Azure ML, registra métricas/artefactos y ahora aplica calibración temporal del umbral con una compuerta de promoción.
- `azure/endpoints/score.py` define el scoring AML y puede leer el umbral calibrado del artefacto.
- `azure/agent_platform/` usa Semantic Kernel y Azure OpenAI GPT-5-mini desde Azure Functions y Service Bus para una demo sintética con agentes académico, financiero y bienestar.
- Azure AI Foundry no es actualmente el host del runtime de los agentes; se considera para evaluación y gobierno de prompts/agentes.
- Verificación al 2026-11-12: el deployment `sat-gpt5-mini` está `Succeeded` con capacidad 200 y la Function App `FUMCanalyticscore` ejecutó un lote autenticado de 20 casos sin fallos; ver [`E2EValidation.md`](./E2EValidation.md).

## 2. Límite importante: despliegue no es integración

La POC distribuida no invoca el endpoint AML: sus puntuaciones iniciales se generan dentro del Digital Twin. Los jobs/manifiestos AML no acreditan que un endpoint independiente esté desplegado, disponible o conectado. Azure SQL está provisionado y su esquema aplicado, pero la API de la POC todavía persiste en Tables/Blob y no llama al repositorio SQL. El inicio de sesión interactivo y la respuesta API autorizada tampoco se verificaron.

## 3. Entrenamiento y promoción

La ventana final de test no se usa para escoger hiperparámetros ni umbral. El job selecciona una configuración acotada de LightGBM en una ventana temporal interna; si no cumple el Recall mínimo en validación y holdout sin caer en el caso degenerado de alertar a todo el mundo, el modelo no se registra como promovible. La promoción requiere además evaluación institucional, revisión de fairness, calibración y aprobación humana.

El Recall ≥ 0,80 es un objetivo pendiente. Los datos sintéticos no son evidencia de desempeño FUMC. Consulte [arquitectura objetivo y gates](./ProductionArchitecture.md#5-criterios-de-habilitación-institucional).

## 4. Seguridad y operación

Usar Managed Identity, RBAC de mínimo privilegio y Key Vault; nunca incluir endpoint keys o secretos en manifiestos/archivos versionados. En producción, agregar CI/CD con OIDC, evaluación del modelo y agentes, aprobación por ambiente, monitoreo App Insights, alertas, rollback y redes aprobadas por TI. No ejecutar provisioning ni inferencia institucional sin autorización explícita.
