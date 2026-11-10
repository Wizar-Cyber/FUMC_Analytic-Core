# 05.01 | Modelo predictivo SAT-FUMC

> **Estado:** Documento fundacional — Versión 1.0  
> **Derivado de:** `definicion_del_proyecto_y_prompt_mejorado.md`, `matriz_de_skills_y_herramientas.md`, `diccionario_datos_SAT_desercion_FUMC.xlsx` (hojas: Clasificacion_Variables, No_Predictoras_Criticas, Guia_Modelado, Matriz_Uso_Modelo)

> Las metas de Recall, precisión, F1, AUC, Brier y fairness de este documento son criterios propuestos; no son métricas demostradas por el despliegue Azure ni resultados aprobados del modelo.

---

## 1. Definición Formal del Problema

**Tipo de tarea:** Clasificación binaria supervisada  
**Variable objetivo:** `target_desercion` ∈ {0, 1}  
**Momento de predicción:** Antes del corte predictivo definido (inicio, semana 2, 4, 8, primer corte)  
**Unidad de predicción:** Estudiante × Periodo × Corte

```
target_desercion = 1 ⟺ 
  matriculado en T 
  AND NOT reinscrito_t1 
  AND NOT reinscrito_t2 
  AND NOT graduado_hasta_t2 
  AND NOT transferencia_interna_hasta_t2 
  AND NOT aplazamiento_formal_hasta_t2
```

---

## 2. Grupos de Features por Prioridad

### 2.1 Grupo A — Features críticas (V1)
*Disponibles desde el inicio del semestre*

| Feature | Descripción | Tipo |
|---|---|---|
| `cohorte_ingreso` | Periodo de primer ingreso | Categórica ordinal |
| `semestres_cursados` | Nº periodos cursados hasta T | Numérica |
| `avance_plan_pct` | % del plan completado | Numérica (0–100) |
| `rezago_academico` | Diferencia avance esperado vs real | Numérica |
| `promedio_semestre_anterior` | Promedio del periodo previo | Numérica (0–5) |
| `historial_prueba_academica` | ¿Ha estado en prueba académica? | Binaria |
| `creditos_inscritos` | Créditos matriculados en T | Numérica |
| `num_materias_perdidas` | Materias reprobadas en periodo previo | Numérica |
| `estrato_socioeconomico` | Estrato 1–6 | Numérica ordinal |
| `trabaja` | ¿El estudiante trabaja? | Binaria |
| `jornada` | Diurna / Nocturna / Mixta | Categórica |
| `modalidad` | Presencial / Virtual / Híbrida | Categórica |
| `sede` | Medellín / Cali / Neiva / Popayán / Virtual | Categórica |
| `programa` | Programa académico | Categórica |
| `tipo_financiacion` | ICETEX / Beca / Propio / Crédito | Categórica |
| `puntaje_matematicas` | Puntaje ICFES matemáticas | Numérica |
| `puntaje_global_prueba_ingreso` | Puntaje global admisión | Numérica |

### 2.2 Grupo B — Señales tempranas (semana 2–4)
*Disponibles solo después del corte correspondiente*

| Feature | Descripción |
|---|---|
| `engagement_lms` | Score compuesto de actividad en LMS (accesos, días activos, tareas) |
| `asistencia_pct_semana4` | % asistencia hasta semana 4 |
| `saldo_mora` | Monto de mora financiera actual |
| `bloqueo_financiero` | ¿Tiene bloqueo activo? |
| `num_solicitudes_radicadas` | Solicitudes a registro académico |
| `tareas_vencidas_semana4` | Tareas no entregadas hasta semana 4 |

### 2.3 Grupo C — Riesgo académico (posterior al primer corte)
*Solo disponibles después del primer corte evaluativo*

| Feature | Descripción |
|---|---|
| `nota_primer_corte_promedio` | Promedio de notas primer corte (todas las asignaturas) |
| `num_cursos_nota_menor_3` | Cursos con nota < 3.0 en primer corte |
| `creditos_en_riesgo` | Créditos de asignaturas con calificación < 3.0 |

### 2.4 Grupo D — Variables derivadas recomendadas

| Feature | Fórmula |
|---|---|
| `tasa_aprobacion` | `creditos_aprobados / creditos_inscritos` |
| `intensidad_perdida` | `num_materias_perdidas / num_materias_inscritas` |
| `indice_riesgo_academico` | `f(promedio, rezago, historial_prueba_academica)` |
| `tendencia_financiera` | `delta(saldo_mora, semestre_anterior)` |
| `participacion_te_quiero_en_la_u` | `asistio_tquieroenlaU (booleano)` |
| `periodo_ordinal_estudiante` | Nº del periodo en la trayectoria del estudiante |
| `antiguedad_institucional_periodos` | Periodos activos desde cohorte_ingreso |

---

## 3. Variables Prohibidas (No Predictoras Críticas)

> ⚠️ Estas variables NUNCA deben entrar como features al modelo de predicción temprana.

| Variable | Razón de exclusión |
|---|---|
| `target_desercion` | Es la variable objetivo |
| `reinscrito_t1` | Información posterior al momento de predicción |
| `reinscrito_t2` | Información posterior al momento de predicción |
| `graduado_hasta_t2` | Información posterior al momento de predicción |
| `fecha_retiro` | Revela el desenlace |
| `motivo_retiro` | Revela el desenlace |
| `causa_no_continuidad_*` | Variables de desenlace |
| `nota_final` (en modelos tempranos) | Solo disponible al cierre |
| `promedio_semestre` (actual) | Solo disponible al cierre del semestre |
| `estado_financiero_cierre` | Estado final posterior al corte |

---

## 4. Transformaciones y Preprocesamiento

```python
# Pipeline scikit-learn
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import StandardScaler, OrdinalEncoder, TargetEncoder
from sklearn.impute import SimpleImputer

# Features numéricas: impute mediana → escalar
numeric_pipeline = Pipeline([
    ('imputer', SimpleImputer(strategy='median')),
    ('scaler', StandardScaler())
])

# Features categóricas con alta cardinalidad (programa, sede): Target Encoding
high_card_pipeline = Pipeline([
    ('imputer', SimpleImputer(strategy='most_frequent')),
    ('encoder', TargetEncoder())
])

# Features categóricas binarias / ordinales (jornada, modalidad, estrato)
low_card_pipeline = Pipeline([
    ('imputer', SimpleImputer(strategy='most_frequent')),
    ('encoder', OrdinalEncoder())
])
```

---

## 5. Métricas de Evaluación

| Métrica | Meta | Justificación |
|---|---|---|
| **Recall** | ≥ 0.80 | Prioridad: no perder desertores reales (costo alto de falso negativo) |
| **F1-Score** | ≥ 0.75 | Balance precisión-recall |
| **AUC-ROC** | ≥ 0.80 | Discriminación global del modelo |
| **Precisión** | ≥ 0.70 | Evitar sobrecarga del equipo de consejería |
| **Brier Score** | ≤ 0.15 | Calibración de probabilidades |
| **Fairness (ΔRecall)** | ≤ 0.10 entre grupos | Equidad entre sedes, programas, géneros |

---

## 6. Manejo del Desbalance de Clases

La documentación preliminar estima ~20–25%, pero el snapshot sintético actual contiene 3.025 positivos de 27.975 registros (10,8%). La proporción debe recalcularse con la definición aprobada del target y datos reales; no asumir la cifra preliminar. Estrategias a evaluar:

1. **class_weight='balanced'** en scikit-learn (primera opción, sin modificar datos).
2. **SMOTE** (Synthetic Minority Oversampling) si class_weight no alcanza el Recall meta.
3. **Umbral de clasificación ajustado:** Mover el threshold de 0.5 hacia abajo (ej: 0.35) para aumentar el Recall.
4. **scale_pos_weight** en XGBoost: `n_negativos / n_positivos`.

---

## 7. Output del Modelo

Cada estudiante activo recibe en cada corte:

```json
{
  "id_estudiante_anon": "7f6d2c8a-001",
  "periodo_id": "2025-1",
  "tipo_corte_predictivo": "SEMANA_4",
  "probabilidad_desercion": 0.73,
  "nivel_riesgo": "Alto",
  "top_factores_riesgo": [
    {"factor": "saldo_mora", "shap_valor": 0.21, "descripcion": "Mora financiera activa"},
    {"factor": "engagement_lms", "shap_valor": -0.18, "descripcion": "Baja actividad en plataforma virtual"},
    {"factor": "tareas_vencidas_semana4", "shap_valor": 0.14, "descripcion": "4 tareas no entregadas"},
    {"factor": "promedio_semestre_anterior", "shap_valor": -0.12, "descripcion": "Promedio previo: 2.8"},
    {"factor": "participacion_te_quiero_en_la_u", "shap_valor": -0.09, "descripcion": "No ha asistido a sesiones de apoyo"}
  ],
  "intervencion_sugerida": "Priorizar contacto de Apoyo Socioeconómico y agendar sesión de tutorías académicas en 'Te quiero en la U'"
}
```

---

## 8. Criterios de Decisión Operativa por Nivel de Riesgo

| Nivel | Probabilidad | Acción recomendada | Urgencia |
|---|---|---|---|
| **Bajo** | 0–30% | Seguimiento rutinario | Próxima semana |
| **Medio** | 30–60% | Contacto preventivo del consejero | Esta semana |
| **Alto** | 60–80% | Intervención directa + plan de acción | 48 horas |
| **Crítico** | >80% | Intervención inmediata + escalamiento a coordinación | Hoy |
