# Vision.md — SAT-FUMC: Sistema de Alerta Temprana para la Deserción Estudiantil

> **Estado:** Documento fundacional — Versión 1.0

---

## 1. Declaración de Visión

Construir una **plataforma inteligente de analítica académica predictiva** que permita a la Fundación Universitaria María Cano (FUMC) identificar oportunamente a estudiantes con riesgo de deserción, generar alertas tempranas accionables y activar de forma focalizada el programa de permanencia **"Te quiero en la U"**, contribuyendo así a la reducción de la deserción estudiantil y al incremento de la permanencia, el bienestar y la graduación oportuna.

---

## 2. Problema de Negocio

La deserción estudiantil en educación superior colombiana representa una pérdida social, económica e institucional significativa. La FUMC, con presencia en cinco sedes y modalidades presencial, virtual e híbrida, enfrenta el reto de:

- Detectar **señales de riesgo** antes de que el estudiante abandone sus estudios.
- Personalizar las **intervenciones del programa "Te quiero en la U"** según el perfil de riesgo.
- Cubrir simultáneamente múltiples sedes, programas, jornadas y modalidades con recursos limitados de consejería.
- Operar sin datos reales disponibles en la fase inicial del proyecto (restricción que motiva el uso del Digital Twin).

---

## 3. Propuesta de Valor

| Dimensión | Situación actual | Con SAT-FUMC |
|---|---|---|
| Detección del riesgo | Reactiva / tardía | Predictiva / semanas 2–8 del semestre |
| Cobertura | Parcial, basada en criterio del consejero | Automatizada para todos los estudiantes activos |
| Personalización | Genérica | Por perfil de riesgo (académico, financiero, social) |
| Datos para decisión | Informes manuales | Dashboard en tiempo real (Power BI) |
| Trazabilidad | Limitada | Completa con auditoría y gobierno del dato |

---

## 4. Principios Rectores

1. **El objetivo es permanencia, no clasificación punitiva.** El SAT genera una *prioridad de intervención*, nunca una etiqueta sancionatoria.
2. **Sin fuga de información.** Las variables de cierre académico/financiero y estados finales no se usan como predictores tempranos.
3. **Equidad y fairness.** Las métricas de desempeño del modelo se evalúan por género, estrato, programa, modalidad y sede.
4. **Digital Twin como puente.** Ante la ausencia inicial de datos reales, se usa un gemelo digital de la FUMC que respeta fielmente la estructura institucional.
5. **Interoperabilidad.** Toda salida del sistema se expone en formatos consumibles por Power BI (Parquet / CSV / API REST).
6. **Respeto a los documentos existentes.** Ninguna decisión de diseño reemplaza o contradice las definiciones del diccionario de datos `diccionario_datos_SAT_desercion_FUMC.xlsx`.

---

## 5. Usuarios del Sistema

| Rol | Necesidad principal |
|---|---|
| Decanos y Vicerrectoría Académica | Vista ejecutiva de tasas de riesgo por facultad y programa |
| Coordinadores de Permanencia | Lista priorizada de estudiantes para intervención |
| Consejeros "Te quiero en la U" | Perfil individual de riesgo y factores explicativos |
| Equipo de Datos / Analytics | Gestión del modelo, calidad de datos, MLOps |
| Dirección de TI | Administración de la plataforma y pipelines |

---

## 6. Horizonte de Implementación

| Fase | Nombre | Duración estimada |
|---|---|---|
| 0 | Fundación (documentación, arquitectura) | 2 semanas |
| 1 | Digital Twin + datos sintéticos | 3 semanas |
| 2 | Pipeline ML + agentes core | 4 semanas |
| 3 | Dashboard Power BI | 2 semanas |
| 4 | MLOps y monitoreo | 3 semanas |
| 5 | Integración con datos reales (producción) | A definir con FUMC |
