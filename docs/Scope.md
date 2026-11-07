# Scope.md — Alcance del Proyecto SAT-FUMC

> **Estado:** Documento fundacional — Versión 1.0

---

## 1. Dentro del Alcance (In-Scope)

### 1.1 Cobertura Institucional
- **Sedes:** Medellín (principal), Cali, Neiva, Popayán, Virtual (nacional/internacional).
- **Programas:** Todos los programas de pregrado activos: Fisioterapia, Fonoaudiología, Terapia Ocupacional, Nutrición y Dietética, Actividad Física y Deporte, Administración de Empresas, Contaduría Pública, Administración en Salud (Virtual), Ingeniería de Software, Psicología.
- **Jornadas:** Diurna, nocturna, mixta, virtual.
- **Modalidades:** Presencial, virtual, híbrida.
- **Ventana temporal:** Últimos 5 años académicos con granularidad por periodo (semestre).

### 1.2 Generación de Datos Sintéticos (Digital Twin)
- Datasets en formato `.parquet` representando la operación institucional de la FUMC.
- Tablas: `estudiante_periodo_corte`, `estudiante_asignatura_periodo`, `lms_estudiante_curso_semana`, `financiera_estudiante_evento`, `bienestar_acompanamiento`, `solicitudes_estudiantiles`, `target_trazabilidad`, `calendario_academico_financiero`, `catalogos_maestros`.
- Mínimo 100,000 registros en tabla principal; escala suficiente para simular Big Data.

### 1.3 Arquitectura Multi-Agente
- Orquestación de agentes con LangChain / CrewAI / AutoGen.
- Agentes: Coordinador, Ingestor, Calidad de Datos, Feature Engineer, Entrenador, Evaluador, Explicador, Predictivo, Monitor.

### 1.4 Pipeline de Machine Learning
- Modelos candidatos: XGBoost, LightGBM, CatBoost, Random Forest, Redes Neuronales.
- Selección automática del mejor modelo por métricas de clasificación (F1, Recall, AUC-ROC).
- Explicabilidad mediante SHAP/LIME.
- Cortes predictivos: inicio del semestre, semana 2, semana 4, primer corte, semana 8, cierre.

### 1.5 Visualización — Power BI
- Dashboard ejecutivo: tasa de riesgo por sede, facultad, programa.
- Perfil individual: probabilidad de deserción (0–100%) + factores explicativos.
- Gráficos de cascada (waterfall) para los factores de riesgo del estudiante.
- Integración vía archivos Parquet/CSV o API REST.

### 1.6 MLOps
- Versionado de modelos y datasets.
- Monitoreo de drift de datos y modelos.
- Pipeline de re-entrenamiento programado.

---

## 2. Fuera del Alcance (Out-of-Scope)

| Elemento | Razón |
|---|---|
| Integración directa con sistemas transaccionales de la FUMC (ERP, LMS real) en Fase 0–3 | Requiere acceso institucional; se integra en Fase 5 |
| Variables prohibidas como predictores (`fecha_retiro`, `motivo_retiro`, `reinscrito_t1`, `reinscrito_t2`, `graduado_hasta_t2`) | Regla crítica del diccionario de datos: fuga de información |
| Diagnósticos clínicos o notas de consejería detalladas | Privacidad / datos sensibles |
| Gestión de identidad de estudiantes reales (CÉDULA, correo institucional) | Solo IDs anonimizados (UUID/hash) |
| Automatización de la intervención (envío automático de correos, citas) | Fase posterior; requiere aprobación institucional |
| Programas de posgrado o educación continua | No contemplados en el contexto FUMC actual |

---

## 3. Restricciones Técnicas

- Variables del target (`target_desercion`) nunca se mezclan con predictores.
- Toda variable usable como predictor debe ser observable **antes** de la fecha de corte predictivo.
- Dato de sesgo sensible (género, estrato, etnia) se usa con evaluación de fairness documentada.
- Formato de datos de salida: Parquet (procesamiento) + CSV/JSON (Power BI).

---

## 4. Criterios de Éxito

| KPI | Meta |
|---|---|
| F1-Score del modelo en conjunto de prueba | ≥ 0.75 |
| Recall (sensibilidad a desertores) | ≥ 0.80 |
| Cobertura de programas y sedes en el dataset sintético | 100% |
| Tiempo de predicción por corte | < 5 minutos para 100K registros |
| Dashboard funcional en Power BI | Mínimo 3 vistas (ejecutiva, programa, estudiante) |

---

## 5. Supuestos

- Los datos sintéticos del Digital Twin son estadísticamente representativos de la población real de la FUMC.
- La definición de `target_desercion` del diccionario de datos es la fuente de verdad y no cambia durante el proyecto.
- El equipo tiene acceso a Python 3.10+, bibliotecas de ML y Power BI Desktop.
- Se respeta la hoja `Exclusiones_Modelo` del diccionario de datos como lista de exclusiones definitivas.
