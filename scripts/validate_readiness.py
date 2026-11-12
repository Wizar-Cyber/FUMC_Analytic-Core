"""Verificador del checklist de producción (bloques 4 a 9).

Cada ítem del checklist se asocia con un chequeo automático o se marca MANUAL.
Estados:
  PASS     evidencia obtenida en esta ejecución
  FAIL     el chequeo se ejecutó y no se cumple
  PENDING  requiere entorno Azure (variables de entorno) que no está configurado
  MANUAL   requiere evidencia humana (portal, revisión de documento)

Uso:
  python scripts/validate_readiness.py                 # solo chequeos locales
  SAT_BASE_URL=https://<app>.azurewebsites.net python scripts/validate_readiness.py
  ... --allow-writes   permite chequeos que crean datos de prueba
Variables remotas: SAT_BASE_URL, SAT_BEARER_TOKEN, SAT_SQL_SERVER, SAT_SQL_DATABASE,
SAT_STORAGE_CONNECTION, SAT_STORAGE_CONTAINER, SAT_PREDICT_PAYLOAD (ruta a JSON).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "azure" / "agent_platform"))
sys.path.insert(0, str(ROOT))

PASS, FAIL, PENDING, MANUAL = "PASS", "FAIL", "PENDING", "MANUAL"


@dataclass
class Result:
    status: str
    evidence: str


class Context:
    def __init__(self, allow_writes: bool) -> None:
        self.allow_writes = allow_writes
        self.base_url = os.environ.get("SAT_BASE_URL", "").rstrip("/")
        self.token = os.environ.get("SAT_BEARER_TOKEN", "")
        self._pytest_cache: dict[str, Result] = {}

    def pytest(self, target: str) -> Result:
        if target not in self._pytest_cache:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", target],
                cwd=ROOT, capture_output=True, text=True,
            )
            lines = [line for line in proc.stdout.splitlines() if line.strip()]
            summary = lines[-1] if lines else "sin salida"
            status = PASS if proc.returncode == 0 else FAIL
            self._pytest_cache[target] = Result(status, f"pytest {target}: {summary}")
        return self._pytest_cache[target]

    def http(self, method: str, path: str, body: dict | None = None, auth: bool = True):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base_url + path, data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if auth and self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode("utf-8", "replace")


def _need_remote(ctx: Context) -> Result | None:
    if not ctx.base_url:
        return Result(PENDING, "define SAT_BASE_URL")
    return None


def _json_get(ctx: Context, path: str):
    status, text = ctx.http("GET", path)
    try:
        return status, json.loads(text)
    except ValueError:
        return status, None


# ---------- chequeos locales ----------

def local_tests(target: str):
    return lambda ctx: ctx.pytest(target)


def sql_schema_tables(ctx: Context) -> Result:
    sql = (ROOT / "azure/agent_platform/infra/sql_schema.sql").read_text(encoding="utf-8")
    tables = re.findall(r"CREATE TABLE dbo\.(\w+)", sql)
    indexes = len(re.findall(r"CREATE (?:UNIQUE )?INDEX", sql))
    fks = len(re.findall(r"FOREIGN KEY", sql))
    ok = len(tables) == 9 and indexes > 0 and fks > 0
    return Result(PASS if ok else FAIL, f"{len(tables)} tablas, {indexes} índices, {fks} FK en sql_schema.sql")


def sql_repository_not_fake_by_default(ctx: Context) -> Result:
    source = (ROOT / "src/persistence/sql_repository.py").read_text(encoding="utf-8")
    has_fake_default = bool(re.search(r"connection or FakeConnection\(\)", source))
    has_driver = bool(re.search(r"pyodbc|pymssql", source))
    has_reads = bool(re.search(r"def (get|list|fetch|read)_", source))
    problems = []
    if has_fake_default:
        problems.append("usa FakeConnection por defecto (escrituras se descartan en silencio)")
    if not has_driver:
        problems.append("no hay driver real (pyodbc/pymssql)")
    if not has_reads:
        problems.append("no hay operaciones de lectura (solo record_*)")
    return Result(FAIL if problems else PASS, "; ".join(problems) or "repositorio con conexión real y lectura")


def synthetic_data_separation(ctx: Context) -> Result:
    from sat_agents import synthetic_database as db

    rows = db._generate_entities()
    leaked = any("TargetDesercion" in row for row in rows[db.TABLE_SNAPSHOTS])
    sql = (ROOT / "azure/agent_platform/infra/sql_schema.sql").read_text(encoding="utf-8")
    marked = "DataMode" in sql and "'synthetic'" in sql
    ok = not leaked and marked and db.TABLE_TARGETS != db.TABLE_SNAPSHOTS
    return Result(PASS if ok else FAIL, f"target fuera de snapshots={not leaked}; DataMode synthetic en SQL={marked}")


def snapshot_keeps_period_and_cut(ctx: Context) -> Result:
    sql = (ROOT / "azure/agent_platform/infra/sql_schema.sql").read_text(encoding="utf-8")
    block = sql.split("CREATE TABLE dbo.StudentSnapshot", 1)[1].split(");", 1)[0]
    needed = ("PseudonymizedStudentId", "AcademicPeriod", "PredictionCut", "ObservedAt")
    missing = [column for column in needed if column not in block]
    return Result(PASS if not missing else FAIL, f"faltan columnas: {missing}" if missing else "StudentSnapshot conserva estudiante, periodo, corte y fecha")


def cohort_size(ctx: Context) -> Result:
    from sat_agents import synthetic_database as db

    ok = db.DEFAULT_SYNTHETIC_STUDENT_COUNT == 20000 and db.MAX_SYNTHETIC_STUDENT_COUNT == 100000
    return Result(PASS if ok else FAIL, f"default={db.DEFAULT_SYNTHETIC_STUDENT_COUNT}, max={db.MAX_SYNTHETIC_STUDENT_COUNT}")


def recall_gate_default(ctx: Context) -> Result:
    import inspect

    from src.ml.model_selection import select_recall_threshold

    default = inspect.signature(select_recall_threshold).parameters["minimum_recall"].default
    return Result(PASS if default == 0.80 else FAIL, f"minimum_recall por defecto={default}")


def mlflow_logging_declared(ctx: Context) -> Result:
    source = (ROOT / "src/ml/train_pipeline.py").read_text(encoding="utf-8")
    ok = "mlflow.log_metrics" in source and "mlflow.set_experiment" in source
    uri_local = "MLRUNS_DIR" in source and "set_tracking_uri(str(MLRUNS_DIR))" in source
    note = "tracking local (carpeta mlruns), no un workspace AML" if uri_local else "tracking remoto"
    return Result(PASS if ok else FAIL, f"registro de métricas declarado; {note}")


def eval_metrics_reported(ctx: Context) -> Result:
    source = (ROOT / "src/ml/train_pipeline.py").read_text(encoding="utf-8")
    keys = ('"recall"', '"precision"', '"f1"', '"auc_roc"', '"auc_pr"', '"brier_score"')
    missing = [key for key in keys if key not in source]
    return Result(PASS if not missing else FAIL, f"métricas ausentes en train_pipeline.py: {missing}" if missing else "métricas calculadas en el código de entrenamiento (no es una evaluación independiente)")


def no_mock_in_frontend(ctx: Context) -> Result:
    hits = []
    for name in ("dashboard.js", "index.html"):
        text = (ROOT / "azure/agent_platform/static" / name).read_text(encoding="utf-8")
        hits += [f"{name}:{m.group(0)}" for m in re.finditer(r"(?i)\b(mock|lorem ipsum|placeholder data)\b", text)]
    return Result(PASS if not hits else FAIL, f"coincidencias: {hits}" if hits else "sin marcadores mock en la SPA")


# ---------- chequeos remotos ----------

def remote_status(ctx: Context) -> Result:
    if (r := _need_remote(ctx)):
        return r
    status, body = _json_get(ctx, "/api/poc/status")
    return Result(PASS if status == 200 and body is not None else FAIL, f"GET /api/poc/status -> {status}")


def remote_spa(ctx: Context) -> Result:
    if (r := _need_remote(ctx)):
        return r
    status, text = ctx.http("GET", "/", auth=False)
    return Result(PASS if status == 200 and "<html" in text.lower() else FAIL, f"GET / -> {status}")


def remote_auth_enforced(ctx: Context) -> Result:
    if (r := _need_remote(ctx)):
        return r
    status, _ = ctx.http("GET", "/api/reviews", auth=False)
    return Result(PASS if status in (401, 403) else FAIL, f"GET /api/reviews sin token -> {status} (se espera 401/403)")


def remote_dashboard(ctx: Context) -> Result:
    if (r := _need_remote(ctx)):
        return r
    status, body = _json_get(ctx, "/api/poc/dashboard")
    return Result(PASS if status == 200 and body else FAIL, f"GET /api/poc/dashboard -> {status}")


def remote_students(ctx: Context) -> Result:
    if (r := _need_remote(ctx)):
        return r
    status, body = _json_get(ctx, "/api/poc/students?limit=5")
    items = (body or {}).get("items") if isinstance(body, dict) else None
    return Result(PASS if status == 200 and items else FAIL, f"GET /api/poc/students -> {status}, {len(items or [])} filas")


def remote_student_detail(ctx: Context) -> Result:
    if (r := _need_remote(ctx)):
        return r
    _, body = _json_get(ctx, "/api/poc/students?limit=1")
    items = (body or {}).get("items") if isinstance(body, dict) else None
    if not items:
        return Result(FAIL, "no hay estudiantes para consultar")
    student_id = items[0].get("student_id") or items[0].get("StudentId")
    status, detail = _json_get(ctx, f"/api/poc/students/{student_id}")
    return Result(PASS if status == 200 and detail else FAIL, f"GET /api/poc/students/{student_id} -> {status}")


def remote_api_errors(ctx: Context) -> Result:
    if (r := _need_remote(ctx)):
        return r
    status, _ = ctx.http("GET", "/api/poc/students/__no_existe__")
    return Result(PASS if status in (400, 404) else FAIL, f"estudiante inexistente -> {status} (se espera 400/404)")


def remote_alerts(ctx: Context) -> Result:
    if (r := _need_remote(ctx)):
        return r
    status, body = _json_get(ctx, "/api/poc/alerts")
    return Result(PASS if status == 200 and body is not None else FAIL, f"GET /api/poc/alerts -> {status}")


def remote_reviews(ctx: Context) -> Result:
    if (r := _need_remote(ctx)):
        return r
    status, body = _json_get(ctx, "/api/reviews")
    return Result(PASS if status == 200 and body is not None else FAIL, f"GET /api/reviews -> {status}")


def remote_followup_roundtrip(ctx: Context) -> Result:
    if (r := _need_remote(ctx)):
        return r
    if not ctx.allow_writes:
        return Result(PENDING, "requiere --allow-writes (crea un seguimiento de prueba)")
    _, body = _json_get(ctx, "/api/poc/students?limit=1")
    items = (body or {}).get("items") if isinstance(body, dict) else None
    if not items:
        return Result(FAIL, "no hay estudiantes")
    student_id = items[0].get("student_id") or items[0].get("StudentId")
    status, text = ctx.http("POST", "/api/poc/followups", {"student_id": student_id, "action": "academic_advisor_review", "owner": "validacion-automatica"})
    if status != 201:
        return Result(FAIL, f"POST /api/poc/followups -> {status}")
    followup_id = json.loads(text)["followup"].get("followup_id") or json.loads(text)["followup"].get("FollowupId")
    _, listing = _json_get(ctx, "/api/poc/followups?status=all&limit=1000")
    ids = {(row.get("followup_id") or row.get("FollowupId")) for row in (listing or {}).get("items", [])}
    return Result(PASS if followup_id in ids else FAIL, f"seguimiento {followup_id} creado y {'recuperado' if followup_id in ids else 'NO recuperado'}")


def remote_predict(ctx: Context) -> Result:
    if (r := _need_remote(ctx)):
        return r
    payload_path = os.environ.get("SAT_PREDICT_PAYLOAD")
    if not payload_path:
        return Result(PENDING, "define SAT_PREDICT_PAYLOAD (JSON con el contrato del endpoint)")
    status, text = ctx.http("POST", "/api/ml/predict", json.loads(Path(payload_path).read_text(encoding="utf-8")))
    return Result(PASS if status == 200 else FAIL, f"POST /api/ml/predict -> {status}")


def remote_sql(check: str):
    def run(ctx: Context) -> Result:
        server = os.environ.get("SAT_SQL_SERVER")
        database = os.environ.get("SAT_SQL_DATABASE")
        if not server or not database:
            return Result(PENDING, "define SAT_SQL_SERVER y SAT_SQL_DATABASE (autenticación Entra: az login o Managed Identity)")
        try:
            from src.persistence.sql_repository import connect_entra

            connection = connect_entra(server, database, retries=2)
        except ImportError:
            return Result(PENDING, "instala pyodbc, azure-identity y ODBC Driver 18")
        except Exception as error:
            return Result(FAIL, f"conexión rechazada: {type(error).__name__}")
        try:
            cursor = connection.cursor()
            if check == "connect":
                return Result(PASS, f"conexión Entra autorizada a {database}")
            if check == "migrations":
                versions = [row[0] for row in cursor.execute("SELECT Version FROM dbo.SchemaVersion ORDER BY Version")]
                return Result(PASS if versions else FAIL, f"versiones de esquema registradas: {versions}")
            if check == "tables":
                tables = {row[0] for row in cursor.execute("SELECT name FROM sys.tables WHERE schema_id = SCHEMA_ID('dbo')")}
                expected = {"ModelRelease", "StudentSnapshot", "Prediction", "AgentExecution", "ReviewProposal", "HumanDecision", "Intervention", "OutcomeTarget", "AuditEvent", "SchemaVersion"}
                missing = expected - tables
                fks = cursor.execute("SELECT COUNT(*) FROM sys.foreign_keys").fetchone()[0]
                indexes = cursor.execute("SELECT COUNT(*) FROM sys.indexes WHERE name LIKE 'IX[_]%'").fetchone()[0]
                ok = not missing and fks and indexes
                return Result(PASS if ok else FAIL, f"faltan {sorted(missing)}; FK={fks}; índices={indexes}" if not ok else f"{len(expected)} tablas, {fks} FK, {indexes} índices")
        finally:
            connection.close()
        if check == "crud":
            if not ctx.allow_writes:
                return Result(PENDING, "requiere --allow-writes (crea y limpia filas de prueba en SQL)")
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_sql_live_roundtrip.py"],
                cwd=ROOT, capture_output=True, text=True,
            )
            summary = [line for line in proc.stdout.splitlines() if line.strip()][-1:] or ["sin salida"]
            return Result(PASS if proc.returncode == 0 else FAIL, f"roundtrip real en Azure SQL: {summary[0]}")
        return Result(MANUAL, check)
    return run


def sql_crud(ctx: Context) -> Result:
    static = sql_repository_not_fake_by_default(ctx)
    if static.status == FAIL:
        return static
    result = remote_sql("crud")(ctx)
    if result.status == PENDING:
        return Result(PENDING, f"{result.evidence}. Chequeo estático del repositorio: {static.evidence}")
    return result


def sql_tables_in_azure(ctx: Context) -> Result:
    result = remote_sql("tables")(ctx)
    if result.status == PENDING:
        local = sql_schema_tables(ctx)
        return Result(PENDING, f"{result.evidence}. Solo evidencia local del script: {local.evidence}")
    return result


def remote_blob(ctx: Context) -> Result:
    connection_string = os.environ.get("SAT_STORAGE_CONNECTION")
    container = os.environ.get("SAT_STORAGE_CONTAINER")
    if not connection_string or not container:
        return Result(PENDING, "define SAT_STORAGE_CONNECTION y SAT_STORAGE_CONTAINER")
    if not ctx.allow_writes:
        return Result(PENDING, "requiere --allow-writes (sube un blob de prueba)")
    try:
        from azure.storage.blob import BlobServiceClient
    except ImportError:
        return Result(PENDING, "instala azure-storage-blob")
    client = BlobServiceClient.from_connection_string(connection_string).get_blob_client(container, "validacion/readiness.txt")
    client.upload_blob(b"ok", overwrite=True)
    value = client.download_blob().readall()
    client.delete_blob()
    return Result(PASS if value == b"ok" else FAIL, "carga y descarga de blob de prueba")


def manual(note: str):
    return lambda ctx: Result(MANUAL, note)


# ---------- mapa del checklist ----------

CHECKLIST: list[tuple[str, str, object]] = [
    ("4", "Blob Storage permite cargar y recuperar archivos.", remote_blob),
    ("4", "Los contenedores tienen permisos adecuados.", manual("revisar RBAC de la cuenta en el portal (Storage Blob Data *)")),
    ("4", "Azure SQL acepta conexiones autorizadas.", remote_sql("connect")),
    ("4", "Las migraciones de base de datos se ejecutaron correctamente.", remote_sql("migrations")),
    ("4", "Las tablas, índices y relaciones existen.", sql_tables_in_azure),
    ("4", "Las operaciones CRUD funcionan.", sql_crud),
    ("4", "Los datos sintéticos están identificados y separados.", synthetic_data_separation),
    ("4", "Los registros mantienen estudiante, periodo y fecha de corte.", snapshot_keeps_period_and_cut),
    ("4", "Los respaldos y políticas de retención están configurados.", manual("az sql db ltr-policy show / short-term-retention-policy show")),

    ("5", "El pipeline de entrenamiento se ejecuta en el entorno esperado.", manual("ejecutar azure/train_azure.py y adjuntar el job de AML")),
    ("5", "Los datasets se cargan correctamente.", local_tests("tests/test_production_contracts.py")),
    ("5", "La validación de esquemas funciona.", local_tests("tests/test_production_contracts.py")),
    ("5", "La ingeniería de características coincide con entrenamiento e inferencia.", local_tests("tests/test_production_contracts.py")),
    ("5", "Las particiones temporales no presentan fuga de información.", local_tests("tests/test_model_selection.py")),
    ("5", "Los experimentos quedan registrados en MLflow.", mlflow_logging_declared),
    ("5", "Los artefactos del modelo se almacenan correctamente.", manual("verificar registro del modelo en AML (az ml model list)")),
    ("5", "El modelo aprobado tiene versión identificable.", manual("depende de AML Model Registry / dbo.ModelRelease")),
    ("5", "El bloqueo de promoción funciona cuando no se cumplen las métricas.", lambda ctx: ctx.pytest("tests/test_model_selection.py") if recall_gate_default(ctx).status == PASS else recall_gate_default(ctx)),
    ("5", "El endpoint utiliza la versión aprobada del modelo.", remote_predict),

    ("6", "Se ejecutó una evaluación independiente del entrenamiento.", manual("falta script de evaluación sobre el conjunto de prueba reservado")),
    ("6", "Se reporta Recall.", eval_metrics_reported),
    ("6", "Se reporta Precision.", eval_metrics_reported),
    ("6", "Se reporta F1-score.", eval_metrics_reported),
    ("6", "Se reporta AUC-ROC y AUC-PR.", eval_metrics_reported),
    ("6", "Se reporta Brier Score.", eval_metrics_reported),
    ("6", "Se revisó la matriz de confusión.", manual("registrar la matriz en el informe de evaluación")),
    ("6", "Se validó el umbral con datos de validación, no de prueba.", local_tests("tests/test_model_selection.py")),
    ("6", "Se conoce el volumen de falsos positivos.", manual("derivar de la matriz de confusión")),
    ("6", "Se conoce el volumen de falsos negativos.", manual("derivar de la matriz de confusión")),
    ("6", "Se documentó si Recall >= 0,80 fue alcanzado.", manual("documentar el resultado del run independiente")),
    ("6", "Los resultados sintéticos no se presentan como resultados institucionales reales.", manual("revisar artículo y dashboards: etiqueta 'sintético' visible")),

    ("7", "Semantic Kernel se inicializa correctamente.", local_tests("tests/test_distributed_agent_contracts.py")),
    ("7", "El coordinador recibe el contexto del estudiante.", local_tests("tests/test_distributed_agent_contracts.py")),
    ("7", "El agente académico ejecuta su análisis.", local_tests("tests/test_distributed_agent_contracts.py")),
    ("7", "El agente financiero maneja correctamente datos ausentes.", local_tests("tests/test_distributed_agent_contracts.py")),
    ("7", "El agente de bienestar respeta los permisos.", manual("revisar política de permisos del agente de bienestar")),
    ("7", "El agente de síntesis consolida los resultados.", local_tests("tests/test_distributed_agent_contracts.py")),
    ("7", "El agente de recomendaciones genera propuestas verificables.", local_tests("tests/test_distributed_agent_contracts.py")),
    ("7", "GPT-5-mini responde desde el recurso Azure esperado.", manual("ejecutar un caso con --allow-writes y revisar el recurso/despliegue sat-gpt5-mini")),
    ("7", "Las salidas cumplen el esquema JSON definido.", local_tests("tests/test_distributed_agent_contracts.py")),
    ("7", "Los agentes no modifican la predicción de LightGBM.", local_tests("tests/test_distributed_agent_contracts.py")),
    ("7", "Los errores y timeouts se gestionan correctamente.", manual("pruebas de fallo contra Azure OpenAI y Service Bus (DLQ)")),
    ("7", "Cada ejecución tiene trazabilidad.", manual("verificar correlación en Application Insights")),

    ("8", "La SPA carga correctamente desde su URL de despliegue.", remote_spa),
    ("8", "La autenticación funciona desde el navegador.", remote_auth_enforced),
    ("8", "El dashboard consume datos reales del backend.", remote_dashboard),
    ("8", "El listado de estudiantes funciona.", remote_students),
    ("8", "La ficha integral muestra información consistente.", remote_student_detail),
    ("8", "La predicción coincide con la respuesta del endpoint.", manual("comparar probabilidad de la ficha con /api/ml/predict para un mismo caso")),
    ("8", "Los resúmenes generados se visualizan correctamente.", manual("revisión visual en navegador")),
    ("8", "Las recomendaciones se pueden revisar.", remote_reviews),
    ("8", "La aprobación y el rechazo quedan registrados.", manual("POST /api/reviews/{id}/approval y verificar en /api/reports/reviews")),
    ("8", "Las intervenciones se pueden registrar y consultar.", remote_followup_roundtrip),
    ("8", "Los errores de API se muestran adecuadamente.", remote_api_errors),
    ("8", "No quedan mocks presentados como datos reales.", no_mock_in_frontend),

    ("9", "Se genera o carga un registro de estudiante.", cohort_size),
    ("9", "Se procesa y valida su información.", local_tests("tests/test_production_contracts.py")),
    ("9", "Se ejecuta una predicción.", remote_predict),
    ("9", "Se obtiene la probabilidad y clasificación de riesgo.", remote_predict),
    ("9", "Se inicia la orquestación de agentes.", manual("POST /api/cases con --allow-writes")),
    ("9", "Se genera un resumen.", manual("depende del caso end-to-end")),
    ("9", "Se generan recomendaciones.", manual("depende del caso end-to-end")),
    ("9", "Se almacenan los resultados en Azure SQL.", sql_crud),
    ("9", "La API recupera la información almacenada.", remote_student_detail),
    ("9", "La SPA muestra la información correctamente.", manual("revisión visual en navegador")),
    ("9", "Un profesional puede revisar el caso.", remote_reviews),
    ("9", "La intervención queda registrada.", remote_followup_roundtrip),
    ("9", "El seguimiento puede consultarse posteriormente.", remote_followup_roundtrip),
]

BLOCK_TITLES = {
    "4": "Datos y almacenamiento",
    "5": "Pipeline de Machine Learning",
    "6": "Validación predictiva",
    "7": "Red multiagente y GPT-5-mini",
    "8": "API y frontend",
    "9": "Integración end-to-end",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--allow-writes", action="store_true")
    parser.add_argument("--output", default=str(ROOT / "outputs" / "readiness_report.md"))
    args = parser.parse_args()

    ctx = Context(args.allow_writes)
    rows = []
    cache: dict[int, Result] = {}
    for block, text, check in CHECKLIST:
        key = id(check)
        if key not in cache:
            try:
                cache[key] = check(ctx)
            except Exception as error:
                cache[key] = Result(FAIL, f"excepción: {type(error).__name__}: {error}")
        rows.append((block, text, cache[key]))

    lines = [f"# Informe de preparación para producción", "", f"Generado: {datetime.now(timezone.utc).isoformat(timespec='seconds')}", f"Modo remoto: {'sí' if ctx.base_url else 'no (solo chequeos locales)'}", ""]
    totals = {PASS: 0, FAIL: 0, PENDING: 0, MANUAL: 0}
    for block in BLOCK_TITLES:
        block_rows = [row for row in rows if row[0] == block]
        passed = sum(row[2].status == PASS for row in block_rows)
        lines += [f"## {block}. {BLOCK_TITLES[block]} ({passed}/{len(block_rows)})", ""]
        for _, text, result in block_rows:
            totals[result.status] += 1
            mark = "x" if result.status == PASS else " "
            lines.append(f"- [{mark}] {text} **{result.status}** — {result.evidence}")
        lines.append("")
    lines.insert(4, "Resumen: " + ", ".join(f"{name}={count}" for name, count in totals.items()))
    lines.insert(5, "")
    report = "\n".join(lines)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(report, encoding="utf-8")
    print(report)
    return 1 if totals[FAIL] else 0


if __name__ == "__main__":
    raise SystemExit(main())
