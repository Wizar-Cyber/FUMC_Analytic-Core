"""
=============================================================================
SAT-FUMC: Digital Twin — Generador de Datos Sintéticos
=============================================================================
Fundación Universitaria María Cano - Sistema de Alerta Temprana de Deserción

Basado en:
  - diccionario_datos_SAT_desercion_FUMC.xlsx (fuente de verdad)
  - contexto_fundacion_universitaria_maria_cano.md
  - SyntheticDataStrategy.md

Genera:
  - catalogos_maestros.parquet
    - estudiante_periodo_corte.parquet      (volumen configurable)
    - estudiante_asignatura_periodo.parquet (volumen configurable)
    - financiera_estudiante_evento.parquet  (volumen configurable)
    - bienestar_acompanamiento.parquet       (volumen configurable)
    - solicitudes_estudiantiles.parquet     (volumen configurable)
    - target_trazabilidad.parquet           (target separado, con madurez/censura)
  - calendario_academico.parquet
  - perfilamiento_calidad.parquet
=============================================================================
"""
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import uuid
import os
import json
import hashlib
from datetime import date, timedelta, datetime, timezone
from pathlib import Path

CONFIG_PATH = Path(
    os.environ.get(
        "SAT_SYNTHETIC_CONFIG",
        str(Path(__file__).resolve().parents[2] / "configs" / "synthetic_data.json"),
    )
).expanduser()
with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
    CONFIG = json.load(config_file)

GENERATOR_VERSION = str(CONFIG.get("generator_version", "2.0.0"))
N_ESTUDIANTES = int(os.environ.get("SAT_SYNTHETIC_STUDENTS", CONFIG["students"]))
SEED = int(os.environ.get("SAT_SYNTHETIC_SEED", CONFIG["seed"]))
PERIOD_COUNT = int(os.environ.get("SAT_SYNTHETIC_PERIODS", CONFIG["period_count"]))
COHORT_START_PERIODS = int(CONFIG.get("cohort_start_periods", 1))
MAX_FILAS_ESTUDIANTE_PERIODO = int(
    os.environ.get(
        "SAT_MAX_SNAPSHOT_ROWS",
        CONFIG.get("max_snapshot_rows", N_ESTUDIANTES * PERIOD_COUNT),
    )
)
SCENARIO = os.environ.get("SAT_SYNTHETIC_SCENARIO", CONFIG.get("scenario", "baseline"))
SCENARIOS = CONFIG.get("scenarios", {})
if SCENARIO not in SCENARIOS:
    raise ValueError(f"Escenario sintético no configurado: {SCENARIO!r}")
SCENARIO_PARAMETERS = SCENARIOS[SCENARIO]
HAZARD_MULTIPLIER = float(SCENARIO_PARAMETERS.get("hazard_multiplier", 1.0))
TARGET_CONFIG = CONFIG.get("target", {})
TARGET_HORIZON_PERIODS = int(TARGET_CONFIG.get("horizon_periods", 2))
OUTCOME_FOLLOWUP_PERIODS = int(
    CONFIG.get("outcome_followup_periods", TARGET_HORIZON_PERIODS)
)
INTERVENTION_CONFIG = CONFIG.get("intervention_effectiveness", {})
FOLLOWUP_ALIGNMENT = str(CONFIG.get("followup_alignment", "aligned"))
if FOLLOWUP_ALIGNMENT not in ("aligned", "legacy"):
    raise ValueError("followup_alignment debe ser 'aligned' o 'legacy'.")

if (
    N_ESTUDIANTES < 1
    or PERIOD_COUNT < 3
    or TARGET_HORIZON_PERIODS < 1
    or OUTCOME_FOLLOWUP_PERIODS < 0
):
    raise ValueError("La configuración requiere estudiantes >=1, periodos >=3 y horizontes válidos.")
if MAX_FILAS_ESTUDIANTE_PERIODO < N_ESTUDIANTES:
    raise ValueError("SAT_MAX_SNAPSHOT_ROWS no puede ser menor que el número de estudiantes.")

# ─── Reproducibilidad ─────────────────────────────────────────────────────────
RNG = np.random.default_rng(seed=SEED)
RUN_TIMESTAMP = datetime.now(timezone.utc)
DEFAULT_OUTPUT_DIR = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "synthetic_runs"
    / f"{RUN_TIMESTAMP.strftime('%Y%m%dT%H%M%SZ')}_{SCENARIO}_{N_ESTUDIANTES}students"
)
OUTPUT_DIR = Path(
    os.environ.get(
        "SAT_OUTPUT_DIR",
        str(CONFIG.get("output_dir") or DEFAULT_OUTPUT_DIR),
    )
).expanduser()
if OUTPUT_DIR.exists() and any(OUTPUT_DIR.iterdir()) and os.environ.get("SAT_OVERWRITE_OUTPUT") != "true":
    raise FileExistsError(
        f"El directorio de salida ya contiene archivos: {OUTPUT_DIR}. "
        "Use otro SAT_OUTPUT_DIR o SAT_OVERWRITE_OUTPUT=true de forma explícita."
    )
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

print("=" * 70)
print("SAT-FUMC Digital Twin — Generador de Datos Sintéticos")
print("=" * 70)

# ==============================================================================
# 1. CATÁLOGOS MAESTROS
# ==============================================================================

SEDES = {
    "MED": {"nombre": "Medellín", "pct_matricula": 0.45, "modalidad_ppal": "Presencial", "ciudad": "Medellín"},
    "CAL": {"nombre": "Cali",     "pct_matricula": 0.12, "modalidad_ppal": "Presencial", "ciudad": "Cali"},
    "NEI": {"nombre": "Neiva",    "pct_matricula": 0.10, "modalidad_ppal": "Presencial", "ciudad": "Neiva"},
    "POP": {"nombre": "Popayán",  "pct_matricula": 0.08, "modalidad_ppal": "Híbrida",    "ciudad": "Popayán"},
    "VIR": {"nombre": "Virtual",  "pct_matricula": 0.25, "modalidad_ppal": "Virtual",    "ciudad": "Nacional"},
}

FACULTADES = {
    "CS":  "Ciencias de la Salud",
    "CE":  "Ciencias Empresariales",
    "ING": "Ingeniería",
    "CSO": "Ciencias Sociales",
}

PROGRAMAS = [
    {"codigo": "FIS", "nombre": "Fisioterapia",                "facultad": "CS",  "semestres": 10, "pct": 0.10, "creditos_plan": 160},
    {"codigo": "FON", "nombre": "Fonoaudiología",              "facultad": "CS",  "semestres": 10, "pct": 0.08, "creditos_plan": 155},
    {"codigo": "TOP", "nombre": "Terapia Ocupacional",         "facultad": "CS",  "semestres": 10, "pct": 0.08, "creditos_plan": 158},
    {"codigo": "NUT", "nombre": "Nutrición y Dietética",       "facultad": "CS",  "semestres": 10, "pct": 0.07, "creditos_plan": 152},
    {"codigo": "AFD", "nombre": "Actividad Física y Deporte",  "facultad": "CS",  "semestres": 10, "pct": 0.07, "creditos_plan": 148},
    {"codigo": "ADE", "nombre": "Administración de Empresas",  "facultad": "CE",  "semestres": 10, "pct": 0.14, "creditos_plan": 150},
    {"codigo": "CON", "nombre": "Contaduría Pública",          "facultad": "CE",  "semestres": 10, "pct": 0.11, "creditos_plan": 148},
    {"codigo": "ASV", "nombre": "Administración en Salud (Virtual)", "facultad": "CE", "semestres": 10, "pct": 0.05, "creditos_plan": 145},
    {"codigo": "SWE", "nombre": "Ingeniería de Software",      "facultad": "ING", "semestres": 10, "pct": 0.15, "creditos_plan": 165},
    {"codigo": "PSI", "nombre": "Psicología",                  "facultad": "CSO", "semestres": 10, "pct": 0.15, "creditos_plan": 160},
]

JORNADAS = ["Diurna", "Nocturna", "Mixta", "Virtual"]


def _build_periods(start_period: str, count: int) -> list[str]:
    try:
        year_text, semester_text = start_period.split("-", maxsplit=1)
        year, semester = int(year_text), int(semester_text)
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("start_period debe usar el formato YYYY-S.") from error
    if semester not in (1, 2):
        raise ValueError("El semestre del periodo debe ser 1 o 2.")
    periods = []
    for _ in range(count):
        periods.append(f"{year}-{semester}")
        if semester == 1:
            semester = 2
        else:
            year += 1
            semester = 1
    return periods


def _period_shift(period_id: str, offset: int) -> str:
    year_text, semester_text = period_id.split("-", maxsplit=1)
    ordinal = int(year_text) * 2 + int(semester_text) - 1 + offset
    return f"{ordinal // 2}-{ordinal % 2 + 1}"


PERIODOS = _build_periods(str(CONFIG["start_period"]), PERIOD_COUNT)

TIPOS_FINANCIACION = [
    "Recursos propios",
    "ICETEX crédito",
    "ICETEX subsidio",
    "Beca mérito",
    "Beca deporte",
    "Beca bienestar",
    "Crédito bancario",
    "Empresa/empleador",
    "Fondo territorial",
]

TIPOS_BECA = [None, "Beca Mérito", "Beca Deporte", "Beca Bienestar", "Beca Empresa", "Beca Territorial"]

MUNICIPIOS_COLOMBIA = [
    "Medellín", "Cali", "Neiva", "Popayán", "Bogotá",
    "Envigado", "Bello", "Itagüí", "Manizales", "Pereira",
    "Bucaramanga", "Barranquilla", "Cartagena", "Pasto", "Armenia",
    "Palmira", "Ibagué", "Villavicencio", "Montería", "Sincelejo",
]

TIPOS_APOYO_BIENESTAR = [
    "Psicoorientación",
    "Apoyo socioeconómico",
    "Tutoría académica",
    "Asesoría espiritual",
    "Talleres nivelación matemáticas",
    "Talleres nivelación lectura",
    "Orientación profesional",
    "Talleres manejo ansiedad",
]

TIPOS_SOLICITUD = [
    "Cancelación asignatura",
    "Aplazamiento semestre",
    "Paz y salvo",
    "Certificado matrícula",
    "Cambio de jornada",
    "Homologación",
    "Revisión nota",
    "Beca/financiación",
    "Transferencia interna",
]

# ==============================================================================
# 2. PARÁMETROS DE RIESGO (basados en literatura y contexto FUMC)
# ==============================================================================

# Riesgo base de deserción por programa
RIESGO_BASE_PROGRAMA = {
    "FIS": 0.035, "FON": 0.032, "TOP": 0.033, "NUT": 0.032, "AFD": 0.038,
    "ADE": 0.045, "CON": 0.048, "ASV": 0.060,
    "SWE": 0.050,
    "PSI": 0.042,
}

# Factores de riesgo multiplicativos (incrementales sobre el riesgo base)
FACTOR_PRIMER_SEMESTRE   = 1.45  # Estudios: mayor riesgo en primer año
FACTOR_JORNADA_NOCTURNA  = 1.30  # Estrato bajo + trabajo nocturno
FACTOR_ESTRATO_1_2       = 1.35  # Vulnerabilidad socioeconómica
FACTOR_MORA              = 1.50  # Mora financiera activa
FACTOR_SIN_TQUIEROENLAU  = 1.20  # No participación en programa permanencia
FACTOR_PROMEDIO_BAJO     = 1.60  # Promedio < 3.0
FACTOR_VIRTUAL           = 1.25  # Desconexión en modalidad virtual
FACTOR_TRABAJA           = 1.18  # Conciliación trabajo-estudio
FACTOR_JEFE_HOGAR        = 1.22  # Responsabilidades familiares
FACTOR_DISCAPACIDAD      = 1.15  # (protegido; solo para ajuste estadístico)
FACTOR_REZAGO_ALTO       = 1.40  # Rezago académico > 2 semestres
FACTOR_HISTORIAL_PRUEBA  = 1.55  # Historial de prueba académica
FACTOR_BECA_PROTECTORA   = 0.70  # Beca reduce riesgo de abandono

# ==============================================================================
# 3. HELPERS
# ==============================================================================

def gen_uuid():
    return str(uuid.UUID(int=RNG.integers(0, 2**128)))

def _clamp(val, lo, hi):
    return max(lo, min(hi, val))

def weighted_choice(choices, weights):
    weights = np.array(weights, dtype=float)
    weights /= weights.sum()
    idx = RNG.choice(len(choices), p=weights)
    return choices[idx]

def periodo_siguiente(periodo_id):
    anio, sem = int(periodo_id[:4]), int(periodo_id[5])
    if sem == 1:
        return f"{anio}-2"
    return f"{anio+1}-1"

def periodo_ordinal(periodo_id):
    return PERIODOS.index(periodo_id) if periodo_id in PERIODOS else -1

def periodo_add(periodo_id, n):
    idx = periodo_ordinal(periodo_id)
    new_idx = idx + n
    if 0 <= new_idx < len(PERIODOS):
        return PERIODOS[new_idx]
    return None

# ==============================================================================
# 4. CATÁLOGOS
# ==============================================================================
print("\n[1/10] Generando catálogos maestros...")

prog_df = pd.DataFrame(PROGRAMAS)
prog_df["facultad_nombre"] = prog_df["facultad"].map(FACULTADES)
prog_df.to_parquet(OUTPUT_DIR / "catalogos_programas.parquet", index=False)

sedes_df = pd.DataFrame([
    {"codigo_sede": k, **v} for k, v in SEDES.items()
])
sedes_df.to_parquet(OUTPUT_DIR / "catalogos_sedes.parquet", index=False)

# Calendario académico
cal_rows = []
for p in PERIODOS:
    anio, sem = int(p[:4]), int(p[5])
    inicio = date(anio, 1 if sem == 1 else 7, 15 if sem == 1 else 20)
    fin = inicio + timedelta(weeks=18)
    for sede in SEDES.keys():
        cal_rows.append({
            "periodo_id": p,
            "sede": sede,
            "fecha_inicio_clases": inicio,
            "fecha_fin_clases": fin,
            "fecha_corte_1":  inicio + timedelta(weeks=4),
            "fecha_corte_2":  inicio + timedelta(weeks=8),
            "fecha_cierre":   fin,
            "semanas_efectivas": 16,
            "fecha_limite_pago_matricula": inicio - timedelta(days=10),
        })
cal_df = pd.DataFrame(cal_rows)
cal_df.to_parquet(OUTPUT_DIR / "calendario_academico.parquet", index=False)

# Asignaturas por programa
asig_rows = []
for prog in PROGRAMAS:
    n_asig = 45 + RNG.integers(-3, 4)
    for i in range(1, n_asig + 1):
        semestre_asig = int(np.ceil(i / (n_asig / 10)))
        asig_rows.append({
            "asignatura_id": f"{prog['codigo']}-A{i:03d}",
            "nombre_asignatura": f"Asignatura {i} de {prog['nombre']}",
            "programa": prog["codigo"],
            "semestre_del_plan": min(semestre_asig, 10),
            "creditos": int(RNG.choice([2, 3, 4], p=[0.2, 0.6, 0.2])),
            "tipo_asignatura": RNG.choice(
                ["Teórica", "Teórico-práctica", "Práctica", "Electiva"],
                p=[0.35, 0.40, 0.20, 0.05]
            ),
            "area_conocimiento": RNG.choice(
                ["Fundamental", "Disciplinar", "Complementaria", "Humanidades"],
                p=[0.30, 0.40, 0.20, 0.10]
            ),
        })
asig_df = pd.DataFrame(asig_rows)
asig_df.to_parquet(OUTPUT_DIR / "catalogos_asignaturas.parquet", index=False)

print(f"   Programas: {len(prog_df)} | Sedes: {len(sedes_df)} | Periodos: {len(PERIODOS)} | Asignaturas: {len(asig_df)}")

# ==============================================================================
# 5. POBLACIÓN DE ESTUDIANTES (6,000 registros únicos)
# ==============================================================================
print("\n[2/10] Generando población de estudiantes...")

if COHORT_START_PERIODS < 1 or COHORT_START_PERIODS > len(PERIODOS):
    raise ValueError("cohort_start_periods debe estar entre 1 y el número de periodos.")
programa_pcts = [p["pct"] for p in PROGRAMAS]
programas_codigos = [p["codigo"] for p in PROGRAMAS]
sede_pcts = [v["pct_matricula"] for v in SEDES.values()]
sede_codigos = list(SEDES.keys())

estudiantes = []
for i in range(N_ESTUDIANTES):
    # Programa y sede
    prog_code = weighted_choice(programas_codigos, programa_pcts)
    prog_info = next(p for p in PROGRAMAS if p["codigo"] == prog_code)

    # Sede: programas virtuales tienen mayor probabilidad de sede VIR
    if prog_code == "ASV":
        sede_code = "VIR"
    else:
        _sede_pcts = [0.42, 0.13, 0.11, 0.09, 0.25] if prog_code != "ASV" else [0, 0, 0, 0, 1]
        sede_code = weighted_choice(sede_codigos, _sede_pcts)

    sede_info = SEDES[sede_code]
    modalidad = "Virtual" if sede_code == "VIR" else sede_info["modalidad_ppal"]

    # Jornada (virtual siempre virtual)
    if modalidad == "Virtual":
        jornada = "Virtual"
    else:
        jornada = weighted_choice(["Diurna", "Nocturna", "Mixta"], [0.60, 0.30, 0.10])

    # Periodo de ingreso
    n_periodos_disponibles = len(PERIODOS)
    cohorte_idx = int(RNG.integers(0, min(COHORT_START_PERIODS, n_periodos_disponibles)))
    cohorte_ingreso = PERIODOS[cohorte_idx]

    # Sociodemografía
    estrato = int(RNG.choice([1, 2, 3, 4, 5, 6], p=[0.20, 0.30, 0.30, 0.12, 0.05, 0.03]))
    genero = weighted_choice(["F", "M", "NB"], [0.58, 0.40, 0.02])
    edad_ingreso = int(RNG.integers(16, 35))
    trabaja = bool(RNG.random() < (0.55 if jornada == "Nocturna" else 0.30))
    jefe_hogar = bool(RNG.random() < (0.25 if trabaja else 0.10))
    discapacidad = bool(RNG.random() < 0.04)
    n_mun = len(MUNICIPIOS_COLOMBIA)
    mun_pcts = [0.20] + [0.80 / (n_mun - 1)] * (n_mun - 1)
    municipio = weighted_choice(MUNICIPIOS_COLOMBIA, mun_pcts)

    # Admisión
    puntaje_global = round(float(RNG.normal(280, 45)), 1)
    puntaje_global = _clamp(puntaje_global, 100, 500)
    puntaje_matematicas = round(float(RNG.normal(45, 12)), 1)
    puntaje_matematicas = _clamp(puntaje_matematicas, 0, 100)
    puntaje_lectura = round(float(RNG.normal(50, 10)), 1)
    puntaje_lectura = _clamp(puntaje_lectura, 0, 100)
    puntaje_ingles = round(float(RNG.normal(42, 15)), 1)
    puntaje_ingles = _clamp(puntaje_ingles, 0, 100)
    puntaje_ciencias = round(float(RNG.normal(47, 11)), 1)
    puntaje_ciencias = _clamp(puntaje_ciencias, 0, 100)
    tipo_ingreso = weighted_choice(
        ["Primera vez universitario", "Transferencia externa", "Reingreso", "Homologación"],
        [0.75, 0.10, 0.10, 0.05]
    )

    # Financiación
    tiene_beca_flag = bool(RNG.random() < 0.18)
    tipo_beca = None
    tipo_financiacion = weighted_choice(TIPOS_FINANCIACION, [0.30, 0.20, 0.10, 0.08, 0.05, 0.05, 0.08, 0.07, 0.07])
    if tiene_beca_flag:
        tipo_beca = weighted_choice(["Beca Mérito","Beca Deporte","Beca Bienestar","Beca Empresa","Beca Territorial"],
                                    [0.35, 0.15, 0.25, 0.15, 0.10])
        tipo_financiacion = tipo_beca

    estudiantes.append({
        "id_estudiante_anon": f"ST-{i+1:06d}",
        "cohorte_ingreso": cohorte_ingreso,
        "programa": prog_code,
        "sede": sede_code,
        "jornada": jornada,
        "modalidad": modalidad,
        "genero": genero,
        "edad_ingreso": edad_ingreso,
        "estrato_socioeconomico": estrato,
        "municipio_residencia": municipio,
        "trabaja": trabaja,
        "jefe_hogar": jefe_hogar,
        "discapacidad": discapacidad,
        "puntaje_global_prueba_ingreso": puntaje_global,
        "puntaje_matematicas": puntaje_matematicas,
        "puntaje_lectura_critica": puntaje_lectura,
        "puntaje_ingles": puntaje_ingles,
        "puntaje_ciencias": puntaje_ciencias,
        "tipo_ingreso": tipo_ingreso,
        "tiene_beca": tiene_beca_flag,
        "tipo_beca": tipo_beca,
        "tipo_financiacion": tipo_financiacion,
    })

est_df = pd.DataFrame(estudiantes)
print(f"   Estudiantes generados: {len(est_df):,}")
print(f"   Distribución programas:\n{est_df['programa'].value_counts().to_string()}")
print(f"   Distribución sedes:\n{est_df['sede'].value_counts().to_string()}")

# ==============================================================================
# 6. TRAYECTORIAS LONGITUDINALES
# ==============================================================================
print("\n[3/10] Simulando trayectorias longitudinales...")

prog_dict = {p["codigo"]: p for p in PROGRAMAS}

main_rows      = []   # estudiante_periodo_corte
target_rows    = []   # target_trazabilidad
fin_rows       = []   # financiera_estudiante_evento
bienestar_rows = []   # bienestar_acompanamiento
sol_rows       = []   # solicitudes_estudiantiles

for idx, est in est_df.iterrows():
    if idx % 2000 == 0:
        print(f"   Procesando estudiante {idx}/{N_ESTUDIANTES}...")

    cohorte_idx = PERIODOS.index(est["cohorte_ingreso"])
    prog_info   = prog_dict[est["programa"]]
    estado_actual = "Activo"
    promedio_acum  = None
    creditos_acum  = 0
    semestres_curs  = 0
    historial_prueba = False
    mejor_promedio  = None
    peor_promedio   = None
    promedios_hist  = []
    student_main_start = len(main_rows)
    outcome_period_index = None
    outcome_type = None
    previous_support = False
    previous_mora_state = False
    last_hazard_probability = None

    for p_idx in range(cohorte_idx, len(PERIODOS)):
        if estado_actual in ("Desertor", "Graduado", "Aplazado_permanente"):
            break

        periodo_id = PERIODOS[p_idx]
        periodo_siguiente_id = PERIODOS[p_idx + 1] if p_idx + 1 < len(PERIODOS) else None
        periodo_siguiente2_id = PERIODOS[p_idx + 2] if p_idx + 2 < len(PERIODOS) else None
        periodo_ord_estudiante = p_idx - cohorte_idx + 1  # periodo relativo del estudiante

        anio, sem = int(periodo_id[:4]), int(periodo_id[5])
        semestres_curs += 1

        # ── Académico (simular promedio del semestre) ──────────────────────────
        # Base promedio con varianza
        prom_base = 3.5 + (est["puntaje_global_prueba_ingreso"] - 280) / 400
        if previous_support:
            prom_base += float(INTERVENTION_CONFIG.get("academic_support_grade_delta", 0.0))
        # Degradar si riesgo alto
        if promedio_acum is not None and promedio_acum < 3.0:
            prom_base -= 0.3
        prom_sem = round(float(RNG.normal(prom_base, 0.55)), 2)
        prom_sem = _clamp(prom_sem, 0.0, 5.0)

        # Créditos
        creditos_sem = int(RNG.choice([12, 15, 18, 21], p=[0.10, 0.25, 0.50, 0.15]))
        creditos_sem = _clamp(creditos_sem, 6, 21)
        tasa_aprobacion = _clamp(float(RNG.beta(8 if prom_sem >= 3.0 else 3, 2)), 0.3, 1.0)
        cred_aprobados = round(creditos_sem * tasa_aprobacion)
        cred_reprobados = creditos_sem - cred_aprobados
        num_mat = int(creditos_sem / 3)
        num_perdidas = round(num_mat * (1 - tasa_aprobacion))
        num_canceladas = int(RNG.integers(0, 2 + (1 if prom_sem < 3.0 else 0)))
        creditos_acum += cred_aprobados
        promedios_hist.append(prom_sem)
        promedio_acum = round(np.mean(promedios_hist), 2)
        mejor_promedio = max(promedios_hist)
        peor_promedio  = min(promedios_hist)
        prom_anterior  = promedios_hist[-2] if len(promedios_hist) >= 2 else None
        tendencia_prom = round(prom_sem - prom_anterior, 2) if prom_anterior else 0.0

        # Avance plan
        total_creditos_plan = prog_info["creditos_plan"]
        avance_pct = round(creditos_acum / total_creditos_plan * 100, 2)
        semestres_plan = prog_info["semestres"]
        avance_esperado = period_ord = (semestres_curs / semestres_plan) * 100
        rezago = round(avance_esperado - avance_pct, 2)

        # Prueba académica
        en_prueba_academica = prom_sem < 2.8 and semestres_curs > 1
        if en_prueba_academica:
            historial_prueba = True

        # ── Financiero ──────────────────────────────────────────────────────
        monto_matricula = float(RNG.choice([3_500_000, 4_200_000, 5_000_000, 6_800_000], p=[0.25, 0.35, 0.25, 0.15]))
        # Ajustar por beca
        if est["tiene_beca"]:
            monto_matricula *= RNG.uniform(0.0, 0.6)  # beca cubre parte o todo
        mora_base = 0.0
        if previous_mora_state:
            tiene_mora = bool(RNG.random() < 0.65)
        else:
            mora_incidence = 0.30 if est["estrato_socioeconomico"] <= 2 else 0.12
            tiene_mora = bool(RNG.random() < mora_incidence)
        previous_mora_state = tiene_mora
        saldo_mora = round(float(RNG.uniform(50_000, 2_500_000)) if tiene_mora else 0.0, 2)
        bloqueo_financiero = bool(saldo_mora > 1_000_000)
        tipo_fin_periodo = est["tipo_financiacion"]

        # Eventos financieros
        for ev_type in ["liquidacion", "pago_parcial"] + (["mora"] if tiene_mora else []):
            if ev_type == "liquidacion":
                monto_ev = monto_matricula
            else:
                monto_ev = RNG.uniform(min(500_000.0, monto_matricula), max(500_000.0, monto_matricula))
            fin_rows.append({
                "id_estudiante_anon": est["id_estudiante_anon"],
                "periodo_id": periodo_id,
                "tipo_evento": ev_type,
                "fecha_evento": str(date(anio, 1 if sem == 1 else 7, int(RNG.integers(1, 28)))),
                "monto": round(float(monto_ev), 2),
                "saldo_pendiente": round(float(saldo_mora), 2),
                "tipo_financiacion": tipo_fin_periodo,
                "bloqueo_activo": bloqueo_financiero,
            })

        # ── LMS / Engagement ───────────────────────────────────────────────
        es_virtual = est["modalidad"] == "Virtual"
        engagement_mean = 45 if not es_virtual else 80
        if prom_sem < 3.0:
            engagement_mean *= 0.72
        if previous_support:
            engagement_mean *= 1.08
        accesos_sem_lms = int(_clamp(RNG.normal(engagement_mean, 20), 0, 150))
        days_mean = 28 if prom_sem >= 3.0 else 20
        dias_activos = int(_clamp(RNG.normal(days_mean, 8), 0, 60))
        tareas_vencidas = int(_clamp(RNG.poisson(1.5 if prom_sem < 3.0 else 0.5), 0, 10))
        participacion_foros = int(_clamp(RNG.poisson(3), 0, 20))
        evaluaciones_comp = int(_clamp(RNG.normal(5, 1.5), 0, 10))

        # Score de engagement LMS (derivado)
        engagement_lms = round(
            0.4 * min(accesos_sem_lms / 60, 1.0) +
            0.3 * min(dias_activos / 40, 1.0) +
            0.2 * max(0, 1 - tareas_vencidas / 5) +
            0.1 * min(participacion_foros / 5, 1.0), 3
        )

        # ── Bienestar ──────────────────────────────────────────────────────
        asistio_tquieroenlaU = bool(RNG.random() < (0.45 if prom_sem < 3.5 or saldo_mora > 0 else 0.20))
        num_sesiones_bienestar = int(RNG.poisson(2.5) if asistio_tquieroenlaU else 0)
        previous_support = asistio_tquieroenlaU and num_sesiones_bienestar > 0
        tipo_apoyo = None
        if asistio_tquieroenlaU:
            tipo_apoyo = weighted_choice(TIPOS_APOYO_BIENESTAR, [0.20, 0.20, 0.20, 0.08, 0.12, 0.08, 0.07, 0.05])
            bienestar_rows.append({
                "id_estudiante_anon": est["id_estudiante_anon"],
                "periodo_id": periodo_id,
                "tipo_apoyo": tipo_apoyo,
                "num_sesiones": num_sesiones_bienestar,
                "canal": weighted_choice(["Presencial", "Virtual", "Híbrido"], [0.50, 0.30, 0.20]),
                "asistio": True,
                "estado_seguimiento": weighted_choice(["Activo", "Cerrado", "Derivado"], [0.60, 0.30, 0.10]),
            })

        # ── Solicitudes ────────────────────────────────────────────────────
        n_solicitudes = int(RNG.poisson(0.8 if rezago > 10 or saldo_mora > 0 else 0.3))
        for _ in range(n_solicitudes):
            tipo_sol = weighted_choice(TIPOS_SOLICITUD, [0.20, 0.10, 0.12, 0.15, 0.08, 0.10, 0.10, 0.08, 0.07])
            mes_base = 1 if sem == 1 else 7
            dia_base = int(RNG.integers(1, 28))
            sol_date = date(anio, mes_base, dia_base) + timedelta(days=int(RNG.integers(0, 75)))
            sol_rows.append({
                "id_estudiante_anon": est["id_estudiante_anon"],
                "periodo_id": periodo_id,
                "tipo_solicitud": tipo_sol,
                "fecha_radicacion": str(sol_date),
                "estado": weighted_choice(["Aprobada", "Rechazada", "En revisión"], [0.60, 0.20, 0.20]),
            })

        # ── Cálculo de riesgo de deserción ────────────────────────────────
        riesgo_base = RIESGO_BASE_PROGRAMA[est["programa"]]
        risk = riesgo_base

        if semestres_curs == 1:              risk *= FACTOR_PRIMER_SEMESTRE
        if est["jornada"] == "Nocturna":     risk *= FACTOR_JORNADA_NOCTURNA
        if est["estrato_socioeconomico"] <= 2: risk *= FACTOR_ESTRATO_1_2
        if tiene_mora:                        risk *= FACTOR_MORA
        if not asistio_tquieroenlaU:          risk *= FACTOR_SIN_TQUIEROENLAU
        if prom_sem < 3.0:                    risk *= FACTOR_PROMEDIO_BAJO
        if est["modalidad"] == "Virtual":     risk *= FACTOR_VIRTUAL
        if est["trabaja"]:                    risk *= FACTOR_TRABAJA
        if est["jefe_hogar"]:                 risk *= FACTOR_JEFE_HOGAR
        if rezago > 15:                       risk *= FACTOR_REZAGO_ALTO
        if historial_prueba:                  risk *= FACTOR_HISTORIAL_PRUEBA
        if est["tiene_beca"]:                 risk *= FACTOR_BECA_PROTECTORA
        if bloqueo_financiero:                risk *= 1.30
        if previous_support:
            risk *= float(INTERVENTION_CONFIG.get("followup_hazard_multiplier", 1.0))

        # Scenario changes prevalence without tying the label to a single feature.
        prob_desercion = _clamp(risk * HAZARD_MULTIPLIER, 0.01, 0.95)
        last_hazard_probability = prob_desercion
        deserta = bool(RNG.random() < prob_desercion)

        # ── Variables derivadas adicionales ───────────────────────────────
        tasa_aprobacion_calc = round(cred_aprobados / max(creditos_sem, 1), 3)
        intensidad_perdida   = round(num_perdidas / max(num_mat, 1), 3)
        indice_riesgo_academico = round(
            (1 - tasa_aprobacion_calc) * 0.5 +
            (max(0, 3.0 - prom_sem) / 3.0) * 0.3 +
            (1 if historial_prueba else 0) * 0.2, 3
        )

        # ── Fila tabla principal ──────────────────────────────────────────
        fecha_inicio_periodo = date(anio, 1 if sem == 1 else 7, 15 if sem == 1 else 20)
        fecha_corte = fecha_inicio_periodo + timedelta(weeks=18)
        row = {
            # Identificación y temporalidad
            "id_estudiante_anon":        est["id_estudiante_anon"],
            "cohorte_ingreso":           est["cohorte_ingreso"],
            "anio":                      anio,
            "semestre":                  sem,
            "periodo_id":                periodo_id,
            "periodo_ordinal_estudiante": period_ord,
            "fecha_corte_predictiva":    fecha_corte,
            "tipo_corte_predictivo":     str(TARGET_CONFIG.get("observation_cut", "CIERRE")),
            "antiguedad_institucional_periodos": semestres_curs,
            # Programa y sede
            "programa":                  est["programa"],
            "sede":                      est["sede"],
            "jornada":                   est["jornada"],
            "modalidad":                 est["modalidad"],
            # Admisión (fijos)
            "puntaje_global_prueba_ingreso": est["puntaje_global_prueba_ingreso"],
            "puntaje_matematicas":       est["puntaje_matematicas"],
            "puntaje_lectura_critica":   est["puntaje_lectura_critica"],
            "puntaje_ingles":            est["puntaje_ingles"],
            "puntaje_ciencias":          est["puntaje_ciencias"],
            "tipo_ingreso":              est["tipo_ingreso"],
            # Académicas
            "promedio_semestre":         prom_sem,
            "promedio_semestre_anterior": round(prom_anterior, 2) if prom_anterior else None,
            "promedio_acumulado":        promedio_acum,
            "mejor_promedio_hist":       round(mejor_promedio, 2),
            "peor_promedio_hist":        round(peor_promedio, 2),
            "tendencia_promedio":        tendencia_prom,
            "creditos_inscritos":        creditos_sem,
            "creditos_aprobados":        cred_aprobados,
            "creditos_reprobados":       cred_reprobados,
            "creditos_acumulados":       creditos_acum,
            "num_materias_inscritas":    num_mat,
            "num_materias_perdidas":     num_perdidas,
            "num_materias_canceladas":   num_canceladas,
            "semestres_cursados":        semestres_curs,
            "avance_plan_pct":           avance_pct,
            "rezago_academico":          rezago,
            "historial_prueba_academica": int(historial_prueba),
            "en_prueba_academica_actual": int(en_prueba_academica),
            # Socioeconómico
            "estrato_socioeconomico":    est["estrato_socioeconomico"],
            "genero":                    est["genero"],
            "edad_en_periodo":           est["edad_ingreso"] + (semestres_curs // 2),
            "municipio_residencia":      est["municipio_residencia"],
            "trabaja":                   int(est["trabaja"]),
            "jefe_hogar":                int(est["jefe_hogar"]),
            "discapacidad":              int(est["discapacidad"]),
            # Financiero
            "tipo_financiacion":         tipo_fin_periodo,
            "monto_matricula":           round(monto_matricula, 2),
            "saldo_mora":                saldo_mora,
            "bloqueo_financiero":        int(bloqueo_financiero),
            "tiene_beca":                int(est["tiene_beca"]),
            "tipo_beca":                 est["tipo_beca"],
            # LMS
            "accesos_lms_semestre":      accesos_sem_lms,
            "dias_activos_lms":          dias_activos,
            "tareas_vencidas":           tareas_vencidas,
            "participacion_foros":       participacion_foros,
            "evaluaciones_completadas":  evaluaciones_comp,
            "engagement_lms":            engagement_lms,
            # Bienestar
            "asistio_tquieroenlaU":      int(asistio_tquieroenlaU),
            "num_sesiones_bienestar":    num_sesiones_bienestar,
            "tipo_apoyo_bienestar":      tipo_apoyo,
            # Solicitudes
            "num_solicitudes_periodo":   n_solicitudes,
            # Variables derivadas
            "tasa_aprobacion":           tasa_aprobacion_calc,
            "intensidad_perdida":        intensidad_perdida,
            "indice_riesgo_academico":   indice_riesgo_academico,
            "tendencia_financiera":      round(saldo_mora / max(monto_matricula, 1), 3),
            # The latent hazard and outcome stay internal to the generator.
            "_period_index":             p_idx,
        }
        main_rows.append(row)

        if deserta:
            estado_actual = "Desertor"
            outcome_period_index = p_idx + 1
            outcome_type = "dropout"
            break
        else:
            if creditos_acum >= total_creditos_plan * 0.95 and semestres_curs >= semestres_plan - 1:
                if bool(RNG.random() < 0.70):
                    estado_actual = "Graduado"
                    outcome_period_index = p_idx + 1
                    outcome_type = "graduation"
                    break
            if RNG.random() < 0.006:
                estado_actual = "Transferencia"
                outcome_period_index = p_idx + 1
                outcome_type = "transfer"
                break
            if RNG.random() < 0.008:
                estado_actual = "Aplazado_formal"
                outcome_period_index = p_idx + 1
                outcome_type = "formal_leave"
                break

    # Continue outcome observation after the final feature snapshot. These
    # follow-up draws affect labels only and are never emitted as predictors.
    if outcome_period_index is None and last_hazard_probability is not None:
        last_snapshot_index = len(PERIODOS) - 1
        # A dropout draw at snapshot q produces an outcome at period q+1. The
        # "aligned" mode therefore simulates virtual snapshots after the last
        # observed one and places each event one period later, so every label
        # window contains the same number of independent hazard draws. The
        # "legacy" mode (generator <= 2.0.0) drew the first follow-up event at
        # last+1, duplicating the last snapshot's own draw and inflating the
        # label prevalence of the final periods.
        if FOLLOWUP_ALIGNMENT == "aligned":
            followup_offsets = range(1, OUTCOME_FOLLOWUP_PERIODS)
            outcome_shift = 1
        else:
            followup_offsets = range(1, OUTCOME_FOLLOWUP_PERIODS + 1)
            outcome_shift = 0
        for future_offset in followup_offsets:
            future_hazard = _clamp(
                last_hazard_probability * (0.92 ** (future_offset - 1)),
                0.01,
                0.95,
            )
            event_index = last_snapshot_index + future_offset + outcome_shift
            if RNG.random() < future_hazard:
                outcome_period_index = event_index
                outcome_type = "dropout"
                break
            if RNG.random() < 0.006:
                outcome_period_index = event_index
                outcome_type = "transfer"
                break
            if RNG.random() < 0.008:
                outcome_period_index = event_index
                outcome_type = "formal_leave"
                break

    # Labels are outcomes after the observation cut, never the current-period
    # hazard draw. Right-censored snapshots retain an explicit immature label.
    for row in main_rows[student_main_start:]:
        period_index = int(row.pop("_period_index"))
        horizon_end = period_index + TARGET_HORIZON_PERIODS
        event_in_window = (
            outcome_period_index is not None
            and period_index < outcome_period_index <= horizon_end
        )
        followup_end_index = len(PERIODOS) - 1 + OUTCOME_FOLLOWUP_PERIODS
        full_horizon_observed = horizon_end <= followup_end_index
        if event_in_window:
            target_observed = True
            target_label = int(outcome_type == "dropout")
        elif full_horizon_observed:
            target_observed = True
            target_label = 0
        else:
            target_observed = False
            target_label = None

        target_row = {
            "id_estudiante_anon": row["id_estudiante_anon"],
            "periodo_id": row["periodo_id"],
            "reinscrito_t1": None,
            "reinscrito_t2": None,
            "graduado_hasta_t2": 0,
            "transferencia_interna_hasta_t2": 0,
            "aplazamiento_formal_hasta_t2": 0,
            "target_desercion": target_label,
            "target_observado": target_observed,
            "horizonte_periodos": TARGET_HORIZON_PERIODS,
            "periodo_inicio_horizonte": _period_shift(row["periodo_id"], 1),
            "periodo_fin_horizonte": _period_shift(
                row["periodo_id"], TARGET_HORIZON_PERIODS
            ),
            "evento_simulado": outcome_type if event_in_window else None,
        }
        if target_observed:
            target_row["reinscrito_t1"] = int(
                outcome_period_index is None
                or outcome_period_index > period_index + 1
            )
            if outcome_type == "graduation" and event_in_window:
                target_row["graduado_hasta_t2"] = 1
            elif outcome_type == "transfer" and event_in_window:
                target_row["transferencia_interna_hasta_t2"] = 1
            elif outcome_type == "formal_leave" and event_in_window:
                target_row["aplazamiento_formal_hasta_t2"] = 1
            target_row["reinscrito_t2"] = int(
                outcome_period_index is None
                or outcome_period_index > period_index + 2
            )
        target_rows.append(target_row)
print(f"   Registros tabla principal: {len(main_rows):,}")
print(f"   Registros target:          {len(target_rows):,}")
print(f"   Registros financiero:      {len(fin_rows):,}")
print(f"   Registros bienestar:       {len(bienestar_rows):,}")
print(f"   Solicitudes:               {len(sol_rows):,}")
if len(main_rows) > MAX_FILAS_ESTUDIANTE_PERIODO or len(target_rows) > MAX_FILAS_ESTUDIANTE_PERIODO:
    raise RuntimeError(
        "El Digital Twin excede el límite de "
        f"{MAX_FILAS_ESTUDIANTE_PERIODO:,} filas por snapshot/target."
    )

# ==============================================================================
# 7. CONVERTIR Y GUARDAR
# ==============================================================================
print("\n[4/10] Guardando tabla principal (estudiante_periodo_corte)...")
main_df = pd.DataFrame(main_rows)
main_df_clean = main_df.copy()
main_df_clean.to_parquet(OUTPUT_DIR / "estudiante_periodo_corte.parquet", index=False)
print(f"   Guardado: estudiante_periodo_corte.parquet ({len(main_df_clean):,} filas x {len(main_df_clean.columns)} cols)")

print("\n[5/10] Guardando target_trazabilidad (tabla SEPARADA)...")
target_df = pd.DataFrame(target_rows)
target_df.to_parquet(OUTPUT_DIR / "target_trazabilidad.parquet", index=False)
observed_target_df = target_df[target_df["target_observado"]]
n_desertores = int(observed_target_df["target_desercion"].sum())
target_prevalence = float(observed_target_df["target_desercion"].mean())
print(f"   Guardado: target_trazabilidad.parquet ({len(target_df):,} filas)")
print(f"   Etiquetas maduras: {len(observed_target_df):,} | inmaduras/censuradas: {len(target_df)-len(observed_target_df):,}")
print(f"   Deserción futura: {n_desertores:,} ({target_prevalence:.1%} de etiquetas maduras)")

print("\n[6/10] Guardando financiera_estudiante_evento...")
fin_df = pd.DataFrame(fin_rows)
fin_df.to_parquet(OUTPUT_DIR / "financiera_estudiante_evento.parquet", index=False)
print(f"   Guardado: financiera_estudiante_evento.parquet ({len(fin_df):,} filas)")

print("\n[7/10] Guardando bienestar_acompanamiento...")
bienestar_df = pd.DataFrame(bienestar_rows)
bienestar_df.to_parquet(OUTPUT_DIR / "bienestar_acompanamiento.parquet", index=False)
print(f"   Guardado: bienestar_acompanamiento.parquet ({len(bienestar_df):,} filas)")

print("\n[8/10] Guardando solicitudes_estudiantiles...")
sol_df = pd.DataFrame(sol_rows)
sol_df.to_parquet(OUTPUT_DIR / "solicitudes_estudiantiles.parquet", index=False)
print(f"   Guardado: solicitudes_estudiantiles.parquet ({len(sol_df):,} filas)")

# ==============================================================================
# 8. TABLA DE DETALLE POR ASIGNATURA
# ==============================================================================
print("\n[9/10] Generando estudiante_asignatura_periodo...")
course_lookup = {
    (str(program), int(course_semester)): group[
        ["asignatura_id", "creditos"]
    ].to_numpy(dtype=object)
    for (program, course_semester), group in asig_df.groupby(
        ["programa", "semestre_del_plan"], sort=False
    )
}
program_course_lookup = {
    str(program): group[["asignatura_id", "creditos"]].to_numpy(dtype=object)
    for program, group in asig_df.groupby("programa", sort=False)
}
assignment_frames = []
snapshot_groups = main_df_clean.groupby(
    ["programa", "semestres_cursados"], sort=False
)
for (program, semester), snapshots in snapshot_groups:
    course_semester = min(int(semester), 10)
    courses = course_lookup.get(
        (str(program), course_semester), program_course_lookup[str(program)]
    )
    if not len(courses):
        continue
    requested_count = snapshots["num_materias_inscritas"].to_numpy(dtype=int)
    count_per_snapshot = np.minimum(requested_count, len(courses))
    maximum_count = int(count_per_snapshot.max(initial=0))
    if maximum_count == 0:
        continue
    # One random permutation per snapshot preserves without-replacement course
    # selection while avoiding a DataFrame scan/sample for each of 100k students.
    course_order = np.argsort(
        RNG.random((len(snapshots), len(courses))), axis=1
    )
    for rank in range(maximum_count):
        active = count_per_snapshot > rank
        if not active.any():
            continue
        active_snapshots = snapshots.loc[active]
        selected_courses = courses[course_order[active, rank]]
        count = len(active_snapshots)
        average = active_snapshots["promedio_semestre"].to_numpy(dtype=float)
        first_grade = np.round(
            np.clip(RNG.normal(average + 0.1, 0.4), 0.0, 5.0), 1
        )
        second_grade = np.round(
            np.clip(RNG.normal(average, 0.4), 0.0, 5.0), 1
        )
        attendance = np.where(
            average >= 3.0,
            RNG.beta(8, 2, size=count),
            RNG.beta(3, 3, size=count),
        )
        attendance = np.round(attendance * 100, 1)
        cancelled = (
            (first_grade < 2.0) & (RNG.random(count) < 0.25)
        ).astype(int)
        result = np.where(
            (second_grade >= 3.0) & (cancelled == 0),
            "Aprobada",
            np.where(cancelled == 1, "Cancelada", "Reprobada"),
        )
        assignment_frames.append(pd.DataFrame({
            "id_estudiante_anon": active_snapshots["id_estudiante_anon"].to_numpy(),
            "periodo_id": active_snapshots["periodo_id"].to_numpy(),
            "asignatura_id": selected_courses[:, 0],
            "creditos_asignatura": selected_courses[:, 1].astype(int),
            "nota_primer_corte": first_grade,
            "nota_segundo_corte": second_grade,
            "asistencia_pct": attendance,
            "cancelada": cancelled,
            "resultado": result,
        }))

asig_det_df = (
    pd.concat(assignment_frames, ignore_index=True)
    if assignment_frames
    else pd.DataFrame(columns=[
        "id_estudiante_anon", "periodo_id", "asignatura_id",
        "creditos_asignatura", "nota_primer_corte", "nota_segundo_corte",
        "asistencia_pct", "cancelada", "resultado",
    ])
)
asig_det_df.to_parquet(OUTPUT_DIR / "estudiante_asignatura_periodo.parquet", index=False)
print(f"   Guardado: estudiante_asignatura_periodo.parquet ({len(asig_det_df):,} filas)")

# ==============================================================================
# 9. ESTADÍSTICAS FINALES Y VALIDACIÓN
# ==============================================================================
print("\n[10/10] Validando Digital Twin...")

validaciones = []

# PK único
pk_duplicados = main_df_clean.duplicated(subset=["id_estudiante_anon", "periodo_id"]).sum()
validaciones.append(("PK unica (id_estudiante + periodo)", pk_duplicados == 0, f"{pk_duplicados} duplicados"))

# Cobertura sedes
sedes_cubiertas = set(main_df_clean["sede"].unique())
todas_sedes = set(SEDES.keys())
validaciones.append(("Cobertura todas las sedes", sedes_cubiertas == todas_sedes,
                    f"Cubiertas: {len(sedes_cubiertas)}/{len(todas_sedes)}"))

# Rango promedios
prom_ok = main_df_clean["promedio_semestre"].between(0, 5).all()
validaciones.append(("Promedios entre 0-5", prom_ok, ""))

# Créditos no negativos
cred_ok = (main_df_clean["creditos_inscritos"] >= 0).all()
validaciones.append(("Creditos >= 0", cred_ok, ""))

# Tasa deserción: emergent prevalence is reported, not forced into one range.
tasa_desercion = target_prevalence
tasa_ok = (
    np.isfinite(tasa_desercion)
    and 0.0 < tasa_desercion < 1.0
    and observed_target_df["target_desercion"].nunique() == 2
)
validaciones.append(("Target futuro con ambas clases", tasa_ok, f"Tasa madura: {tasa_desercion:.1%}"))

# Target separado de predictores
target_en_main = "target_desercion" in main_df_clean.columns
validaciones.append(("Target NO esta en tabla predictores", not target_en_main, ""))

print("\n--- REPORTE DE VALIDACION DIGITAL TWIN ---")
for nombre, ok, detalle in validaciones:
    status = "[OK]" if ok else "[FAIL]"
    print(f" {status} {nombre:<45} {detalle}")

if not all(ok for _, ok, _ in validaciones):
    raise RuntimeError("Fallaron una o más validaciones del Digital Twin.")

effective_config = {
    **CONFIG,
    "generator_version": GENERATOR_VERSION,
    "students": N_ESTUDIANTES,
    "seed": SEED,
    "start_period": PERIODOS[0],
    "period_count": len(PERIODOS),
    "periods": PERIODOS,
    "cohort_start_periods": COHORT_START_PERIODS,
    "max_snapshot_rows": MAX_FILAS_ESTUDIANTE_PERIODO,
    "scenario": SCENARIO,
    "scenario_parameters": SCENARIO_PARAMETERS,
    "target": {
        **TARGET_CONFIG,
        "horizon_periods": TARGET_HORIZON_PERIODS,
    },
        "outcome_followup_periods": OUTCOME_FOLLOWUP_PERIODS,
    "followup_alignment": FOLLOWUP_ALIGNMENT,
}
effective_config_text = json.dumps(
    effective_config, sort_keys=True, ensure_ascii=False, separators=(",", ":")
)
file_hashes = {}
for parquet_path in sorted(OUTPUT_DIR.glob("*.parquet")):
    digest = hashlib.sha256()
    with parquet_path.open("rb") as parquet_file:
        for chunk in iter(lambda: parquet_file.read(1024 * 1024), b""):
            digest.update(chunk)
    file_hashes[parquet_path.name] = digest.hexdigest()

dataset_fingerprint = hashlib.sha256(effective_config_text.encode("utf-8"))
for file_name, file_hash in sorted(file_hashes.items()):
    dataset_fingerprint.update(file_name.encode("utf-8"))
    dataset_fingerprint.update(file_hash.encode("ascii"))
dataset_version = dataset_fingerprint.hexdigest()
table_rows = {
    "catalogos_programas.parquet": len(prog_df),
    "catalogos_sedes.parquet": len(sedes_df),
    "calendario_academico.parquet": len(cal_df),
    "catalogos_asignaturas.parquet": len(asig_df),
    "estudiante_periodo_corte.parquet": len(main_df_clean),
    "target_trazabilidad.parquet": len(target_df),
    "estudiante_asignatura_periodo.parquet": len(asig_det_df),
    "financiera_estudiante_evento.parquet": len(fin_df),
    "bienestar_acompanamiento.parquet": len(bienestar_df),
    "solicitudes_estudiantiles.parquet": len(sol_df),
}
effective_config_path = OUTPUT_DIR / "generator_config.json"
effective_config_path.write_text(
    json.dumps(effective_config, indent=2, ensure_ascii=False), encoding="utf-8"
)
target_class_counts = {
    str(label): int(count)
    for label, count in observed_target_df["target_desercion"].value_counts().items()
}
quality_report = {
    "dataset_version": dataset_version,
    "generator_version": GENERATOR_VERSION,
    "scenario": SCENARIO,
    "students_requested": N_ESTUDIANTES,
    "students_observed": int(main_df_clean["id_estudiante_anon"].nunique()),
    "periods": PERIODOS,
    "snapshot_rows": len(main_df_clean),
    "target_rows": len(target_df),
    "mature_target_rows": len(observed_target_df),
    "immature_target_rows": len(target_df) - len(observed_target_df),
    "target_class_counts_mature_only": target_class_counts,
    "target_dropout_prevalence_mature_only": target_prevalence,
    "table_rows": table_rows,
    "quality_checks": [
        {"check": name, "passed": bool(passed), "details": detail}
        for name, passed, detail in validaciones
    ],
    "note": "Synthetic longitudinal data; not institutional student records.",
}
(OUTPUT_DIR / "data_quality_report.json").write_text(
    json.dumps(quality_report, indent=2, ensure_ascii=False), encoding="utf-8"
)
manifest = {
    **quality_report,
    "created_at_utc": RUN_TIMESTAMP.isoformat(),
    "configuration_file": str(CONFIG_PATH),
    "output_directory": str(OUTPUT_DIR),
    "effective_config": effective_config,
    "parquet_sha256": file_hashes,
}
(OUTPUT_DIR / "dataset_manifest.json").write_text(
    json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
)
print(f" - Dataset version:            {dataset_version}")
print(f" - Manifiesto / calidad:       {OUTPUT_DIR / 'dataset_manifest.json'}")

print("\nResumen del Digital Twin:")
print(f" - Estudiantes unicos:         {main_df_clean['id_estudiante_anon'].nunique():,}")
print(f" - Registros tabla principal:  {len(main_df_clean):,}")
print(f" - Registros target:           {len(target_df):,}")
print(f" - Periodos cubiertos:         {main_df_clean['periodo_id'].nunique()}")
print(f" - Programas cubiertos:        {main_df_clean['programa'].nunique()}")
print(f" - Sedes cubiertas:            {main_df_clean['sede'].nunique()}")
print(f" - Tasa de desercion global:   {tasa_desercion:.1%}")
print(f" - Promedio general:           {main_df_clean['promedio_semestre'].mean():.2f}")
print(f" - Columnas tabla principal:   {len(main_df_clean.columns)}")

print("\nDigital Twin generado exitosamente.")
print(f"Archivos en: {OUTPUT_DIR}")
