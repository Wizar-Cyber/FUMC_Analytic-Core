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
  - estudiante_periodo_corte.parquet      (~150K filas)
  - estudiante_asignatura_periodo.parquet (~900K filas)
  - lms_estudiante_curso_semana.parquet   (~2M filas)
  - financiera_estudiante_evento.parquet  (~200K filas)
  - bienestar_acompanamiento.parquet      (~80K filas)
  - solicitudes_estudiantiles.parquet     (~50K filas)
  - target_trazabilidad.parquet           (~150K filas — SEPARADO)
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
from datetime import date, timedelta, datetime
from pathlib import Path

# ─── Reproducibilidad ─────────────────────────────────────────────────────────
RNG = np.random.default_rng(seed=42)
OUTPUT_DIR = Path(
    os.environ.get(
        "SAT_OUTPUT_DIR",
        str(Path(__file__).parent.parent.parent / "data" / "raw"),
    )
).expanduser()
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

PERIODOS = [f"{anio}-{sem}" for anio in range(2021, 2026) for sem in [1, 2]]
# 2021-1, 2021-2, ..., 2025-2  → 10 periodos

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

N_ESTUDIANTES = int(os.environ.get("SAT_SYNTHETIC_STUDENTS", "6000"))
if N_ESTUDIANTES < 1:
    raise ValueError("SAT_SYNTHETIC_STUDENTS debe ser mayor que cero.")
MAX_FILAS_ESTUDIANTE_PERIODO = 35_000
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
    cohorte_idx = int(RNG.integers(0, min(8, n_periodos_disponibles)))
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
        tiene_mora = bool(RNG.random() < (0.35 if est["estrato_socioeconomico"] <= 2 else 0.15))
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
        accesos_sem_lms = int(_clamp(RNG.normal(45 if not es_virtual else 80, 20), 0, 150))
        dias_activos = int(_clamp(RNG.normal(28, 8), 0, 60))
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

        # Cap el riesgo
        prob_desercion = _clamp(risk, 0.01, 0.95)
        deserta = bool(RNG.random() < prob_desercion)

        # Nivel de riesgo
        if prob_desercion < 0.30:    nivel_riesgo = "Bajo"
        elif prob_desercion < 0.60:  nivel_riesgo = "Medio"
        elif prob_desercion < 0.80:  nivel_riesgo = "Alto"
        else:                        nivel_riesgo = "Crítico"

        # ── Variables derivadas adicionales ───────────────────────────────
        tasa_aprobacion_calc = round(cred_aprobados / max(creditos_sem, 1), 3)
        intensidad_perdida   = round(num_perdidas / max(num_mat, 1), 3)
        indice_riesgo_academico = round(
            (1 - tasa_aprobacion_calc) * 0.5 +
            (max(0, 3.0 - prom_sem) / 3.0) * 0.3 +
            (1 if historial_prueba else 0) * 0.2, 3
        )

        # ── Fila tabla principal ──────────────────────────────────────────
        row = {
            # Identificación y temporalidad
            "id_estudiante_anon":        est["id_estudiante_anon"],
            "cohorte_ingreso":           est["cohorte_ingreso"],
            "anio":                      anio,
            "semestre":                  sem,
            "periodo_id":                periodo_id,
            "periodo_ordinal_estudiante": period_ord,
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
            # Riesgo (para diagnóstico del Digital Twin — NO es el target)
            "probabilidad_riesgo_simulada": round(prob_desercion, 4),
            "nivel_riesgo_simulado":     nivel_riesgo,
            # Estado (para construir target, no para predecir)
            "_estado_semestre":          "Desertor" if deserta else "Activo",
        }
        main_rows.append(row)

        # Target por periodo observado
        target_row = {
            "id_estudiante_anon": est["id_estudiante_anon"],
            "periodo_id": periodo_id,
            "reinscrito_t1": 0,
            "reinscrito_t2": 0,
            "graduado_hasta_t2": 0,
            "transferencia_interna_hasta_t2": 0,
            "aplazamiento_formal_hasta_t2": 0,
            "target_desercion": 0,
        }
        if deserta:
            estado_actual = "Desertor"
            target_row["target_desercion"] = 1
            target_row["aplazamiento_formal_hasta_t2"] = int(RNG.random() < 0.08)
            target_rows.append(target_row)
            break
        else:
            if creditos_acum >= total_creditos_plan * 0.95 and semestres_curs >= semestres_plan - 1:
                if bool(RNG.random() < 0.70):
                    estado_actual = "Graduado"
                    target_row["graduado_hasta_t2"] = 1
                    target_rows.append(target_row)
                    break
                else:
                    target_rows.append(target_row)
            else:
                target_row["reinscrito_t1"] = 1 if periodo_siguiente_id else 0
                target_row["reinscrito_t2"] = 1 if periodo_siguiente2_id else 0
                target_row["transferencia_interna_hasta_t2"] = int(RNG.random() < 0.01)
                target_row["aplazamiento_formal_hasta_t2"] = int(RNG.random() < 0.03)
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
# Eliminar columna auxiliar _estado_semestre del output principal
main_df_clean = main_df.drop(columns=["_estado_semestre"])
main_df_clean.to_parquet(OUTPUT_DIR / "estudiante_periodo_corte.parquet", index=False)
print(f"   Guardado: estudiante_periodo_corte.parquet ({len(main_df_clean):,} filas x {len(main_df_clean.columns)} cols)")

print("\n[5/10] Guardando target_trazabilidad (tabla SEPARADA)...")
target_df = pd.DataFrame(target_rows)
target_df.to_parquet(OUTPUT_DIR / "target_trazabilidad.parquet", index=False)
n_desertores = target_df["target_desercion"].sum()
print(f"   Guardado: target_trazabilidad.parquet ({len(target_df):,} filas)")
print(f"   Desertores (target=1): {n_desertores:,} ({n_desertores/len(target_df)*100:.1f}%)")
print(f"   No desertores (target=0): {len(target_df)-n_desertores:,} ({(len(target_df)-n_desertores)/len(target_df)*100:.1f}%)")

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
asig_rows_det = []
for row in main_rows[:]:
    prog_asigs = asig_df[asig_df["programa"] == row["programa"]]
    sem_asigs  = prog_asigs[prog_asigs["semestre_del_plan"] == min(row["semestres_cursados"], 10)]
    if len(sem_asigs) == 0:
        sem_asigs = prog_asigs.sample(n=min(5, len(prog_asigs)), random_state=0)
    n_asig_sem = min(row["num_materias_inscritas"], len(sem_asigs))
    sel_asigs  = sem_asigs.sample(n=n_asig_sem, random_state=42).reset_index(drop=True)
    for _, asig in sel_asigs.iterrows():
        nota_1er = round(float(RNG.normal(row["promedio_semestre"] + 0.1, 0.4)), 1)
        nota_1er = _clamp(nota_1er, 0.0, 5.0)
        nota_2do = round(float(RNG.normal(row["promedio_semestre"], 0.4)), 1)
        nota_2do = _clamp(nota_2do, 0.0, 5.0)
        asistencia = round(float(RNG.beta(8, 2) if row["promedio_semestre"] >= 3.0 else RNG.beta(3, 3)), 2) * 100
        cancelada = int(nota_1er < 2.0 and RNG.random() < 0.25)
        asig_rows_det.append({
            "id_estudiante_anon": row["id_estudiante_anon"],
            "periodo_id":         row["periodo_id"],
            "asignatura_id":      asig["asignatura_id"],
            "creditos_asignatura":asig["creditos"],
            "nota_primer_corte":  nota_1er,
            "nota_segundo_corte": nota_2do,
            "asistencia_pct":     round(asistencia, 1),
            "cancelada":          cancelada,
            "resultado":          "Aprobada" if nota_2do >= 3.0 and not cancelada else ("Cancelada" if cancelada else "Reprobada"),
        })

asig_det_df = pd.DataFrame(asig_rows_det)
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

# Tasa deserción
tasa_desercion = target_df["target_desercion"].mean()
tasa_ok = 0.05 <= tasa_desercion <= 0.20
validaciones.append(("Tasa desercion plausible (5-20%)", tasa_ok, f"Tasa: {tasa_desercion:.1%}"))

# Target separado de predictores
target_en_main = "target_desercion" in main_df_clean.columns
validaciones.append(("Target NO esta en tabla predictores", not target_en_main, ""))

print("\n--- REPORTE DE VALIDACION DIGITAL TWIN ---")
for nombre, ok, detalle in validaciones:
    status = "[OK]" if ok else "[FAIL]"
    print(f" {status} {nombre:<45} {detalle}")

if not all(ok for _, ok, _ in validaciones):
    raise RuntimeError("Fallaron una o más validaciones del Digital Twin.")

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
