# DataArchitecture.md — Arquitectura de Datos SAT-FUMC

> **Estado:** Documento fundacional — Versión 1.0  
> **Derivado de:** `diccionario_datos_SAT_desercion_FUMC.xlsx` (hojas: Tablas, Diccionario_Datos, Reglas_Calidad, Definicion_Target, Guia_Modelado)

---

## 1. Principio Rector de Datos

> *"Solicitar datos amplios, pero entrenar modelos únicamente con variables disponibles antes de cada corte predictivo."*  
> — Diccionario de Datos SAT-FUMC

La arquitectura de datos está diseñada en torno a **snapshots estudiante-periodo-corte**: cada fila representa lo que se sabía de un estudiante en un momento preciso del semestre, sin ninguna información posterior a ese corte.

---

## 2. Tablas del Modelo de Datos

### 2.1 Tabla Principal: `estudiante_periodo_corte`
**Unidad de análisis:** Una fila por `(id_estudiante_anon, periodo_id, tipo_corte_predictivo)`

| Grupo de Variables | Ejemplos de campos |
|---|---|
| Identificación y temporalidad | `id_estudiante_anon`, `cohorte_ingreso`, `periodo_id`, `anio`, `semestre`, `tipo_corte_predictivo`, `fecha_corte_predictiva` |
| Admisión e ingreso | `puntaje_admision`, `puntaje_global_prueba_ingreso`, `puntaje_matematicas`, `tipo_ingreso`, `modalidad_admision` |
| Académicas | `promedio_semestre`, `promedio_semestre_anterior`, `creditos_inscritos`, `creditos_aprobados`, `creditos_reprobados`, `num_materias_inscritas`, `num_materias_perdidas`, `num_materias_canceladas`, `semestres_cursados`, `avance_plan_pct`, `rezago_academico`, `historial_prueba_academica` |
| Académicas históricas | `promedio_acumulado_hist`, `mejor_promedio_hist`, `peor_promedio_hist`, `tendencia_promedio` |
| LMS / analítica de aprendizaje | `accesos_lms_semana`, `dias_activos_lms`, `tareas_vencidas`, `foros_participacion`, `ultima_actividad_lms` |
| Financieras y administrativas | `tipo_financiacion`, `monto_matricula`, `saldo_mora`, `tiene_beca`, `tipo_beca`, `bloqueo_financiero` |
| Socidemográficas y contexto | `genero`, `edad`, `estrato_socioeconomico`, `municipio_residencia`, `trabaja`, `jefe_hogar`, `discapacidad` |
| Bienestar y acompañamiento | `asistio_tquieroenlaU`, `num_sesiones_bienestar`, `tipo_apoyo_bienestar`, `intensidad_apoyo` |
| Solicitudes y trámites | `num_solicitudes_radicadas`, `tipos_solicitudes`, `solicitud_aplazamiento` |
| Variables derivadas | `tasa_aprobacion`, `intensidad_perdida`, `indice_riesgo_academico`, `tendencia_financiera`, `engagement_lms` |
| Programa y sede | `programa`, `codigo_programa`, `sede`, `jornada`, `modalidad`, `facultad` |

### 2.2 Tabla Anexa: `estudiante_asignatura_periodo`
**Unidad de análisis:** Una fila por `(id_estudiante_anon, asignatura_id, periodo_id)`

Campos: `asignatura_id`, `nombre_asignatura`, `area_conocimiento`, `tipo_asignatura`, `creditos_asignatura`, `nota_primer_corte`, `nota_segundo_corte`, `nota_final` (solo análisis retrospectivo), `asistencia_pct`, `cancelada`, `resultado`.

### 2.3 Tabla LMS: `lms_estudiante_curso_semana`
**Unidad de análisis:** Una fila por `(id_estudiante_anon, curso_id, semana)`

Campos: `accesos_semana`, `dias_activos`, `tareas_vencidas`, `entregas_realizadas`, `foros_vistos`, `foros_participados`, `evaluaciones_completadas`, `ultima_actividad`.

### 2.4 Tabla Financiera: `financiera_estudiante_evento`
**Unidad de análisis:** Una fila por `(id_estudiante_anon, evento_financiero_id)`

Campos: `tipo_evento` (liquidación, pago, beca, mora, bloqueo), `fecha_evento`, `monto`, `saldo_pendiente`, `tipo_financiacion`, `tiene_beca`.

### 2.5 Tabla Bienestar: `bienestar_acompanamiento`
**Unidad de análisis:** Una fila por `(id_estudiante_anon, periodo_id, tipo_acompanamiento)`

Campos: `tipo_apoyo`, `fecha_sesion`, `asistio`, `canal`, `intensidad_sesiones`, `estado_seguimiento`. *(Sin diagnósticos ni notas clínicas.)*

### 2.6 Tabla Target: `target_trazabilidad`
**Unidad de análisis:** Una fila por `(id_estudiante_anon, periodo_id)`

Campos: `reinscrito_t1`, `reinscrito_t2`, `graduado_hasta_t2`, `transferencia_interna_hasta_t2`, `aplazamiento_formal_hasta_t2`, **`target_desercion`**.

> ⚠️ **CRÍTICO:** Esta tabla NUNCA se mezcla con la tabla de predictores en el entrenamiento.

### 2.7 Catálogos y Calendarios
- `catalogos_maestros`: programas, sedes, jornadas, modalidades, tipos de beca, financiación.
- `calendario_academico_financiero`: fechas de inicio/fin, cortes evaluativos, fechas límite de pago.
- `perfilamiento_calidad_datos`: metadatos de cada variable (cobertura, faltantes, cambios de definición).

---

## 3. Definición del Target

```
target_desercion = 1 
  SI: matriculado en T 
  Y NO: reinscrito en T+1 ni T+2
  Y NO: graduado entre T y T+2
  Y NO: transferencia interna formal entre T y T+2
  Y NO: aplazamiento aprobado entre T y T+2
  = 0 en caso contrario
```

---

## 4. Cortes Predictivos

| Corte | Momento | Variables disponibles | Uso operativo |
|---|---|---|---|
| `INICIO` | Inicio del semestre | Historial + matrícula + trayectoria + sociodemografía | Priorización preventiva |
| `SEMANA_2` | Semana 2 | + LMS semana 2, pago inicial, asistencia inicial | Alertas de desconexión |
| `SEMANA_4` | Semana 4 | + LMS sem 4, asistencia sem 4, mora, solicitudes | Alerta temprana operativa principal |
| `PRIMER_CORTE` | Después del 1er corte | + Notas primer corte, cursos en riesgo | Riesgo académico-financiero |
| `SEMANA_8` | Semana 8 | + Todo acumulado hasta sem 8 | Seguimiento intermedio |
| `CIERRE` | Fin de semestre | Datos finales completos | Solo análisis retrospectivo |

---

## 5. Flujo de Datos

```
[Digital Twin / Fuentes Reales]
        ↓
[ETL / Ingesta] → estudiante_periodo_corte (por corte)
        ↓                ↓
[Validación Calidad]   [target_trazabilidad] (separado)
        ↓
[Feature Engineering] → features_modelo_vXX.parquet
        ↓
[Entrenamiento / Predicción]
        ↓
[Predicciones: probabilidad_desercion, nivel_riesgo, shap_values]
        ↓
[predicciones_estudiante_periodo.parquet / .csv]
        ↓
[Power BI Dashboard]
```

---

## 6. Reglas de Calidad Obligatorias

| Regla | Severidad |
|---|---|
| PK única: `id_estudiante_anon + periodo_id` en tabla principal | Crítica |
| Todas las sedes cubiertas; `sede` no nula | Crítica |
| Variable de target separada de predictores | Crítica |
| Toda variable predictor observable antes del corte | Crítica |
| Promedios entre 0–5; porcentajes 0–100; créditos ≥ 0 | Alta |
| `creditos_aprobados + creditos_reprobados ≤ creditos_inscritos` | Media |
| Catálogos normalizados (programa, modalidad, jornada, sede) | Alta |
| Versionado del dataset con fecha y reglas ETL | Media |

---

## 7. Total de Variables Documentadas

| Fase | Cantidad | Prioridad Alta | Prioridad Media | Prioridad Baja |
|---|---|---|---|---|
| V1 (Core) | 58 | — | — | — |
| V2 (Extendido) | 205 | — | — | — |
| V3 (Avanzado) | 74 | — | — | — |
| **Total** | **337** | **122** | **163** | **52** |

Los grupos de variables son: Identificación/temporalidad (30), Admisión (16), Académicas (47), Académicas históricas (16), Detalle asignatura (21), Sociodemográficas (25), Financieras (39), LMS (44), Bienestar (26), Target/trazabilidad (36), Egreso (7), Institucionales (8), Derivadas (22).
