# AgentsDefinition.md — Arquitectura Multi-Agente SAT-FUMC

> **Estado:** Documento fundacional — Versión 1.0  
> **Derivado de:** `definicion_del_proyecto_y_prompt_mejorado.md`, `matriz_de_skills_y_herramientas.md`, `diccionario_datos_SAT_desercion_FUMC.xlsx` (hoja: Guia_Modelado)

---

## 1. Visión de la Arquitectura

El sistema SAT-FUMC opera como una **red de agentes especializados** orquestada por un Agente Coordinador. Cada agente tiene una responsabilidad única, inputs y outputs bien definidos, y métricas de desempeño propias. La arquitectura evita el acoplamiento directo entre agentes y privilegia la comunicación a través de artefactos (archivos Parquet) y mensajes estructurados.

```
                      ┌─────────────────────┐
                      │  Agente Coordinador │
                      └──────────┬──────────┘
           ┌──────────────────────┼──────────────────────┐
           ↓                      ↓                      ↓
  ┌──────────────┐     ┌──────────────────┐    ┌────────────────┐
  │ Ag. Ingesta  │     │ Ag. Calidad Datos│    │ Ag. Monitoreo  │
  └──────┬───────┘     └────────┬─────────┘    └───────┬────────┘
         ↓                      ↓                      │
  ┌──────────────────────────────────────┐             │
  │      Ag. Feature Engineer            │             │
  └──────────────────┬───────────────────┘             │
                     ↓                                 │
         ┌───────────────────────┐                     │
         │    Ag. Entrenamiento  │                     │
         └───────────┬───────────┘                     │
                     ↓                                 │
         ┌───────────────────────┐                     │
         │    Ag. Evaluación     │◄────────────────────┘
         └───────────┬───────────┘
                     ↓
         ┌───────────────────────┐
         │  Ag. Explicabilidad   │
         └───────────┬───────────┘
                     ↓
         ┌───────────────────────┐
         │    Ag. Predictivo     │
         └───────────────────────┘
```

---

## 2. Definición de cada Agente

---

### AGENTE 1: Coordinador (Orchestrator Agent)

**Objetivo:** Orquestar el flujo completo del pipeline, gestionar dependencias entre agentes, registrar el estado de cada ejecución y activar re-entrenamientos cuando el Agente de Monitoreo lo detecte.

| Atributo | Detalle |
|---|---|
| **Framework** | LangChain / CrewAI |
| **Rol** | Manager / Planner |
| **Inputs** | Configuración de corte (fecha, tipo), parámetros de ejecución |
| **Outputs** | Reporte de ejecución, log de errores, trigger a agentes downstream |
| **Skills** | `orchestrate_pipeline()`, `handle_agent_failure()`, `log_execution_state()`, `schedule_retraining()` |
| **Herramientas** | Scheduler (cron / Airflow), sistema de mensajes entre agentes |
| **Dependencias** | Todos los demás agentes |
| **Métricas** | Tasa de ejecuciones exitosas, tiempo total de pipeline, tasa de re-intentos |

---

### AGENTE 2: Ingestor (Data Ingestion Agent)

**Objetivo:** Leer los archivos `.parquet` del Digital Twin (o fuentes reales), validar que la cobertura de sedes y periodos sea completa, y entregar los datos al Agente de Calidad.

| Atributo | Detalle |
|---|---|
| **Inputs** | Path de archivos Parquet, configuración de periodo y corte |
| **Outputs** | DataFrame crudo validado en memoria / archivo staging |
| **Skills** | `read_parquet_files(path, corte)`, `validate_sede_coverage()`, `validate_pk_uniqueness()`, `load_catalogos_maestros()` |
| **Herramientas** | `pandas`, `pyarrow`, `fastparquet` |
| **Dependencias** | Digital Twin / fuentes de datos |
| **Restricciones** | Verifica que `periodo_id` y `tipo_corte_predictivo` están presentes; rechaza datasets sin cobertura completa de sedes |
| **Métricas** | Registros ingresados, % sedes cubiertas, registros rechazados, tiempo de ingesta |

---

### AGENTE 3: Calidad de Datos (Data Quality Agent)

**Objetivo:** Aplicar las reglas de calidad del `diccionario_datos_SAT_desercion_FUMC.xlsx` (hoja Reglas_Calidad) a cada dataset ingerido y generar un reporte de calidad antes de cualquier procesamiento ML.

| Atributo | Detalle |
|---|---|
| **Inputs** | DataFrame del Agente Ingestor |
| **Outputs** | DataFrame limpio + Reporte de calidad (JSON/Parquet) + flags de faltantes |
| **Skills** | `check_range_constraints()`, `check_temporal_consistency()`, `check_catalog_normalization()`, `flag_missing_values()`, `detect_data_leakage_vars()`, `impute_missing_values(strategy='by_facultad')` |
| **Herramientas** | `pandas`, `great_expectations` (opcional), reglas del diccionario |
| **Dependencias** | Agente Ingestor, `catalogos_maestros` |
| **Restricciones** | NUNCA imputa ni modifica variables de trazabilidad/target |
| **Métricas** | Nº reglas violadas por severidad, % faltantes por variable, cobertura histórica |

---

### AGENTE 4: Ingeniero de Características (Feature Engineering Agent)

**Objetivo:** Transformar los datos validados en features listos para el modelo, creando variables derivadas definidas en el diccionario (grupo "Variables derivadas recomendadas") y codificando variables categóricas.

| Atributo | Detalle |
|---|---|
| **Inputs** | DataFrame limpio del Agente Calidad + catálogos |
| **Outputs** | `features_modelo_vXX_corte_YY.parquet` (predictores) + `target_trazabilidad.parquet` (separado) |
| **Skills** | `encode_categorical_data(data, strategy='target_encoding')`, `calculate_risk_index(grades, attendance)`, `compute_lag_features(variable, periods=1)`, `calculate_lms_engagement_score()`, `compute_financial_risk_score()`, `derive_academic_progress_ratio()`, `separate_target_from_predictors()` |
| **Herramientas** | `pandas`, `scikit-learn` (encoders, scalers), `feature-engine` |
| **Dependencias** | Agente Calidad, `Guia_Modelado` del diccionario |
| **Restricciones críticas** | Variables prohibidas del Excel (`fecha_retiro`, `motivo_retiro`, `reinscrito_t1`, `reinscrito_t2`, `graduado_hasta_t2`) nunca entran al DataFrame de predictores |
| **Métricas** | Nº features generadas, cobertura de nulls en features finales, correlación con target (diagnóstico) |

**Variables derivadas clave:**
- `tasa_aprobacion = creditos_aprobados / creditos_inscritos`
- `intensidad_perdida = num_materias_perdidas / num_materias_inscritas`
- `indice_riesgo_academico = f(promedio, rezago, historial_prueba_academica)`
- `engagement_lms = f(accesos, dias_activos, tareas_vencidas)`
- `tendencia_financiera = delta(saldo_mora, semestre_anterior)`
- `participacion_te_quiero_en_la_u = asistio_tquieroenlaU (booleano)`

---

### AGENTE 5: Entrenador (Model Training Agent)

**Objetivo:** Entrenar múltiples modelos de clasificación binaria sobre los features generados, con validación temporal (por cohorte), optimización de hiperparámetros y registro de experimentos.

| Atributo | Detalle |
|---|---|
| **Inputs** | `features_modelo_vXX_corte_YY.parquet` + `target_trazabilidad.parquet` |
| **Outputs** | Modelos serializados (`.joblib`/`.pkl`), métricas por modelo, mejores hiperparámetros |
| **Skills** | `train_xgboost_model(X, y)`, `train_lightgbm_model(X, y)`, `train_catboost_model(X, y)`, `train_random_forest(X, y)`, `train_neural_network(X, y)`, `hyperparameter_tuning(model, strategy='optuna')`, `temporal_cross_validation(data, n_folds=5)` |
| **Herramientas** | `scikit-learn`, `xgboost`, `lightgbm`, `catboost`, `optuna`, `mlflow` |
| **Dependencias** | Agente Feature Engineer |
| **Restricciones** | Usar validación temporal (por cohorte), no aleatoria, para evitar resultados inflados |
| **Métricas propias** | F1-Score ≥ 0.75, Recall ≥ 0.80, AUC-ROC, tiempo de entrenamiento |

---

### AGENTE 6: Evaluador (Model Evaluation Agent)

**Objetivo:** Comparar todos los modelos entrenados, seleccionar el campeón, evaluar fairness por subgrupos (sede, programa, género, estrato) y generar el reporte de evaluación.

| Atributo | Detalle |
|---|---|
| **Inputs** | Modelos del Agente Entrenador + conjunto de prueba |
| **Outputs** | Modelo campeón seleccionado, reporte de evaluación (JSON/Parquet), métricas de fairness |
| **Skills** | `compare_models_by_f1_recall()`, `evaluate_fairness_by_subgroup(groups=['sede','programa','genero','estrato'])`, `generate_confusion_matrix()`, `compute_calibration_curve()`, `select_champion_model()` |
| **Herramientas** | `scikit-learn`, `fairlearn`, `mlflow` |
| **Dependencias** | Agente Entrenador |
| **Restricciones** | Documentar decisiones de selección y trade-offs explícitamente |
| **Métricas** | Métricas por modelo y subgrupo, brecha de equidad entre grupos |

---

### AGENTE 7: Explicabilidad (Explainability Agent)

**Objetivo:** Generar explicaciones individuales y globales de las predicciones del modelo campeón, usando SHAP y LIME, para habilitar la intervención personalizada del programa "Te quiero en la U".

| Atributo | Detalle |
|---|---|
| **Inputs** | Modelo campeón + features de predicción por estudiante |
| **Outputs** | `shap_values_estudiante_periodo.parquet`, recomendaciones de intervención por estudiante |
| **Skills** | `generate_shap_values(model, X)`, `generate_lime_explanation(model, X, instance)`, `identify_top_risk_factors(shap_values, top_n=5)`, `suggest_intervention(risk_factors, programa_tquieroenlaU=True)`, `generate_waterfall_chart_data()` |
| **Herramientas** | `shap`, `lime`, `pandas` |
| **Dependencias** | Agente Evaluador |
| **Métricas** | Cobertura de explicaciones (% estudiantes con SHAP generado), coherencia de ranking de factores |

**Intervenciones del programa "Te quiero en la U" mapeadas:**
| Factor de riesgo | Intervención sugerida |
|---|---|
| Bajo promedio + rezago académico | Talleres de nivelación (Apoyo Psicoeducativo) |
| Alta mora financiera | Identificación de riesgo financiero (Apoyo Socioeconómico) |
| Baja participación LMS | Fase de Acogida / orientación profesional |
| Alta ausencia a sesiones de bienestar | Psicoorientación y asesoría espiritual |
| Primer semestre + bajo puntaje admisión | Valoración estilos de aprendizaje (Fase Acogida) |

---

### AGENTE 8: Predictivo (Prediction Agent)

**Objetivo:** Ejecutar predicciones en producción para todos los estudiantes activos en cada corte, generar la tabla de predicciones lista para Power BI y activar alertas.

| Atributo | Detalle |
|---|---|
| **Inputs** | Modelo campeón + features del corte actual |
| **Outputs** | `predicciones_estudiante_periodo_corte.parquet` con: `id_estudiante_anon`, `periodo_id`, `corte`, `probabilidad_desercion`, `nivel_riesgo`, `top_5_factores_riesgo`, `intervencion_sugerida` |
| **Skills** | `run_batch_prediction(model, X_corte)`, `assign_risk_level(probability)`, `export_to_parquet()`, `export_to_csv_powerbi()` |
| **Herramientas** | Modelo cargado desde MLflow, `pandas`, `pyarrow` |
| **Dependencias** | Agente Explicabilidad, Agente Feature Engineer |
| **Métricas** | Tiempo de predicción (< 5 min para 100K registros), % estudiantes procesados, distribución de niveles de riesgo |

**Niveles de riesgo:**
| Nivel | Rango probabilidad | Color dashboard |
|---|---|---|
| Bajo | 0–30% | Verde |
| Medio | 30–60% | Amarillo |
| Alto | 60–80% | Naranja |
| Crítico | >80% | Rojo |

---

### AGENTE 9: Monitoreo (Monitoring Agent)

**Objetivo:** Detectar degradación del modelo (concept drift, data drift), monitorear la calidad de los datos en producción y activar al Agente Coordinador cuando se requiere re-entrenamiento.

| Atributo | Detalle |
|---|---|
| **Inputs** | Predicciones históricas, datos de producción, métricas del modelo |
| **Outputs** | Reporte de drift, alertas de re-entrenamiento, dashboard de salud del modelo |
| **Skills** | `detect_data_drift(reference, current, method='ks_test')`, `detect_concept_drift(predictions, actual_outcomes)`, `monitor_feature_distribution()`, `trigger_retraining_alert()`, `log_model_health_metrics()` |
| **Herramientas** | `evidently`, `scipy`, `mlflow`, sistema de alertas |
| **Dependencias** | Agente Coordinador, Agente Evaluador |
| **Métricas** | % features con drift significativo, degradación de F1 en producción, frecuencia de alertas de re-entrenamiento |

---

## 3. Protocolos de Comunicación entre Agentes

- Todos los agentes intercambian datos a través de **archivos Parquet** versionados (artefactos), no en memoria compartida.
- El Agente Coordinador usa un **log de estado** (JSON) para rastrear el avance de cada agente.
- Los errores se propagan al Coordinador, quien decide si reintentar, escalar o detener el pipeline.
- Los mensajes de intervención del Agente Explicabilidad se exportan como parte del archivo de predicciones, no como comunicación directa con el estudiante (eso es responsabilidad del equipo de consejería).
