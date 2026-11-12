# 09.02 | Vista ejecutiva del estudiante y diagnóstico consolidado

> Describe cómo la salida de la red multiagente se convierte en una única vista para directivos y equipo de permanencia. Complementa [`UI-Architecture-SAT-DE.md`](./UI-Architecture-SAT-DE.md) y [`AgentsDefinition.md`](./AgentsDefinition.md). Aplica a la POC sintética; no constituye validación institucional de eficacia.

## 1. Problema que resuelve

La versión anterior mostraba en el perfil un informe por agente (financiero, académico, bienestar), una «síntesis del LLM» que volvía a resumirlos, limitaciones, uso de tokens, costos estimados y códigos internos (`attended`, `sessions`, `academic_advisor_review`…). El resultado era texto redundante, con aspecto de consola técnica y difícil de leer para la toma de decisiones.

**Regla de diseño:** un rector, decano o integrante del equipo de permanencia debe entender la situación de un estudiante en menos de 15 segundos, sin leer párrafos extensos ni detalles del pipeline de IA.

## 2. Flujo multiagente: un solo resultado explicativo

```text
Agente financiero  ─┐   hallazgos internos (≤ 3 c/u, con cifras)
Agente académico   ─┼──►  Sintetizador  ──►  Diagnóstico único (≤ 150 palabras)
Agente bienestar   ─┘        ▲                       + acciones propuestas
                             │                              │
              nivel de riesgo ya clasificado                ▼
                                          Consolidación determinista (executive.py)
                                                            │
                                                            ▼
                                                 Vista ejecutiva (SPA)
```

- Los agentes especializados son **motores internos**: su salida se guarda para auditoría pero **nunca se muestra** en la interfaz.
- El **sintetizador** fusiona los tres informes en un único `summary` que explica por qué el estudiante presenta su nivel de riesgo: empieza por el nivel (Bajo/Medio/Alto/Crítico), nombra los factores asociados con cifras concretas y cierra con el foco prioritario. Usa lenguaje de asociación («asociado a», «coincide con»), sin afirmar causalidad ni mencionar modelos, agentes, IA o nombres de campos.
- El sintetizador recibe el `risk_level` ya clasificado, de modo que el texto y el semáforo usan la misma etiqueta.

### 2.1 Límites de salida

Definidos en `azure/agent_platform/sat_agents/policy.py` y aplicados dos veces: en las instrucciones del agente y, como defensa, en el saneamiento de `contracts.py` (el modelo puede ignorar el prompt).

| Elemento | Límite |
|---|---|
| `summary` de cada agente especializado | 1 frase, ≤ 240 caracteres |
| `observations` de cada agente | ≤ 3 hallazgos, ≤ 160 caracteres, sin duplicados |
| `limitations` (agentes y sintetizador) | ≤ 1 elemento |
| `summary` del sintetizador (diagnóstico) | 40–150 palabras, un párrafo |
| Acciones propuestas | solo códigos permitidos, ≤ 4 |

Antes de mostrarse, el diagnóstico pasa por `_clean_explanation`: reemplaza cualquier código interno de acción por su etiqueta institucional y recorta a 150 palabras.

## 3. Consolidación determinista (`sat_agents/executive.py`)

`build_executive_view(profile, review, followups)` combina el expediente, el resultado del sintetizador y los seguimientos en una estructura de tamaño fijo. El endpoint `GET /api/poc/students/{student_id}` la devuelve en el campo `executive`.

| Campo | Contenido | Límite |
|---|---|---|
| `risk` | Nivel (`Crítico` ≥ 0,80; `Alto` ≥ 0,60; `Medio` ≥ 0,30; `Bajo`), tono y probabilidad en % | — |
| `priority` | Score 0–100 y etiqueta (`Inmediata` ≥ 75, `Alta` ≥ 55, `Programada` ≥ 30, `Monitoreo`) | — |
| `status` | `Sin intervención`, `Plan por validar`, `En seguimiento`, `Intervención completada`, `Plan descartado` | — |
| `explanation` | Diagnóstico consolidado (`source: consolidated`) o preliminar (`source: preliminary`) | ≤ 150 palabras |
| `factors` | Factores con su evidencia numérica e impacto 0–100, ordenados por impacto | ≤ 4 |
| `actions` | Checklist con etiqueta institucional y estado (`pending`, `in_progress`, `done`) | ≤ 4 |
| `timeline` | Intervenciones registradas, más recientes primero | ≤ 5 |

### 3.1 Factores y evidencia

Se calculan a partir de los datos, no del texto del LLM, para que la evidencia sea reproducible:

| Factor | Condición | Evidencia mostrada | Acción asociada |
|---|---|---|---|
| Morosidad financiera activa | mora > 0 meses | `2 meses · $1.347.388` | Evaluación de apoyo financiero |
| Bajo rendimiento en asignaturas críticas | ≥ 1 nota < 3,0 | `3 asignaturas` | Tutoría en asignaturas críticas |
| Inasistencia recurrente | asistencia promedio < 75 % | `60% asistencia` | Cita con asesor académico |
| Uso insuficiente de servicios de acompañamiento | riesgo ≥ Medio y sin asistencia a bienestar | `sin asistencia registrada` | Seguimiento en bienestar universitario |
| Combinación de señales de riesgo de abandono | riesgo ≥ Alto sin ningún factor anterior | `sin un factor dominante` | Cita con asesor académico |

No se incluye «promedio inferior a 3,0» porque siempre implica al menos una asignatura crítica y repetiría el segundo factor.

### 3.2 Prioridad de atención

`score = 0,7 × probabilidad × 100 + 0,3 × impacto medio de los 3 factores principales − 10 si hay una intervención activa`, acotado a 0–100. El descuento evita que un caso ya atendido desplace a uno crítico sin atención.

### 3.3 Acciones sugeridas

Orden: «Contacto desde permanencia» (si el riesgo es ≥ Alto) → acciones derivadas de los factores → acciones adicionales propuestas por el sintetizador; sin duplicados y como máximo cuatro. El estado de cada acción se obtiene de los seguimientos existentes; el contacto se marca como completado cuando el caso ya tiene algún seguimiento. El contacto no es una acción de seguimiento del contrato, por lo que no tiene botón «Asignar».

### 3.4 Diagnóstico preliminar

Si el estudiante aún no tiene análisis, se genera un diagnóstico marcado como **Preliminar** que solo nombra las áreas afectadas (p. ej. «Riesgo crítico por la coincidencia de señales académicas, financieras y de bienestar.»). No repite cifras, porque ya aparecen en la evidencia inmediatamente debajo. El botón «Generar plan» lanza el análisis multiagente para obtener el diagnóstico consolidado.

## 4. Interfaz (pestaña «Resumen ejecutivo» del perfil)

```text
┌ Riesgo de abandono ──┐ ┌ Prioridad de atención ┐ ┌ Estado ───────────┐
│ ▲ Crítico   84%  ▬▬▬ │ │ 71  ◆ Alta       ▬▬▬  │ │ ■ En seguimiento  │
└──────────────────────┘ └───────────────────────┘ └───────────────────┘
┌ Diagnóstico ────────────────────────────┐ ┌ Acciones sugeridas ─────┐
│ Párrafo único consolidado (≤150 pal.)   │ │ ✓ Contacto permanencia  │
│ ─────────────────────────────────────── │ │ ◔ Tutoría               │
│ Factor 1 ............ evidencia  ▬▬▬▬▬  │ │ ○ Apoyo financiero [Asignar]
│ Factor 2 ............ evidencia  ▬▬▬    │ │ [Validar plan] [Descartar]
└─────────────────────────────────────────┘ └─────────────────────────┘
┌ Asignaturas del periodo (mapa de calor) ┐ ┌ Intervenciones (timeline)┐
└─────────────────────────────────────────┘ └─────────────────────────┘
```

- **Cada dato aparece una sola vez.** Nivel y probabilidad comparten tarjeta; la mora y el saldo viven en el factor financiero; el número de intervenciones se lee en la línea de tiempo; no hay banner que repita el estado.
- **Semáforos con icono y etiqueta** (▲ Crítico, ◆ Alto, ■ Medio, ● Bajo), nunca solo color; validados en tema claro y oscuro.
- **Mapa de calor de asignaturas:** una celda por asignatura (nota y asistencia), con leyenda: nota y asistencia bajas, nota < 3,0, asistencia < 75 %, en rango.
- **«Asignar»** crea el seguimiento de esa acción en un clic; **«Validar plan» / «Descartar»** conservan la decisión humana auditada sin texto explicativo adicional.
- La pestaña **Expediente** mantiene los datos detallados (personales, académicos, materias); **Seguimientos** mantiene la gestión de tareas.

### 4.1 Elementos retirados de la interfaz

«Análisis automático · multiagente», «Síntesis del LLM», «Resultado pendiente de revisión humana», «Probabilidad del modelo recibida», limitaciones, informes por agente, tabla de uso de tokens, costos estimados, fuentes recuperadas, pestañas vacías (Documentos, Línea de tiempo separada, Recomendaciones IA, Evaluación del modelo) y textos como «El score no implica causalidad». Se renombraron «Score IA» → «Riesgo», «Procesar GPT» → «Analizar casos», «Alertas IA» → «Alertas», «Analizar con agentes» → «Generar plan». En «Análisis recientes» del dashboard se muestra semáforo, porcentaje y número de acciones en lugar del texto del LLM.

Estos datos **siguen almacenándose** (Blob/SQL) para auditoría y para el reporte CSV; solo dejan de presentarse al usuario final.

## 5. Validación

`tests/test_executive_view.py`:

| Prueba | Verifica |
|---|---|
| `test_example_case_matches_institutional_format` | Caso de referencia: nivel, estado, factores con evidencia, estados de acciones y diagnóstico consolidado sin códigos internos |
| `test_preliminary_explanation_without_analysis` | Diagnóstico preliminar que nombra áreas sin repetir cifras |
| `test_low_risk_case_is_quiet` | Un caso de riesgo bajo no genera factores ni acciones |
| `test_executive_view_stays_bounded_at_scale` | Con 5.000, 10.000, 25.000, 50.000 y 100.000 estudiantes: ≤ 4 factores, ≤ 4 acciones, ≤ 5 eventos, diagnóstico ≤ 150 palabras, resto de la vista ≤ 100 palabras, < 6 KB por caso y < 2 ms por caso |
| `test_visible_text_has_no_technical_vocabulary` | El texto visible no contiene `_review`, `attended`, `sessions`, «token», «prompt», «GPT», «LLM», «agente», «modelo» ni nombres de variables |
| `test_agent_output_is_capped_before_consolidation` | El saneamiento recorta salidas verbosas a los límites de la §2.1 |

La cantidad de texto por estudiante es constante: no depende del tamaño de la población ni de la extensión de la respuesta del LLM.

## 6. Limitaciones y pendientes

- Los diagnósticos generados antes de este cambio usan las instrucciones anteriores y pueden contener lenguaje técnico; deben regenerarse analizando de nuevo esos casos.
- La calidad del diagnóstico consolidado depende del cumplimiento del prompt por parte del modelo; los límites de longitud y la limpieza de códigos están garantizados, el tono y la ausencia de jerga solo se verifican por instrucción.
- Los pesos de impacto y la fórmula de prioridad son heurísticas de presentación, no salidas del modelo predictivo ni criterios institucionales aprobados; deben calibrarse con el equipo de permanencia.
- La vista se verificó con pruebas automatizadas y capturas renderizadas con datos sintéticos; no se ha validado aún con una sesión autenticada contra Azure ni con usuarios directivos.
