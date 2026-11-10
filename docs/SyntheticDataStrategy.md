# 04.01 | Estrategia de datos sintéticos y Digital Twin

> **Estado:** Documento fundacional — Versión 1.0  
> **Derivado de:** `contexto_fundacion_universitaria_maria_cano.md`, `diccionario_datos_SAT_desercion_FUMC.xlsx` (hojas: README, Diccionario_Datos, Tablas)

---

## 1. Justificación del Digital Twin

Inicialmente no existen datos reales disponibles para pruebas masivas del SAT-FUMC. Para avanzar con el desarrollo, entrenamiento y validación del sistema, se diseña un **Digital Twin (Gemelo Digital)** de la FUMC que:

- Respeta fielmente la estructura institucional real (sedes, programas, jornadas).
- Implementa las 337 variables del diccionario de datos con sus tipos, rangos y reglas de validación.
- Simula distribuciones estadísticas realistas (tasas de deserción por programa, estrato, jornada).
- Genera datos longitudinales (5 años académicos × 2 semestres = 10 periodos).
- Es completamente reemplazable por datos reales en Fase 5 sin modificar el pipeline downstream.

---

## 2. Parámetros de Simulación Institucional

### 2.1 Distribución de Estudiantes por Sede

| Sede | % del total | Modalidad principal |
|---|---|---|
| Medellín | 45% | Presencial |
| Virtual | 25% | Virtual |
| Cali | 12% | Presencial |
| Neiva | 10% | Presencial |
| Popayán | 8% | Presencial / Híbrida |

### 2.2 Distribución por Facultad y Programa

| Facultad | Programas | % matrícula |
|---|---|---|
| Ciencias de la Salud | Fisioterapia, Fonoaudiología, T. Ocupacional, Nutrición, Act. Física | 40% |
| Ciencias Empresariales | Admón. Empresas, Contaduría, Admón. Salud (Virtual) | 30% |
| Ingeniería | Ingeniería de Software | 15% |
| Ciencias Sociales | Psicología | 15% |

### 2.3 Tasas de Deserción Simuladas por Contexto

| Contexto | Tasa deserción base |
|---|---|
| Primer semestre (todos) | 22% |
| Jornada nocturna | +8% adicional |
| Estrato 1-2 | +10% adicional |
| Con mora financiera activa | +15% adicional |
| Sin participación "Te quiero en la U" | +6% adicional |
| Promedio < 3.0 | +20% adicional |
| Programa Ingeniería de Software | +5% adicional |
| Modalidad Virtual | +12% adicional |

### 2.4 Escala de los Datos

| Tabla | Filas en la última generación |
|---|---|
| `estudiante_periodo_corte` (tabla principal) | 27,975 filas (6,000 estudiantes; límite técnico de 35,000) |
| `estudiante_asignatura_periodo` | 120,734 filas |
| `financiera_estudiante_evento` | 62,877 filas |
| `bienestar_acompanamiento` | 9,969 filas |
| `solicitudes_estudiantiles` | 13,849 filas |
| `target_trazabilidad` | 27,975 filas |

Conteos del dataset de investigación versionado y comprometido en el repositorio.
El generador actual también admite corridas mayores bajo demanda. Se completaron
corridas temporales de 50k y 100k: esta última produjo 552.847 snapshots,
485.421 targets maduros y 2.394.881 filas de detalle académico. No se entrenó el
modelo a 50k/100k; no atribuir métricas ML a esos tamaños. La matriz y hashes
están en [`ScaleExperiments.md`](./ScaleExperiments.md). Estas filas no se envían
a agentes LLM; la app mantiene por separado su límite de 10.000 evaluaciones.
La tabla LMS semanal descrita en versiones anteriores no la genera el script
actual.

### 2.5 Base operativa sintética para la POC multiagente

El libro Excel es el diccionario y contrato de tablas; no contiene filas de
estudiantes. La Function App tiene un valor predeterminado de **5.000 estudiantes
ficticios** (`SYNTHETIC_STUDENT_COUNT`, con máximo de 5.000) si la configuración
no lo reemplaza. Al primer acceso autenticado al panel puede crear las tablas y
sembrar perfiles, snapshots `2025-2/SEMANA_4`, señales académicas, finanzas,
bienestar y `target_trazabilidad` en Azure Tables. Esa inicialización no se
validó mediante una sesión autenticada al 2026-11-09; el número es el default
del código, no un conteo observado en Azure.

Este conjunto operativo de la Function App es distinto del dataset tabular de
investigación de la sección 2.4 (6.000 estudiantes y 27.975 snapshots en la
última generación medida). No se deben sumar ni presentar ambos como una sola
población. El target permanece separado y no se consulta para construir entradas
de agentes.

La interfaz puede pedir explícitamente hasta cinco snapshots pendientes. El
Durable batch los procesa secuencialmente y guarda cada borrador para revisión
humana. No se ejecutan lotes al inicio ni por calendario. El interruptor de la
POC bloquea nuevas corridas; no permite pausar mientras un caso o lote está
activo.

---

## 3. Estrategia de generación

### Paso 1: Generar Catálogos Maestros
```
catalogos_maestros.parquet
├── programas (10 programas con códigos, facultad, duración semestres)
├── sedes (5 sedes con ciudad, modalidad)
├── asignaturas (~120 asignaturas distribuidas por programa)
├── tipos_beca (ICETEX, Mérito, Deporte, Bienestar, Empresa)
└── calendario_academico (2021-1 → 2025-2, fechas cortes)
```

### Paso 2: Generar Población de Estudiantes
- 6,000 estudiantes únicos con `id_estudiante_anon` (UUID).
- Atributos fijos: `cohorte_ingreso`, `genero`, `edad`, `estrato`, `municipio`, `trabaja`, `discapacidad`.
- Distribuciones basadas en parámetros institucionales reales.

### Paso 3: Simular Trayectorias Longitudinales
- Para cada estudiante, simular su estado por semestre: `Activo`, `Desertor`, `Graduado`, `Aplazado`.
- Probabilidad de deserción determinada por los factores de riesgo acumulados.
- Correlaciones realistas entre variables (ej: bajo promedio → mayor mora → menor participación LMS).

### Paso 4: Generar Variables por Corte Predictivo
- Para cada `(estudiante, periodo, corte)`, materializar solo las variables disponibles antes de ese corte.
- Cortes: `INICIO`, `SEMANA_2`, `SEMANA_4`, `PRIMER_CORTE`, `SEMANA_8`.

### Paso 5: Separar Target
- Construir `target_trazabilidad` siguiendo la fórmula exacta del diccionario.
- Verificar que ninguna variable del target aparezca en la tabla de predictores.

### Paso 6: Validar con Reglas de Calidad
- Ejecutar el Agente de Calidad sobre los datos sintéticos.
- Corregir cualquier violación antes de usar los datos en entrenamiento.

---

## 4. Librerías y herramientas

```python
# Generación de datos
import numpy as np
import pandas as pd
from faker import Faker
import pyarrow as pa
import pyarrow.parquet as pq

# Distribuciones estadísticas
from scipy import stats

# Correlaciones y estructura de datos
from numpy.random import default_rng
```

---

## 5. Validación del Digital Twin

El Digital Twin se considera válido si:
- [ ] Tasa de deserción global entre 15% y 30% (referencia Colombia).
- [ ] Desbalance de clases refleja la realidad (desertores ≈ 20–25% del total).
- [ ] Distribución de promedios: media ~3.5, desviación ~0.6, escala 0–5.
- [ ] Cobertura completa de las 5 sedes y los 10 programas.
- [ ] Correlaciones entre variables coherentes (ej: estrato bajo ↔ mayor mora, mayor deserción).
- [ ] Pasa todas las reglas críticas y de alta severidad del Agente de Calidad.
- [ ] Los modelos ML entrenados sobre este dataset alcanzan métricas plausibles (F1 ≥ 0.70).

---

## 6. Plan de transición a datos reales

Cuando la FUMC provea los datos reales:

1. El Agente Ingestor reemplaza la ruta de archivos sintéticos por la ruta real.
2. El Agente de Calidad aplica las mismas reglas (el diccionario de datos es la fuente de verdad).
3. El Agente Feature Engineer usa el mismo pipeline (sin cambios).
4. Se re-entrena el modelo con datos reales y se versiona en MLflow.
5. El Digital Twin se archiva para referencias y auditoría futura.
