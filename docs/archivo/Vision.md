# 01.01 | Visión del SAT-FUMC

El SAT-FUMC busca apoyar a los equipos de permanencia de la Fundación Universitaria María Cano a revisar señales académicas, financieras, de bienestar y LMS de forma oportuna. La plataforma prioriza acompañamiento; no etiqueta de forma punitiva ni toma decisiones en lugar de las personas.

## 1. Experiencia objetivo

Un snapshot temporal validado alimenta en paralelo (1) un modelo LightGBM en Azure Machine Learning y (2) agentes Semantic Kernel sobre Service Bus y GPT-5-mini. La consolidación conserva la probabilidad del modelo, evidencia, incertidumbres y propuestas. El profesional accede desde una SPA autenticada y decide; el seguimiento y feedback quedan auditados.

## 2. Principios

1. Minimizar datos y usar identificadores seudónimos.
2. Usar únicamente señales disponibles a la fecha de corte; separar target y predictores.
3. Mostrar el score como estimación, no como causa o decisión.
4. Requerir revisión profesional para cada recomendación.
5. Evaluar Recall, precisión, calibración, capacidad de intervención y equidad con cohortes reales.
6. No presentar datos, tendencias o métricas sintéticas como evidencia institucional.
7. Mantener la SPA como único punto de acceso operativo; exportación CSV no es una segunda interfaz.

## 3. Estado actual y ruta de evolución

Al 2026-11-12 la Function App `FUMCanalyticscore` (grupo `FUMC.CaseReviewer`, Brazil South, Flex Consumption, Python 3.11) está `Running`. El flujo de agentes por Service Bus se verificó con un usuario autenticado (lote de 20 casos: 20 procesados, 0 fallidos), la cohorte de 15.000 estudiantes está puntuada por el endpoint Azure ML v2 y la app escribe en Azure SQL. Evidencia en [`E2EValidation.md`](./E2EValidation.md). No hay fuentes FUMC conectadas. La arquitectura y brechas canónicas están en [`ProductionArchitecture.md`](./ProductionArchitecture.md). La habilitación institucional depende de aprobación de fuentes, seguridad/privacidad, validación del modelo, inferencia AML en tiempo real, CI/CD y operación por TI/FUMC.
