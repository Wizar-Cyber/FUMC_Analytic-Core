# 02.01 | Alcance del SAT-FUMC

> Arquitectura canónica y estado actual: [`ProductionArchitecture.md`](./ProductionArchitecture.md).

## 1. Alcance del diseño objetivo

- Integrar, con autorización, snapshots de Académica, Finanzas, Bienestar y LMS.
- Validar calidad, pseudonimización, temporalidad y separación de etiquetas antes del entrenamiento.
- Ejecutar en paralelo la inferencia LightGBM en Azure ML y la red generativa Semantic Kernel/Durable Functions con GPT-5-mini.
- Consolidar probabilidad, factores, resúmenes, límites y recomendaciones sin alterar la salida del modelo.
- Entregar datos por API a una SPA autenticada: dashboard, ficha, alertas, revisión y seguimiento.
- Requerir la decisión humana, registrarla con auditoría y utilizar feedback solo conforme al ciclo institucional de etiquetado.
- Preparar Azure SQL para estado operacional; ADLS/Blob y Azure ML Data Assets para datos y artefactos históricos.
- Incorporar CI, evaluación de calidad ML/LLM, MLOps, observabilidad, secretos en Key Vault y aprobación de despliegue.

## 2. Implementado en la POC

Datos sintéticos, pipeline ML local/job AML, contrato de scoring, Functions/Service Bus/Durable Functions, agentes académico/financiero/bienestar, GPT-5-mini y SPA están presentes. Al 2026-11-09, Bicep está desplegado, la Function App está Running con 33 funciones indexadas y Azure SQL Online con las nueve tablas aplicadas. El acceso anónimo recibe 401 y la ruta Entra redirige a Microsoft, pero no se validó sesión autenticada con respuesta 200. AML y SQL no están conectados al flujo Functions; la POC no es apta para decisiones reales.

## 3. Fuera de alcance hasta contar con aprobación

- Conectores a SIS/LMS/finanzas/bienestar reales, identificadores directos o notas clínicas.
- Decisiones o intervenciones automáticas, contacto al estudiante, asignación automática de becas o acciones académicas.
- Afirmar desempeño institucional a partir del Digital Twin.
- La SPA autenticada es el punto único de acceso operativo.

## 4. Criterios de aceptación para producción

1. Fuentes, finalidad, target, cortes, disponibilidad temporal y retención aprobados por sus responsables.
2. Holdout temporal institucional sin leakage; Recall ≥ 0,80 y métricas complementarias aprobadas, con capacidad de intervención y fairness evaluadas.
3. Contrato común y prueba E2E que recorra snapshot→AML y agentes en paralelo→consolidación→Azure SQL→API→SPA.
4. Revisión humana, identidad Entra, auditoría, pruebas de privacidad/seguridad y controles de datos sensibles.
5. CI/CD, aprobación, monitoreo, alertas, carga, recuperación y rollback verificados.

El Recall ≥ 0,80 es un objetivo de aceptación pendiente de demostrar, no un compromiso que pueda garantizarse con el dataset sintético disponible.
