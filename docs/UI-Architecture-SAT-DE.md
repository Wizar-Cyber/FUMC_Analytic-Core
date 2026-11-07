# Arquitectura de la Interfaz Gráfica: SAT-DE (FUMC Analytics Core)

## 1. Prompt Optimizado para el Desarrollo de la Interfaz

**System Prompt / Prompt Principal:**
"Actúa como Diseñador Lead de UX/UI y Desarrollador Full-Stack/Power BI especializado en soluciones EdTech y Analítica Predictiva. Tu objetivo es diseñar e implementar la interfaz gráfica del **Sistema de Alerta Temprana de Deserción Estudiantil (SAT-DE / FUMC Analytics Core)** para la Fundación Universitaria María Cano.

**Contexto Institucional y Arquitectura:**
* **Entorno:** Azure Machine Learning + Orquestación Multi-Agente (Azure OpenAI GPT-4o mini) + Almacenamiento en Parquet.
* **Sedes integradas en la demo:** Medellín, Cali, Popayán y Neiva; programas y facultades se toman del catálogo del mockup.
* **Enfoque clave:** los agentes generan y muestran el análisis de demo automáticamente al terminar el lote. El score no es una causa ni una decisión. Alertas y seguimientos solo cambian registros simulados; no se envían mensajes ni se ejecutan intervenciones institucionales. Cualquier uso de datos reales o acción externa requiere validación institucional y supervisión profesional.

**Requerimientos de la Interfaz:**
1. **Filtros Globales Superior:** Sede, Programa (e.g., Ingeniería de Software, Fisioterapia), Modalidad, Semestre, Nivel de Riesgo (Alto, Medio, Bajo) y Estado de Intervención (Pendiente, En Gestión, Resuelto).
2. **Módulo 1 - Executive Dashboard (Nivel Directivo):**
   * KPIs principales: Total matriculados, % de estudiantes en riesgo alto, tasa de efectividad de retención, tiempo promedio de intervención.
   * Gráficos de distribución de riesgo por sede y programa.
   * Matriz de correlación de variables principales (promedio acumulado, materias reprobadas, días de mora, asistencia, actividad en plataforma).

3. **Módulo 2 - Vista Detallada de Estudiantes (Nivel Operativo/Tutor):**
   * Tabla dinámica con búsqueda rápida, ordenable por probabilidad de deserción.
   * Badges visuales de riesgo (*High*, *Medium*, *Low*).
   * Columnas clave: Código, Nombre, Programa, Sede, Nivel de Riesgo, Factor Principal de Riesgo y Botón de Acción.

4. **Módulo 3 - Ficha Individual del Estudiante (Diagnóstico Multi-Agente):**
   * Panel con desglose del **Agente Académico** (historico de notas, materias filtro reprobadas, asistencia).
   * Panel del **Agente Socioeconómico** (estrato, mora en pagos, soporte financiero).
   * **Síntesis del agente:** resumen cualitativo del LLM que conserva el score reportado y explicita sus límites; no presenta correlaciones como causas.
   * Acciones de apoyo propuestas, visibles como recomendaciones; la demo no las ejecuta.

5. **Módulo 4 - Alertas y seguimientos de demo:**
   * Reconocer/resolver una alerta y abrir/completar un seguimiento actualiza Azure Tables y su historial.
   * La creación de una tarea es explícita y queda vinculada al perfil sintético; no inicia contacto externo ni retroalimenta automáticamente el entrenamiento."

---

## 2. Arquitectura Gráfica de la Interfaz (Estructura de Pantallas)

### Layout General y Estilo Visual
* **Paleta de Colores:** Basada en la identidad de la universidad (Azul institucional de la María Cano como color primario, gris azulado para fondos/tarjetas, y semáforo de riesgo: Rojo `#EF4444` para Alto, Amarillo `#F59E0B` para Medio, Verde `#10B981` para Bajo).
* **Barra Superior:** Buscador general de estudiante (por ID/Nombre), selector de Sede y botón de actualización de sincronización con Azure Data Lake / Parquet.

---

### Dashboard Principal: Centro de Control de Deserción

```
+------------------------------------------------------------------------------------------------+
|  [Filtro: Sede ▼]  [Filtro: Programa ▼]  [Filtro: Modalidad ▼]  [Filtro: Nivel Riesgo ▼]      |
+------------------------------------------------------------------------------------------------+
|  [ KPI: Total Estudiantes ]   [ KPI: En Riesgo Alto ]   [ KPI: Cobertura TQU ]  [ Eficacia ML ]|
|          5,000                       412 (8.2%)               310 (75%)            91.4%     |
+----------------------------------------------------+-------------------------------------------+
|  Mapa de Riesgo por Sede y Programa                |  Factores Desencadenantes de Riesgo       |
|  (Gráfico de Barras Apiladas)                      |  (Gráfico de Rosca / Donut Chart)         |
|  - Medellín: 210 Alto                              |  - Bajo Promedio / Pérdida Materia (45%)  |
|  - Cali:      85 Alto                              |  - Mora en Matrícula / Pago (30%)         |
|  - Neiva:     42 Alto                              |  - Inactividad en Plataforma (15%)        |
|  - Popayán:   75 Alto                              |  - Inasistencia Continuada (10%)          |
+----------------------------------------------------+-------------------------------------------+
```

---

### Módulo Operativo: Listado y Matriz de Estudiantes
Esta vista permite a los coordinadores filtrar y priorizar rápidamente a los estudiantes que requieren atención inmediata.

| ID Estudiante | Programa | Sede | Semestre | Prom. Acum. | Asistencia | Mora (Días) | Score Riesgo | Diagnóstico Predominante | Acción |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **EST-00412** | Ing. de Software | Medellín | 4.° | 2.1 | 62% | 45 días | 88% (ALTO) | Académico + Financiero | [Ver Expediente] |
| **EST-01205** | Fisioterapia | Cali | 2.° | 3.2 | 80% | 60 días | 64% (MEDIO) | Mora Financiera | [Ver Expediente] |
| **EST-00891** | Administración | Virtual | 1.° | 4.1 | 95% | 0 días | 12% (BAJO) | Estable | [Ver Expediente] |

---

### Ficha Interactiva del Estudiante (Desglose Multi-Agente)
Al hacer clic en **[Ver Expediente]**, se despliega una modal o vista detallada con los hallazgos de cada sub-agente:

```
====================================================================================================
EXPEDIENTE DE EVALUACIÓN PREDICTIVA: EST-00412 | Ingeniería de Software (Sede Medellín)
====================================================================================================
[ PANEL DE HISTORIAL ACADÉMICO ]          [ PANEL SOCIOECONÓMICO Y ACCESIBILIDAD ]
- Promedio General: 2.1 / 5.0             - Estrato Socioeconómico: 1
- Materias Reprobadas: 3 (Estructuras)    - Días de Mora en Pago: 45 Días
- Asistencia Global: 62%                  - Apoyo "Te Quiero en la U": NO REGISTRA
- Horas Plataforma: 12 hrs/mes            - Becas/Auxilios: Ninguno Activo
----------------------------------------------------------------------------------------------------
🤖 SÍNTESIS Y DIAGNÓSTICO DEL AGENTE PREDICTIVO (Azure OpenAI GPT-4o mini)
----------------------------------------------------------------------------------------------------
"El estudiante presenta una probabilidad de deserción del 88%. El factor crítico reside en el 
bajo rendimiento en asignaturas filtro de 4.° semestre (Estructura de Datos), sumado a una 
inactividad prolongada en la plataforma LMS y un atraso de 45 días en el pago del crédito. 
La falta de participación en el programa TQU incrementa la vulnerabilidad de abandono."
----------------------------------------------------------------------------------------------------
🛠️ PLAN DE ACCIÓN SUGERIDO POR EL AGENTE (Human-in-the-Loop)
----------------------------------------------------------------------------------------------------
1. [ ] Asignación de Tutoría Par en Algoritmos y Estructura de Datos.
2. [ ] Remisión a Bienestar Universitario para evaluación de Beca/Auxilio Financiero de Emergencia.
3. [ ] Entrevista presencial o virtual con Psicología Académica.
----------------------------------------------------------------------------------------------------
✍️ DECISIÓN DEL EVALUADOR HUMANO (Coordinador / Bienestar)
----------------------------------------------------------------------------------------------------
Estado: [ Aprobado con Modificaciones  ▼ ]
Notas del Evaluador: "Se aprueba tutoría y auxilio. Se agenda cita prioritaria para el lunes."
[ GUARDAR E INICIAR RUTINA DE CONTACTO (Teams / Mail) ]
```
