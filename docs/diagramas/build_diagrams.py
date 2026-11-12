"""Genera los 14 diagramas de arquitectura del SAT-FUMC.

Uso:  python docs/diagramas/build_diagrams.py [nombre ...]
Salida: docs/diagramas/*.svg (fuente autocontenida) y docs/imagenes/*.png.

Cada diagrama refleja solo lo implementado en el código del repositorio
(árbol de trabajo a 2026-11-12). Los elementos con defecto conocido,
deshabilitados u opcionales se dibujan con línea discontinua.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine import Diagram, render  # noqa: E402


# 1. Estructura del repositorio ------------------------------------------------
def estructura() -> Diagram:
    d = Diagram(
        "01_estructura_repositorio",
        "Estructura del repositorio",
        1500,
        900,
        "Carpetas versionadas y su dependencia principal (flecha = 'usa / importa')",
    )
    d.node("fa", "function_app.py", 200, 170, "azure-functions", "35 funciones · API + workers")
    d.node("sat", "sat_agents/", 200, 330, "python", "agentes, contratos, datos,\nlotes, vista ejecutiva")
    d.node("static", "static/", 440, 170, "javascript", "SPA HTML/CSS/JS")
    d.node("infra", "infra/", 440, 330, "azure-resource-group", "main.bicep · budget.bicep\nsql_schema.sql · deploy.ps1")
    d.group("azure/agent_platform/  (plataforma operativa)", ["fa", "sat", "static", "infra"], "azure", icon="azure-functions")

    d.node("train", "train_azure.py", 680, 330, "azure-machine-learning", "entrenamiento LightGBM")
    d.node("comp", "components/ · environments/", 680, 170, "azure-machine-learning", "job.yaml · conda.yaml")
    d.node("endp", "endpoints/", 900, 170, "azure-machine-learning", "endpoint.yaml · score.py\nmodel_code/ (copia de src/)")
    d.node("aml_boot", "infra_fumc_brazil.bicep\ndeploy_azure_resources.py", 900, 330, "azure-resource-group", "workspace AML (legado)")
    d.group("azure/  (Azure Machine Learning)", ["train", "comp", "endp", "aml_boot"], "ml", icon="azure-machine-learning")

    d.node("pers", "persistence/", 200, 560, "azure-sql-database", "repositorio Azure SQL")
    d.node("ml", "ml/", 500, 560, "python", "features · selección\nscoring endpoint · feedback")
    d.node("lagents", "agents/ + run_multiagent\n_system.py", 760, 560, "python", "pipeline local (sin LLM)", w=200)
    d.node("gen", "data_generation/", 1000, 560, "python", "Digital Twin sintético")
    d.group("src/  (núcleo Python compartido)", ["gen", "ml", "pers", "lagents"], "data", icon="python")

    d.node("scripts", "scripts/", 1260, 170, "python", "seed · rescore · replace\nrecalibración · readiness")
    d.node("tests", "tests/", 1260, 330, "python", "13 archivos pytest")
    d.node("ci", ".github/workflows/", 1260, 560, "github-actions", "ci.yml (pytest)")
    d.group("Operación y calidad", ["scripts", "tests", "ci"], "ops")

    d.node("models", "models/", 180, 790, sub="*.joblib locales", w=170)
    d.node("data", "data/  (ignorado)", 400, 790, sub="raw · processed · predictions", w=190)
    d.node("outputs", "outputs/", 650, 790, sub="recalibration · reportes · backups", w=210)
    d.node("cfg", "configs/", 1000, 790, sub="synthetic_data.json", w=170)
    d.node("docs", "docs/ · entregables/", 1190, 790, sub="documentación · artículo", w=190)
    d.node("dash", "dashboards/", 1385, 790, sub="render_summary.py", w=170)
    d.group("Configuración, artefactos y documentación", ["cfg", "models", "data", "outputs", "docs", "dash"], "external")

    d.link("fa", "sat")
    d.link("fa", "static", "sirve")
    d.link("sat", "pers", "audit_sql", tone="azure")
    d.link("fa", "ml", "feedback_loop", tone="azure", label_pos=0.72)
    d.link("train", "ml", "features", tone="ml", label_pos=0.7)
    d.link("lagents", "ml", "")
    d.link("gen", "cfg", "lee")
    d.link("ci", "tests", "pytest")
    d.note(40, 875, "scripts/ importa sat_agents (synthetic_database, training_cohort, rescoring, legacy_replacement) y src/ml. endpoints/model_code/ contiene una copia de src/ml usada por score.py.")
    return d


# 2. Arquitectura general ------------------------------------------------------
def general() -> Diagram:
    d = Diagram(
        "02_arquitectura_general",
        "Arquitectura general",
        1500,
        780,
        "Capas implementadas: presentación, identidad, backend, agentes, datos, ML y observabilidad",
    )
    d.node("users", "Equipo de permanencia", 110, 170, "users", "revisores en allowlist")
    d.node("spa", "SPA web", 320, 170, "javascript", "HTML · CSS · JS")
    d.node("entra", "Microsoft Entra ID", 560, 170, "microsoft-entra-id", "Easy Auth")
    d.node("func", "Function App", 790, 170, "azure-functions", "Python 3.11 · Flex FC1\n23 rutas HTTP")
    d.node("sb", "Service Bus", 1020, 170, "azure-service-bus", "4 colas")
    d.node("aoai", "Azure OpenAI", 1250, 170, "azure-openai", "gpt-5-mini · Semantic Kernel")
    d.node("tables", "Table Storage", 580, 380, "azure-table-storage", "12 tablas Synthetic*")
    d.node("blob", "Blob Storage", 800, 380, "azure-blob-storage", "propuestas · aprobaciones")
    d.node("sql", "Azure SQL", 1020, 380, "azure-sql-database", "auditoría (10 tablas)")
    d.node("appi", "Application Insights", 1250, 380, "azure-application-insights", "+ Log Analytics")
    d.group("Stack operativo · main.bicep (brazilsouth)", ["entra", "func", "sb", "aoai", "tables", "blob", "sql", "appi"], "azure", icon="azure")

    d.node("scripts", "Scripts operativos", 130, 480, "python", "seed · rescore")
    d.node("twin", "Digital Twin", 130, 660, "python", "generador sintético")
    d.group("Repositorio / estación local", ["twin", "scripts"], "external")

    d.node("job", "Job de entrenamiento", 370, 660, "azure-machine-learning", "train_azure.py")
    d.node("reg", "Registro + MLflow", 600, 660, "mlflow", "SAT_FUMC_LightGBM_Model v2")
    d.node("ep", "Online endpoint", 830, 660, "azure-machine-learning", "sat-fumc-endpoint / blue")
    d.group("Azure Machine Learning (workspace FUMC_Analytics_Core)", ["job", "reg", "ep"], "ml", icon="azure-machine-learning")

    d.link("users", "spa", "HTTPS")
    d.link("spa", "entra", "login")
    d.link("entra", "func")
    d.link("func", "sb", "fan-out", tone="agents")
    d.link("sb", "aoai", tone="agents")
    d.link("func", "tables", "estado / UI", tone="data", label_pos=0.45)
    d.link("func", "blob", tone="data")
    d.link("func", "sql", "auditoría", tone="data", label_pos=0.55)
    d.link("func", "appi", "telemetría", label_pos=0.72)
    d.link("twin", "job", "data asset", tone="ml")
    d.link("job", "reg", tone="ml")
    d.link("reg", "ep", "despliega", tone="ml")
    d.link("ep", "scripts", "puntuación offline", tone="ml", route="vh", label_pos=0.6)
    d.link("scripts", "tables", "ModelProbability", tone="data", label_pos=0.5)
    d.note(40, 760, "La Function App también expone /api/ml/predict como proxy al endpoint (requiere AZURE_ML_ENDPOINT_*, no definido en Bicep). Los agentes leen la probabilidad ya guardada.")
    return d


# 3. Frontend ------------------------------------------------------------------
def frontend() -> Diagram:
    d = Diagram(
        "03_frontend",
        "Arquitectura frontend",
        1500,
        900,
        "SPA vanilla JS servida por la Function App; todas las vistas llaman a la API protegida mediante api() (fetch same-origin)",
    )
    d.node("user", "Usuario", 90, 404, "user", "navegador", w=120)
    views = [
        ("v_dash", "Dashboard", "poc/dashboard · poc/status · poc/alerts · batches"),
        ("v_students", "Estudiantes", "poc/students · poc/followups"),
        ("v_profile", "Perfil 360° (Resumen ejecutivo)", "poc/students/{id} · poc/followups\nbatches · reviews/{id}/approval"),
        ("v_alerts", "Alertas", "poc/alerts · poc/alerts/{id}/status"),
        ("v_follow", "Seguimientos", "poc/followups · poc/followups/{id}/status"),
        ("v_analytics", "Analítica · Facultades · Programas", "poc/dashboard (datos reutilizados)"),
        ("v_reports", "Reportes", "reports/reviews (CSV)"),
        ("v_settings", "Configuración", "poc/status"),
    ]
    for i, (id_, label, sub) in enumerate(views):
        d.node(id_, label, 410, 140 + i * 88, sub=sub, w=330)
    d.group("SPA · static/index.html + dashboard.js + styles.css", [v[0] for v in views], "front", icon="javascript")
    d.node("api", "api()", 750, 450, "javascript", "fetch same-origin\ncookie de sesión", w=150)
    d.node("entra", "Easy Auth", 950, 450, "microsoft-entra-id", "401 → /.auth/login/aad", w=170)
    d.node("func", "Function App", 1260, 160, "azure-functions", "23 rutas · allowlist", w=330)
    endpoints = [
        "GET /api/poc/dashboard · /api/poc/status",
        "GET /api/poc/students · /students/{id}",
        "GET·POST /api/poc/alerts · /followups",
        "POST /api/batches · GET /batches/{id}",
        "POST /api/reviews/{id}/approval",
        "GET /api/reports/reviews",
        "POST /api/poc/state",
    ]
    ids = []
    for i, label in enumerate(endpoints):
        ids.append(f"e{i}")
        d.node(f"e{i}", label, 1260, 290 + i * 70, w=330, kind="pill")
    d.group("Azure Functions · API REST", ["func"] + ids, "azure", icon="azure-functions")
    d.link("user", "v_alerts")
    for view in views:
        d.link(view[0], "api", tone="azure", route="hv")
    d.link("api", "entra", tone="security")
    d.link("entra", "func", "x-ms-client-principal", tone="security", route="vh", label_pos=0.35)
    d.note(
        40,
        850,
        "Gráficos propios en SVG/CSS (tendencia, donut, barras, heatmaps, gauges); sin framework. Tema claro/oscuro en localStorage. Refresco cada 30 s; polling de lotes cada 3 s.\n"
        "CSP script-src 'self'. Al cargar el dashboard sin análisis previos se lanza un lote automático (maybeAutoAnalyze) que consume Azure OpenAI.",
    )
    return d


# 4. Backend -------------------------------------------------------------------
def backend() -> Diagram:
    d = Diagram(
        "04_backend",
        "Arquitectura backend (Azure Functions)",
        1560,
        940,
        "function_app.py: disparadores, controles transversales, módulos de dominio (sat_agents) y servicios",
    )
    d.node("http", "HTTP · 23 rutas", 160, 160, "azure-functions", "API /api/* + SPA estática")
    d.node("sbt", "Service Bus · 4 triggers", 160, 360, "azure-service-bus", "3 workers + agent-results")
    d.node("timer", "Timers", 160, 560, "azure-functions", "cache_warmer 4 min\nbatch_reaper 2 min")
    d.node("durable", "Durable (legado)", 160, 760, "azure-functions", "/api/cases espera eventos\nque nadie emite")
    d.group("Disparadores", ["http", "sbt", "timer", "durable"], "azure")

    d.node("guard", "Controles", 470, 160, sub="_authorize_reviewer · allowlist\n_require_synthetic_mode · 16 KB", w=230)
    d.node("starter", "_ServiceBusBatchStarter", 470, 330, sub="admisión · claim · fan-out", w=230)
    d.node("collect", "collect_agent_result", 470, 680, sub="_record_agent_result\n_build_pending_review", w=230)
    d.group("function_app.py", ["guard", "starter", "collect"], "ops", icon="python")

    mods = [
        ("m_exec", "executive.py", "vista ejecutiva determinista"),
        ("m_pilot", "pilot_limits.py", "contador ETag en Blob"),
        ("m_batch", "batch_flow.py", "SyntheticBatches · AgentResults"),
        ("m_db", "synthetic_database.py", "estudiantes · snapshots · alertas\nseguimientos · dashboard"),
        ("m_contract", "contracts.py · policy.py", "esquemas · saneamiento · umbrales"),
        ("m_agents", "agents.py", "Semantic Kernel · 4 agentes"),
        ("m_reviews", "reviews.py · usage.py", "propuestas · costos"),
        ("m_audit", "audit_sql.py", "dual-write no bloqueante"),
    ]
    for i, (id_, label, sub) in enumerate(mods):
        d.node(id_, label, 820, 140 + i * 94, sub=sub, w=260)
    d.group("sat_agents/", [m[0] for m in mods], "agents", icon="python")

    d.node("s_aml", "Azure ML endpoint", 1230, 130, "azure-machine-learning", "proxy /api/ml/predict")
    d.node("s_tables", "Table Storage", 1440, 330, "azure-table-storage")
    d.node("s_blob", "Blob Storage", 1230, 660, "azure-blob-storage")
    d.node("s_sql", "Azure SQL", 1230, 800, "azure-sql-database", "pyodbc + token Entra")
    d.node("s_search", "Azure AI Search", 1440, 130, "azure-ai-search", "RAG deshabilitado")
    d.node("s_aoai", "Azure OpenAI", 1440, 560, "azure-openai", "token Entra")
    d.group("Servicios", ["s_tables", "s_blob", "s_sql", "s_aml", "s_aoai", "s_search"], "external")

    d.link("http", "guard")
    d.link("guard", "starter", "POST /api/batches")
    d.link("guard", "m_exec", "perfil")
    d.link("starter", "m_pilot", tone="agents")
    d.link("starter", "m_batch", tone="agents")
    d.link("starter", "sbt", "3 mensajes/caso", tone="agents", label_pos=0.5)
    d.link("sbt", "collect", "agent-results", tone="agents", label_pos=0.55)
    d.link("collect", "m_agents", "síntesis", tone="agents")
    d.link("collect", "m_reviews", tone="agents")
    d.link("collect", "m_audit", tone="agents")
    d.link("durable", "collect", "sin raise_event", dashed=True, tone="security", label_pos=0.5)
    d.link("m_pilot", "s_blob", tone="data", route="hv")
    d.link("m_batch", "s_tables", tone="data")
    d.link("m_db", "s_tables", tone="data")
    d.link("m_reviews", "s_blob", tone="data")
    d.link("m_agents", "s_aoai", tone="agents")
    d.link("m_audit", "s_sql", tone="data")
    d.note(40, 905, "Los timers refrescan cachés (cache_warmer) y cierran lotes de más de 20 min (batch_reaper). agents.py solo consulta AI Search si ACADEMIC_RAG_ENABLED=true (false en Bicep).")
    return d


# 5. Base de datos -------------------------------------------------------------
def base_datos() -> Diagram:
    d = Diagram(
        "05_base_datos",
        "Arquitectura de datos persistentes",
        1500,
        900,
        "Azure SQL (auditoría, 7 FK) · Azure Table Storage (operación de la UI) · Blob (propuestas y control)",
    )
    d.node("mr", "ModelRelease", 150, 190, sub="PK (ModelName, ModelVersion)\nthreshold · MetricsJson", w=230)
    d.node("ss", "StudentSnapshot", 150, 400, sub="PK SnapshotId\nUQ modo+estudiante+periodo+corte", w=230)
    d.node("ot", "OutcomeTarget", 150, 610, sub="PK/FK SnapshotId\nmadurez del target", w=230)
    d.node("pr", "Prediction", 450, 300, sub="PK PredictionId\nFK Snapshot · FK ModelRelease\nRiskLevel · InferenceSource", w=240)
    d.node("ae", "AgentExecution", 450, 520, sub="FK Prediction\nUQ (Prediction, Agent, Attempt)", w=240)
    d.node("rp", "ReviewProposal", 750, 300, sub="PK ReviewId · FK Prediction\npending/approved/edited/rejected", w=240)
    d.node("hd", "HumanDecision", 750, 480, sub="FK ReviewProposal (UQ)", w=240)
    d.node("iv", "Intervention", 750, 640, sub="FK HumanDecision (UQ)\nopen/in_progress/completed", w=240)
    d.node("au", "AuditEvent", 450, 720, sub="bigint IDENTITY · MetadataJson", w=240)
    d.node("sv", "SchemaVersion", 150, 790, sub="versión aplicada", w=230)
    d.group("Azure SQL · SATFUMCOperational (serverless GP_S_Gen5_1)", ["mr", "ss", "ot", "pr", "ae", "rp", "hd", "iv", "au", "sv"], "data", icon="azure-sql-database")
    d.link("ss", "pr", "1:N", tone="data")
    d.link("mr", "pr", "1:N", tone="data")
    d.link("pr", "ae", "1:N", tone="data")
    d.link("pr", "rp", "1:1", tone="data")
    d.link("rp", "hd", "1:1", tone="data")
    d.link("hd", "iv", "1:1", tone="data")
    d.link("ss", "ot", "1:1", tone="data")

    d.node(
        "tbl",
        "Azure Table Storage",
        1210,
        330,
        "azure-table-storage",
        "SyntheticStudents · SyntheticSnapshots\nSyntheticAcademic · SyntheticFinance\nSyntheticWellbeing · SyntheticTargets\n"
        "SyntheticAlerts · SyntheticFollowups\nSyntheticDashboardTrends · SyntheticControl\nSyntheticBatches · SyntheticAgentResults",
        w=320,
    )
    d.node(
        "blob",
        "Blob · student-case-reviews",
        1210,
        680,
        "azure-blob-storage",
        "reviews/{id}/proposal.json\nreviews/{id}/approval.json (write-once)\npilot/evaluation-counter.json",
        w=320,
    )
    d.group("Azure Storage (fuente de verdad de la UI)", ["tbl", "blob"], "azure", icon="azure-storage-account")
    d.link("blob", "rp", "audit_sql replica", tone="azure", dashed=True, label_pos=0.5)
    return d


# 6. Azure ---------------------------------------------------------------------
def azure() -> Diagram:
    d = Diagram(
        "06_azure",
        "Recursos Azure declarados en código",
        1500,
        900,
        "main.bicep (stack operativo) + infra_fumc_brazil.bicep / YAML (Azure ML). Flechas = rol RBAC de la identidad administrada",
    )
    d.node("mi", "Identidad administrada", 660, 430, "azure-managed-identity", "SystemAssigned de la Function App")
    d.node("func", "Function App", 660, 210, "azure-functions", "Flex Consumption FC1\n1 instancia · 2 GB")
    d.node("entra", "Easy Auth", 420, 210, "microsoft-entra-id", "authsettingsV2")
    d.node("kv", "Key Vault", 420, 430, "azure-key-vault", "entra-client-secret")
    d.node("st", "Storage Account", 420, 650, "azure-storage-account", "Standard_LRS · sin shared key")
    d.node("sb", "Service Bus", 660, 650, "azure-service-bus", "Standard · 4 colas")
    d.node("aoai", "Azure OpenAI", 900, 650, "azure-openai", "S0 · gpt-5-mini GlobalStandard 50")
    d.node("sql", "Azure SQL", 900, 430, "azure-sql-database", "GP_S_Gen5_1 · auto-pause 60 min")
    d.node("appi", "Application Insights", 900, 210, "azure-application-insights")
    d.node("law", "Log Analytics", 1110, 210, "azure-log-analytics", "30 días · 1 GB/día")
    d.group("Resource group · main.bicep (brazilsouth)", ["mi", "func", "entra", "kv", "st", "sb", "aoai", "sql", "appi", "law"], "azure", icon="azure-resource-group")

    d.link("func", "mi")
    d.link("mi", "kv", "Secrets User", tone="security")
    d.link("mi", "st", "Blob Owner · Queue/Table\nContributor", tone="security", label_pos=0.55)
    d.link("mi", "sb", "Data Sender/Receiver", tone="security")
    d.link("mi", "aoai", "OpenAI User", tone="security")
    d.link("mi", "sql", "token*", tone="security", dashed=True)
    d.link("entra", "func")
    d.link("func", "appi")
    d.link("appi", "law")

    d.node("ws", "Workspace AML", 1320, 400, "azure-machine-learning", "FUMC_Analytics_Core")
    d.node("ep", "Online endpoint", 1320, 600, "azure-machine-learning", "sat-fumc-endpoint · blue\nStandard_DS2_v2 × 1 · auth key")
    d.node("job", "Command job", 1320, 790, "azure-machine-learning", "serverless Standard_DS3_v2")
    d.group("Azure Machine Learning", ["ws", "ep", "job"], "ml", icon="azure-machine-learning")
    d.link("func", "ep", "AZURE_ML_ENDPOINT_KEY\n(no definido en Bicep)", tone="ml", dashed=True, label_pos=0.62)

    d.node("budget", "Presupuesto", 160, 780, sub="FUMC-SAT-POC-monthly-100USD\nalertas 50/80/100 %", w=230)
    d.group("Suscripción · budget.bicep", ["budget"], "ops")
    d.note(40, 862, "* Usuario de base de datos para la identidad creado manualmente (no está en Bicep).\nSin VNet ni private endpoints: recursos con acceso público y TLS 1.2. AI Search no se aprovisiona (RAG deshabilitado).")
    return d


# 7. Pipeline ML ---------------------------------------------------------------
def pipeline_ml() -> Diagram:
    d = Diagram(
        "07_pipeline_ml",
        "Pipeline de Machine Learning",
        1500,
        720,
        "Camino operativo (Azure ML) y caminos locales/experimentales",
    )
    d.node("cfg", "configs/synthetic_data.json", 140, 200, sub="v2.1.0 · seed 42", w=200)
    d.node("gen", "Digital Twin", 140, 390, "python", "generate_digital_twin.py")
    d.node("parquet", "Parquet + manifest", 140, 580, sub="SHA-256 por archivo", w=200)
    d.group("Datos sintéticos", ["cfg", "gen", "parquet"], "data")

    d.node("asset", "Data asset", 440, 580, "azure-machine-learning", "sat-fumc-synthetic-100k:1")
    d.node("job", "Command job", 440, 390, "azure-machine-learning", "train_azure.py\nserverless DS3_v2")
    d.node("mlflow", "MLflow", 700, 390, "mlflow", "métricas · params · modelo")
    d.node("reg", "Model registry", 700, 200, "azure-machine-learning", "SAT_FUMC_LightGBM_Model v2")
    d.node("ep", "Online endpoint", 960, 200, "azure-machine-learning", "sat-fumc-endpoint / blue")
    d.node("eval", "evaluate_model.py", 960, 390, "python", "evaluación independiente")
    d.group("Camino operativo · Azure Machine Learning", ["asset", "job", "mlflow", "reg", "ep", "eval"], "ml", icon="azure-machine-learning")

    d.node("local", "train_pipeline.py", 1290, 200, "python", "XGBoost vs LightGBM\nmlruns/ local")
    d.node("recal", "recalibration_*.py", 1290, 390, "python", "420 corridas 5k–100k\nno productivo")
    d.node("lmodels", "models/*.joblib", 1290, 580, sub="artefactos locales", w=200)
    d.group("Local / experimental", ["local", "recal", "lmodels"], "external")

    d.link("cfg", "gen")
    d.link("gen", "parquet")
    d.link("parquet", "asset", "upload", tone="ml")
    d.link("asset", "job", tone="ml")
    d.link("job", "mlflow", "log", tone="ml")
    d.link("mlflow", "reg", "si elegible +\n--register_model", tone="ml")
    d.link("reg", "ep", "deployment.yaml", tone="ml")
    d.link("reg", "eval", tone="ml", dashed=True)
    d.link("recal", "lmodels", "")
    d.note(
        40,
        690,
        "Regla de promoción: recall ≥ 0,80 y tasa de alertas ≤ máx. en validación. Ninguna corrida registrada la cumple (promotion_eligible = 0); v2 está desplegado como POC.",
    )
    return d


# 8. Multiagentes --------------------------------------------------------------
def multiagentes() -> Diagram:
    d = Diagram(
        "08_multiagentes",
        "Flujo multiagente (lote)",
        1500,
        880,
        "POST /api/batches → Service Bus → 3 agentes especializados → sintetizador → revisión humana",
    )
    d.node("ui", "SPA", 110, 200, "javascript", "Analizar casos /\nGenerar plan")
    d.node("adm", "Admisión", 330, 200, "azure-functions", "allowlist · POC activa\n≤ 20 casos · mayor riesgo")
    d.node("pilot", "Límites piloto", 330, 400, "azure-blob-storage", "10.000 evaluaciones\n1 lote concurrente")
    d.node("reg", "batch_flow", 560, 200, "azure-table-storage", "SyntheticBatches")
    d.group("Orquestación (sin Durable)", ["adm", "pilot", "reg"], "azure")

    d.node("q1", "socioeconomic-analysis", 820, 130, "azure-service-bus", w=190)
    d.node("q2", "academic-analysis", 820, 300, "azure-service-bus", w=190)
    d.node("q3", "wellbeing-analysis", 820, 470, "azure-service-bus", w=190)
    d.group("Service Bus", ["q1", "q2", "q3"], "azure", icon="azure-service-bus")

    d.node("a1", "AnalistaSocioeconomico", 1080, 130, "azure-openai", "≤3 hallazgos", w=200)
    d.node("a2", "EvaluadorAcademico", 1080, 300, "azure-openai", "RAG AI Search: off", w=200)
    d.node("a3", "AnalistaBienestar", 1080, 470, "azure-openai", "≤3 hallazgos", w=200)
    d.group("Agentes · SK + gpt-5-mini", ["a1", "a2", "a3"], "agents", icon="azure-openai")

    d.node("res", "agent-results", 1350, 300, "azure-service-bus", "collect_agent_result", w=180)
    d.node("synth", "Sintetizador", 1350, 560, "azure-openai", "diagnóstico único ≤150 pal.\nacciones permitidas", w=200)
    d.node("prop", "Propuesta", 1080, 700, "azure-blob-storage", "pending_approval")
    d.node("sql", "Auditoría", 1350, 790, "azure-sql-database", "Prediction · AgentExecution\nReviewProposal")
    d.node("exec", "Vista ejecutiva", 820, 700, "python", "executive.py (determinista)")
    d.node("human", "Revisor", 560, 700, "user", "Validar plan / Descartar")
    d.node("fu", "Seguimiento", 330, 700, "azure-table-storage", "SyntheticFollowups\n+ HumanDecision en SQL")

    d.link("ui", "adm", "POST")
    d.link("adm", "pilot")
    d.link("adm", "reg")
    for q in ("q1", "q2", "q3"):
        d.link("reg", q, tone="agents")
    for q, a in (("q1", "a1"), ("q2", "a2"), ("q3", "a3")):
        d.link(q, a, tone="agents")
        d.link(a, "res", tone="agents")
    d.link("res", "synth", "3/3 recibidos", tone="agents")
    d.link("synth", "prop", tone="data")
    d.link("synth", "sql", tone="data")
    d.link("prop", "exec")
    d.link("exec", "human")
    d.link("human", "fu", "aprobado", tone="security")
    d.note(40, 850, "Reintentos: Service Bus maxDelivery 5, lock 5 min, dead-letter; batch_reaper marca como fallido un lote con más de 20 min. OpenAI: timeout 45 s, 1 reintento.")
    return d


# 9. Flujo de entrenamiento ----------------------------------------------------
def entrenamiento() -> Diagram:
    d = Diagram(
        "09_flujo_entrenamiento",
        "Flujo de entrenamiento (train_azure.py)",
        1500,
        620,
        "Pasos ejecutados en el job de Azure ML; el pipeline local reutiliza los mismos módulos de src/",
    )
    steps = [
        ("s1", "AgentIngestion", "lee parquet\nversiona dataset", 130, 200),
        ("s2", "AgentQuality", "13 reglas\nquita fugas", 470, 200),
        ("s3", "Join target maduro", "target_observado\nhorizonte T+2", 810, 200),
        ("s4", "engineer_features", "52 crudas → 59\n(7 derivadas)", 1150, 200),
        ("s5", "Split temporal", "fit · validación 2024-2\ntest 2025-1/2 (20 %)", 1150, 430),
        ("s6", "6 candidatos", "3 sets LightGBM ×\nsigmoid / isotonic", 810, 430),
        ("s7", "Umbral en validación", "recall ≥ 0,80\nalertas ≤ 50 %", 470, 430),
        ("s8", "Evaluación test", "recall · precisión · AUC\nBrier · fairness · SHAP", 130, 430),
    ]
    for i, (id_, label, sub, x, y) in enumerate(steps):
        d.node(id_, label, x, y, "python" if i < 4 else "azure-machine-learning", sub, w=200)
    d.group("src/agents · src/ml", ["s1", "s2", "s3", "s4"], "data", icon="python")
    d.group("azure/train_azure.py", ["s5", "s6", "s7", "s8"], "ml", icon="azure-machine-learning")
    ids = [s[0] for s in steps]
    for a, b in zip(ids, ids[1:]):
        d.link(a, b, tone="ml")
    d.note(40, 590, "No hay reajuste con fit + validación: se conserva el modelo calibrado sobre fit. Registro solo si es elegible y se pasa --register_model.")
    return d


# 10. Flujo de inferencia ------------------------------------------------------
def inferencia() -> Diagram:
    d = Diagram(
        "10_flujo_inferencia",
        "Flujo de inferencia",
        1500,
        790,
        "La probabilidad se calcula offline por lotes y se guarda en Tables; los agentes la leen, no la recalculan",
    )
    d.node("snap", "Snapshots 2025-2", 140, 200, "python", "dataset del generador")
    d.node("seed", "seed / rescore /\nreplace_legacy_cohort", 380, 200, "python", "scripts/")
    d.node("client", "endpoint_scoring.py", 620, 200, "python", "lotes de 200 · 4 reintentos")
    d.group("Puntuación offline (estación de operación)", ["snap", "seed", "client"], "external")

    d.node("ep", "score.py", 900, 200, "azure-machine-learning", "engineer_features\npredict_proba")
    d.node("model", "LightGBM calibrado", 1150, 200, "azure-machine-learning", "SAT_FUMC_LightGBM_Model v2")
    d.group("sat-fumc-endpoint / blue", ["ep", "model"], "ml", icon="azure-machine-learning")

    d.node("tables", "SyntheticSnapshots", 620, 430, "azure-table-storage", "ModelProbability · RiskLevel\nModelVersion · FeaturesJson")
    d.node("func", "Function App", 900, 430, "azure-functions", "API · agentes · vista ejecutiva")
    d.node("ui", "SPA", 1150, 430, "javascript", "semáforo · prioridad")
    d.group("Plataforma", ["tables", "func", "ui"], "azure")

    d.node("local", "run_multiagent_system.py", 380, 640, "python", "joblib local · umbral 0,35", w=180)
    d.node("pq", "predicciones parquet/csv", 700, 640, sub="+ dashboard_resumen.html", w=220)
    d.group("Inferencia local (legado)", ["local", "pq"], "external")

    d.link("snap", "seed")
    d.link("seed", "client")
    d.link("client", "ep", "POST /score", tone="ml")
    d.link("ep", "model", tone="ml")
    d.link("client", "tables", "classify_risk 0,30/0,60", tone="data")
    d.link("tables", "func", tone="data")
    d.link("func", "ui")
    d.link("func", "ep", "/api/ml/predict", tone="ml", dashed=True)
    d.link("local", "pq")
    d.note(
        40,
        765,
        "Dos esquemas de banda: endpoint y pipeline local 0,25/0,50/0,75 (Crítico ≥ 0,75); plataforma 0,30/0,60 con indicador crítico ≥ 0,80. La plataforma ignora nivel_riesgo del endpoint.",
    )
    return d


# 11. Flujo de datos -----------------------------------------------------------
def flujo_datos() -> Diagram:
    d = Diagram(
        "11_flujo_datos",
        "Flujo de datos extremo a extremo",
        1500,
        760,
        "Desde la configuración del generador hasta la decisión auditada",
    )
    chain = [
        ("c1", "Configuración", None, "synthetic_data.json"),
        ("c2", "Digital Twin", "python", "parquet + manifest"),
        ("c3", "Data asset AML", "azure-machine-learning", "uri_folder"),
        ("c4", "Modelo v2", "mlflow", "registro"),
        ("c5", "Endpoint", "azure-machine-learning", "puntuación"),
        ("c6", "Table Storage", "azure-table-storage", "snapshots puntuados"),
    ]
    for i, (id_, label, icon, sub) in enumerate(chain):
        d.node(id_, label, 120 + i * 250, 200, icon, sub, w=170)
    lower = [
        ("d1", "API / SPA", "azure-functions", "consulta y filtros", 1370),
        ("d2", "Agentes", "azure-openai", "contexto mínimo\n(sin case_id)", 1120),
        ("d3", "Blob", "azure-blob-storage", "proposal.json", 870),
        ("d4", "Revisor", "user", "valida o descarta", 620),
        ("d6", "Seguimientos", "azure-table-storage", "intervención", 370),
    ]
    for id_, label, icon, sub, x in lower:
        d.node(id_, label, x, 430, icon, sub, w=170)
    d.node("d5", "Azure SQL", 745, 640, "azure-sql-database", "auditoría", w=170)
    ids = [c[0] for c in chain]
    for a, b in zip(ids, ids[1:]):
        d.link(a, b, tone="data")
    d.link("c6", "d1", tone="data")
    d.link("d1", "d2", tone="data")
    d.link("d2", "d3", tone="data")
    d.link("d3", "d4", tone="data")
    d.link("d4", "d6", "si aprueba", tone="data")
    d.link("d3", "d5", "propuesta", tone="data", dashed=True)
    d.link("d4", "d5", "decisión", tone="data", dashed=True)
    d.note(
        40,
        738,
        "Retroalimentación: /api/model/feedback escribe data/feedback/model_feedback.jsonl local (no persistente en Flex Consumption) y no alimenta el reentrenamiento.",
    )
    return d


# 12. CI/CD --------------------------------------------------------------------
def cicd() -> Diagram:
    d = Diagram(
        "12_cicd",
        "Integración y despliegue",
        1500,
        640,
        "CI automatizada solo para pruebas; el despliegue es manual",
    )
    d.node("dev", "Desarrollador", 120, 220, "user", "VS Code")
    d.node("git", "Repositorio", 340, 220, "github", "push / pull_request")
    d.node("gha", "GitHub Actions", 580, 220, "github-actions", "ci.yml · ubuntu-latest")
    d.node("py", "Python 3.11", 820, 220, "python", "pip install -r requirements.txt")
    d.node("pytest", "pytest -q", 1060, 220, sub="sin despliegue · sin lint Bicep", w=200)
    d.group("CI automática", ["git", "gha", "py", "pytest"], "ops", icon="github-actions")

    d.node("bicep", "deploy.ps1", 340, 470, "azure-resource-group", "az deployment group create\nmain.bicep")
    d.node("func", "func azure functionapp\npublish", 640, 470, "azure-functions", "staging con src/ incluido")
    d.node("aml", "az ml job / endpoint", 940, 470, "azure-machine-learning", "job.yaml · deployment.yaml")
    d.node("azure", "Azure", 1240, 470, "azure", "brazilsouth")
    d.group("Despliegue manual", ["bicep", "func", "aml"], "external")
    d.link("dev", "git", "commit")
    d.link("git", "gha", "trigger")
    d.link("gha", "py")
    d.link("py", "pytest")
    d.link("dev", "bicep", route="vh")
    d.link("bicep", "func")
    d.link("func", "aml")
    d.link("aml", "azure", tone="azure")
    d.note(
        40,
        600,
        "Riesgos: el requirements.txt raíz no incluye azure-functions ni semantic-kernel (tests que importan function_app pueden fallar en CI); deploySubpath de VS Code y deploy-updated.zip omiten src/.",
    )
    return d


# 13. Seguridad ----------------------------------------------------------------
def seguridad() -> Diagram:
    d = Diagram(
        "13_seguridad",
        "Controles de seguridad y gobierno",
        1500,
        830,
        "Cadena de control de cada solicitud y acceso sin secretos a los servicios",
    )
    chain = [
        ("u", "Usuario", "user", "navegador"),
        ("ea", "Easy Auth", "microsoft-entra-id", "requireAuthentication\nRedirectToLoginPage"),
        ("al", "Allowlist", "microsoft-entra-id", "oid ∈ CASE_REVIEWER_\nALLOWED_PRINCIPAL_IDS"),
        ("sm", "Modo sintético", "azure-functions", "DATA_MODE=synthetic\nIDs syn- / ST-SYN-"),
        ("pl", "Límites", "azure-blob-storage", "16 KB · 20 casos/lote\n10.000 evaluaciones"),
        ("hitl", "Humano en el ciclo", "user", "approval write-once\nautomated_decision=false"),
    ]
    for i, (id_, label, icon, sub) in enumerate(chain):
        d.node(id_, label, 120 + i * 250, 200, icon, sub, w=190)
    ids = [c[0] for c in chain]
    for a, b in zip(ids, ids[1:]):
        d.link(a, b, tone="security")
    d.group("Cadena de control por solicitud", ids[1:], "security")

    d.node("mi", "Identidad administrada", 760, 450, "azure-managed-identity", "DefaultAzureCredential", w=200)
    services = [
        ("kv", "Key Vault", "azure-key-vault", "secreto de Entra"),
        ("aoai", "Azure OpenAI", "azure-openai", "disableLocalAuth"),
        ("sb", "Service Bus", "azure-service-bus", "disableLocalAuth"),
        ("st", "Storage", "azure-storage-account", "sin shared key"),
        ("sql", "Azure SQL", "azure-sql-database", "token Entra*"),
    ]
    for i, (id_, label, icon, sub) in enumerate(services):
        d.node(id_, label, 260 + i * 250, 660, icon, sub, w=180)
        d.link("mi", id_, tone="security")
    d.node("aml", "AML endpoint", 1350, 450, "azure-machine-learning", "excepción: clave\nAZURE_ML_ENDPOINT_KEY", w=200)
    d.group("Acceso a servicios", ["mi", "aml"] + [s[0] for s in services], "azure")
    d.note(
        40,
        785,
        "* Entra-only solo si se parametriza sqlEntraAdmin*; Bicep siempre exige contraseña de administrador SQL.\n"
        "Minimización: contratos con campos permitidos, sin case_id hacia el LLM; _public_review oculta IDs de revisor y prompts. Cabeceras CSP, X-Frame-Options DENY, nosniff.",
    )
    return d


# 14. E2E ----------------------------------------------------------------------
def e2e() -> Diagram:
    d = Diagram(
        "14_arquitectura_e2e",
        "Arquitectura completa extremo a extremo",
        1500,
        790,
        "De los datos sintéticos al plan de intervención validado por una persona",
    )
    d.node("cfg", "Generador", 120, 200, "python", "Digital Twin v2.1.0")
    d.node("asset", "Data asset", 120, 430, "azure-machine-learning", "100k")
    d.node("job", "Entrenamiento", 120, 660, "azure-machine-learning", "LightGBM calibrado")
    d.node("reg", "Registro", 330, 660, "mlflow", "v2")
    d.node("ep", "Endpoint", 330, 430, "azure-machine-learning", "blue · DS2_v2")
    d.node("scripts", "Puntuación offline", 330, 200, "python", "seed / rescore")
    d.group("Datos y ML", ["cfg", "asset", "job", "reg", "ep", "scripts"], "ml", icon="azure-machine-learning")

    d.node("tables", "Table Storage", 640, 200, "azure-table-storage", "snapshots · alertas\nseguimientos · lotes")
    d.node("func", "Function App", 640, 430, "azure-functions", "API · admisión · colector")
    d.node("appi", "App Insights", 640, 660, "azure-application-insights", "+ Log Analytics")
    d.node("sb", "Service Bus", 880, 430, "azure-service-bus", "4 colas")
    d.node("agents", "3 agentes + sintetizador", 1110, 430, "azure-openai", "Semantic Kernel · gpt-5-mini")
    d.node("blob", "Blob", 880, 200, "azure-blob-storage", "propuestas")
    d.node("sql", "Azure SQL", 1110, 200, "azure-sql-database", "auditoría")
    d.node("entra", "Entra ID", 1110, 660, "microsoft-entra-id", "Easy Auth + allowlist")
    d.group("Plataforma operativa (main.bicep)", ["tables", "func", "entra", "sb", "agents", "blob", "sql", "appi"], "azure", icon="azure")

    d.node("ui", "SPA", 1360, 430, "javascript", "Resumen ejecutivo")
    d.node("user", "Equipo de permanencia", 1360, 660, "users", "valida y asigna")
    d.group("Usuarios", ["ui", "user"], "front")

    d.link("cfg", "asset", tone="ml")
    d.link("asset", "job", tone="ml")
    d.link("job", "reg", tone="ml")
    d.link("reg", "ep", tone="ml")
    d.link("ep", "scripts", tone="ml")
    d.link("scripts", "tables", "probabilidad", tone="data")
    d.link("tables", "func", tone="data")
    d.link("func", "sb", tone="agents")
    d.link("sb", "agents", tone="agents")
    d.link("agents", "blob", "diagnóstico", tone="data", label_pos=0.4)
    d.link("blob", "sql", "réplica", tone="data", dashed=True)
    d.link("func", "blob", tone="data")
    d.link("func", "appi")
    d.link("user", "ui", both=True)
    d.link("ui", "entra", "HTTPS + login", tone="security", label_pos=0.45)
    d.link("entra", "func", tone="security")
    return d


DIAGRAMS = [
    estructura,
    general,
    frontend,
    backend,
    base_datos,
    azure,
    pipeline_ml,
    multiagentes,
    entrenamiento,
    inferencia,
    flujo_datos,
    cicd,
    seguridad,
    e2e,
]


if __name__ == "__main__":
    only = set(sys.argv[1:])
    for factory in DIAGRAMS:
        diagram = factory()
        if only and diagram.name not in only:
            continue
        path = render(diagram)
        print(f"{diagram.name}: {path.name}")
