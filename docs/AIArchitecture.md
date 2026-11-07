# AIArchitecture.md — Arquitectura de IA y ML del SAT-FUMC

> **Estado:** Documento fundacional — Versión 1.0

---

## 1. Visión General de la Arquitectura

```
┌─────────────────────────────────────────────────────────────────┐
│                     CAPA DE DATOS                               │
│  Digital Twin FUMC / Fuentes Reales → Parquet (por corte)       │
└─────────────────────────────┬───────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│               CAPA DE PROCESAMIENTO MULTI-AGENTE                │
│  Coordinador → Ingestor → Calidad → Feature Eng → Entrenador    │
│                              ↓                                  │
│              Evaluador → Explicabilidad → Predictivo            │
│                              ↓                                  │
│                         Monitoreo                               │
└─────────────────────────────┬───────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                  CAPA DE PREDICCIONES                           │
│  predicciones_estudiante_periodo_corte.parquet                  │
│  (probabilidad, nivel_riesgo, factores, intervención)           │
└─────────────────────────────┬───────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                 CAPA DE VISUALIZACIÓN                           │
│                Power BI Dashboard                               │
│  Vista ejecutiva / Vista programa / Vista estudiante            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Pipeline de Machine Learning

### 2.1 Etapas del Pipeline

```
[Raw Features] → [Preprocesamiento] → [Feature Selection] → [Entrenamiento]
                                                                    ↓
[Explicación SHAP/LIME] ← [Modelo Campeón] ← [Evaluación + Fairness]
        ↓
[Predicciones + Recomendaciones] → [Export Parquet/CSV] → [Power BI]
```

### 2.2 Modelos Candidatos

| Modelo | Librería | Ventaja principal |
|---|---|---|
| XGBoost | `xgboost` | Alto rendimiento, maneja desbalance, nativo SHAP |
| LightGBM | `lightgbm` | Velocidad, variables categóricas nativas |
| CatBoost | `catboost` | Óptimo con variables categóricas de alta cardinalidad |
| Random Forest | `scikit-learn` | Interpretable, robusto a ruido |
| Red Neuronal (MLP) | `scikit-learn` / `pytorch` | Captura relaciones no lineales complejas |

### 2.3 Criterio de Selección del Modelo Campeón

Prioridad de métricas (en orden):
1. **Recall** ≥ 0.80 (minimizar falsos negativos: no perder desertores reales)
2. **F1-Score** ≥ 0.75 (balance precisión-recall)
3. **AUC-ROC** ≥ 0.80
4. **Fairness** (brecha de Recall entre grupos ≤ 0.10)
5. Tiempo de predicción < 5 min para 100K registros

### 2.4 Validación Temporal

```python
# Validación por cohorte (NO aleatoria)
# Entrenamiento: cohortes 2021-1 → 2024-1
# Prueba: cohorte 2024-2 → 2025-2
# Validación cruzada: TimeSeriesSplit con n_splits=5
```

> **Razón:** Una partición aleatoria genera resultados inflados porque permite que el modelo "vea el futuro" de estudiantes de la misma cohorte que están en test. La validación temporal simula el escenario real de producción.

---

## 3. Estrategia de Explicabilidad

### 3.1 SHAP (SHapley Additive exPlanations)
- **Global:** Importancia media de cada feature en todo el dataset.
- **Local (por estudiante):** Contribución de cada variable a la predicción individual.
- Visualización: Waterfall charts por estudiante → Power BI.

### 3.2 LIME (Local Interpretable Model-agnostic Explanations)
- Usado como validación cruzada de las explicaciones SHAP.
- Especialmente útil para las Redes Neuronales.

### 3.3 Output de Explicabilidad para Power BI

```
predicciones_estudiante_periodo_corte.parquet
├── id_estudiante_anon
├── periodo_id
├── tipo_corte_predictivo
├── probabilidad_desercion         (float: 0.0–1.0)
├── nivel_riesgo                   (Bajo/Medio/Alto/Crítico)
├── factor_riesgo_1_nombre
├── factor_riesgo_1_shap_valor
├── factor_riesgo_2_nombre
├── factor_riesgo_2_shap_valor
├── factor_riesgo_3_nombre
├── factor_riesgo_3_shap_valor
├── factor_riesgo_4_nombre
├── factor_riesgo_4_shap_valor
├── factor_riesgo_5_nombre
├── factor_riesgo_5_shap_valor
└── intervencion_sugerida          (texto: acción "Te quiero en la U")
```

---

## 4. MLOps: Gestión del Ciclo de Vida

### 4.1 Componentes MLOps

| Componente | Herramienta | Responsable |
|---|---|---|
| Tracking de experimentos | MLflow | Agente Entrenador |
| Versionado de modelos | MLflow Model Registry | Agente Evaluador |
| Versionado de datasets | Naming convention + hash | Agente Ingestor |
| Monitoreo de drift | Evidently AI | Agente Monitor |
| Re-entrenamiento | Trigger automático | Agente Coordinador |
| Serialización de modelos | joblib / ONNX | Agente Entrenador |

### 4.2 Convención de Nombres

```
# Modelos
model_xgboost_v{version}_corte_{tipo}_periodo_{YYYY_S}.joblib

# Datasets
features_{tipo_corte}_{YYYY_S}_v{version}.parquet
predictions_{tipo_corte}_{YYYY_S}_v{version}.parquet

# Experimentos MLflow
experiment: "SAT_FUMC_{programa}_{corte}"
run_name: "{modelo}_{fecha}"
```

### 4.3 Frecuencia de Re-entrenamiento

| Trigger | Acción |
|---|---|
| Inicio de cada semestre | Re-entrenamiento completo con nuevos datos |
| Drift detectado (KS test p < 0.05 en > 20% features) | Alerta al Coordinador + re-entrenamiento |
| Degradación F1 > 10% vs baseline | Re-entrenamiento urgente |
| Solicitud manual del equipo de datos | Re-entrenamiento bajo demanda |

---

## 5. Diseño de Dashboards Power BI

### Vista 1: Ejecutiva (Decanos / Vicerrectoría)
- **KPIs:** Nº estudiantes en riesgo alto/crítico, tasa de riesgo general, evolución semestral.
- **Gráficos:** Mapa de calor de riesgo por sede + programa, tendencia temporal.
- **Filtros:** Sede, Facultad, Programa, Semestre, Corte predictivo.

### Vista 2: Por Programa / Facultad (Coordinadores)
- **KPIs:** % estudiantes por nivel de riesgo, factor de riesgo más frecuente.
- **Gráficos:** Distribución de probabilidades, top 10 factores de riesgo del programa.
- **Lista:** Estudiantes ordenados por probabilidad de deserción (anonimizados en vista pública).

### Vista 3: Perfil Individual del Estudiante (Consejeros)
- **Probabilidad:** Gauge chart 0–100%.
- **Nivel de riesgo:** Semáforo (Verde/Amarillo/Naranja/Rojo).
- **Factores:** Waterfall chart con top 5 factores SHAP.
- **Intervención sugerida:** Texto con la acción recomendada del programa "Te quiero en la U".
- **Histórico:** Evolución de probabilidad de deserción a lo largo de los semestres.

### Vista 4: Monitoreo del Modelo (Equipo de Datos)
- Estado del modelo (versión, fecha último entrenamiento, métricas actuales).
- Alertas de drift.
- Distribución de predicciones en el tiempo.

---

## 6. Stack Tecnológico Consolidado

| Capa | Tecnología |
|---|---|
| **Generación datos** | Python, Pandas, NumPy, Faker, PyArrow |
| **Formato de datos** | Apache Parquet |
| **Agentes / Orquestación** | LangChain / CrewAI |
| **ML** | scikit-learn, XGBoost, LightGBM, CatBoost |
| **Hiperparámetros** | Optuna |
| **Explicabilidad** | SHAP, LIME |
| **Fairness** | Fairlearn |
| **MLOps** | MLflow |
| **Monitoreo drift** | Evidently AI |
| **Visualización** | Power BI Desktop |
| **Almacenamiento** | Sistema de archivos local → (Fase 5: GCS / Azure Blob) |
