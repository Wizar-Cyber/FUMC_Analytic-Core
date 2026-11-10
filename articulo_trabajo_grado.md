# TÍTULO DEL TRABAJO
Plataforma de apoyo a la permanencia estudiantil con aprendizaje automático y agentes generativos en Azure

# PAPER TITLE
Student Retention Decision Support with Machine Learning and Generative Agents on Azure

**Autor:** REIBER DAVID LOZANO ROMERO  
*Estudiante de Ingeniería de Software, Fundación Universitaria María Cano*  
*Documento resultado de trabajo de grado, modalidad proyecto de investigación. Director: [pendiente]. 2026.*

## Resumen

Este trabajo presenta el diseño y una prueba de concepto de una plataforma de apoyo a la permanencia estudiantil para la Fundación Universitaria María Cano. La propuesta consolida señales académicas, financieras, de bienestar y de participación LMS para alimentar dos ramas en paralelo: un modelo LightGBM ejecutado mediante Azure Machine Learning y una red de agentes basados en Semantic Kernel, Durable Functions y Azure OpenAI GPT-5-mini. Los resultados se presentan en una aplicación web autenticada y requieren revisión profesional; el sistema no toma decisiones académicas ni financieras automáticamente.

La implementación disponible se limita a datos sintéticos. El repositorio incluye pipelines de entrenamiento, contratos de scoring, una aplicación distribuida con agentes especializados y una SPA. El 9 de noviembre de 2026 se verificaron el despliegue de infraestructura Azure, la publicación de la Function App Linux/Python 3.11 y la aplicación de un esquema Azure SQL de nueve tablas. Esto acredita aprovisionamiento, no una operación end-to-end autenticada. Se evaluaron modelos sintéticos en escalas de 6k, 15k y 30k; las tasas de alerta fueron altas y ningún run quedó elegible para promoción. El generador, no el modelo, sí llegó a 100k estudiantes. No se obtuvo métrica de Recall/precisión/F1/AUC del modelo a 100k. La app aún no conecta AML ni SQL y no hay fuentes institucionales.

**Palabras clave:** permanencia estudiantil; aprendizaje automático; agentes generativos; Azure; revisión humana.

## Abstract

This work presents the design and a synthetic proof of concept for a student-retention decision-support platform at Fundación Universitaria María Cano. Academic, financial, wellbeing, and LMS signals are intended to feed two parallel branches: a LightGBM model hosted through Azure Machine Learning and a Semantic Kernel/Durable Functions agent network using Azure OpenAI GPT-5-mini. Results are delivered through an authenticated web application and require professional review; the system does not make academic or financial decisions automatically.

The available implementation is limited to synthetic data. Training pipelines, scoring contracts, a distributed agent application, and a web SPA are present. On November 9, 2026, Azure infrastructure provisioning, publication of a Linux/Python 3.11 Function App, and application of a nine-table Azure SQL schema were verified; this confirms resource provisioning, not authenticated end-to-end operation. Synthetic models were evaluated at 6k, 15k, and 30k scales, with high alert rates and no eligible promotion. The generator—not the model—completed at 100k students. No 100k model Recall/precision/F1/AUC was measured. The app does not yet consume the AML endpoint or SQL repository, and institutional data connectors are absent.

**Keywords:** student retention; machine learning; generative agents; Azure; human review.

## 1. Introducción

La permanencia estudiantil requiere identificar oportunamente señales que orienten el acompañamiento, sin convertir una estimación estadística en una decisión institucional. Este proyecto estudia una arquitectura de apoyo que combina predicción tabular, análisis generativo y revisión profesional. La motivación y los límites de uso se describen en [`docs/Vision.md`](docs/Vision.md) y [`docs/Scope.md`](docs/Scope.md).

El Digital Twin permite probar contratos, calidad y experiencia de usuario cuando no hay acceso aprobado a fuentes institucionales. Su comportamiento no acredita desempeño real ni representatividad poblacional. La finalidad del sistema es priorizar revisión, no etiquetar ni sancionar a estudiantes.

## 2. Arquitectura objetivo y estado implementado

El diseño objetivo ingiere snapshots temporales validados y ejecuta, en paralelo, (A) Azure ML/LightGBM y (B) agentes académico, financiero y bienestar con Semantic Kernel y Durable Functions. Azure OpenAI GPT-5-mini genera resúmenes y propuestas estructuradas. La consolidación conserva la probabilidad del modelo; una API autenticada sirve la SPA y un profesional aprueba, edita o rechaza las propuestas. El seguimiento y feedback se auditan.

El código actual implementa partes de ambas ramas como POCs independientes: el entrenamiento ML trabaja con archivos sintéticos, mientras la aplicación distribuida usa Azure Tables/Blob y una puntuación generada por el Digital Twin. No existe aún el join AML-agentes sobre el mismo snapshot ni integración con sistemas FUMC. Azure SQL está provisionado y su esquema aplicado, pero la persistencia SQL no está conectada a Functions. Véase [`docs/ProductionArchitecture.md`](docs/ProductionArchitecture.md) para el diagrama y matriz de estado.

## 3. Datos y metodología de evaluación

La unidad analítica prevista es estudiante-periodo-corte. El target debe permanecer separado de predictores y solo puede construirse al finalizar la ventana de observación. Toda variable debe estar disponible en el corte que origina la predicción. El esquema y los principios de datos se detallan en [`docs/DataArchitecture.md`](docs/DataArchitecture.md).

El pipeline Azure ML ahora usa una ventana temporal interna para una búsqueda acotada de hiperparámetros y selección del umbral, y reserva los periodos finales para el holdout. La clase positiva se trata mediante ponderación; el modelo no se promueve si no cumple la compuerta de Recall configurada en validación y holdout o si la operación resulta degenerada. Esta modificación aún debe probarse con más periodos históricos y datos reales; no es un resultado experimental nuevo.

El protocolo de producción debe reportar Recall, precisión, F1, AUC, calibración, tasa de alertas y métricas por cohortes, junto con incertidumbre y capacidad del equipo de intervención. Recall ≥ 0,80 no se puede garantizar sin etiquetas institucionales suficientes, definición estable del target, partición temporal válida y validación de la carga de trabajo.

Los experimentos sintéticos por volumen, sus versiones de dataset y todas las métricas registradas se presentan en [`docs/ScaleExperiments.md`](docs/ScaleExperiments.md). En particular, 100k corresponde a generación de datos y prueba de escala, no a entrenamiento/evaluación del modelo.

## 4. Agentes generativos y revisión humana

La POC distribuida implementa workers especializados académico, financiero y bienestar, cuyos resultados estructurados se sintetizan mediante Azure OpenAI GPT-5-mini. La salida debe conservar límites, evidencia permitida y uso real de tokens. Los agentes no recalculan el score, no infieren diagnósticos ni causalidad y no ejecutan intervenciones. Cada propuesta queda pendiente de una decisión de un revisor autenticado.

La calidad de la rama generativa debe evaluarse con un conjunto de casos autorizado y versionado: fidelidad, citas, seguridad, sesgo, abstención, costo y latencia. El uso de datos sintéticos no valida su utilidad para profesionales ni su desempeño sobre personas reales.

## 5. Resultados sintéticos y escala experimental

| Escala del conjunto | Recall | Precisión | F1 | AUC-ROC | AUC-PR | Brier | Tasa de alertas | Promoción |
|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 6k baseline | 0,6971 | 0,3194 | 0,4381 | 0,6071 | 0,3929 | 0,2348 | 62,52% | No |
| 15k baseline | 0,8069 | 0,3090 | 0,4469 | 0,6456 | 0,3827 | 0,2328 | 65,32% | No |
| 30k baseline | 0,7731 | 0,3313 | 0,4639 | 0,6679 | 0,4236 | 0,2333 | 61,31% | No |

Son resultados de evaluación sobre datos sintéticos en runs locales aislados; no son métricas institucionales y no deben mezclarse con variantes calibradas o con diferentes splits. El 15k cruza Recall 0,80, pero la tasa de alertas es 65,32% y el run no supera la compuerta de promoción. Las corridas 50k y 100k generaron datasets sin entrenar ni evaluar modelos; en 100k se generaron 552.847 snapshots, 485.421 etiquetas maduras y 2.394.881 filas académicas. La matriz completa y las variantes calibradas están en [`docs/ScaleExperiments.md`](docs/ScaleExperiments.md).

## 6. Despliegue Azure verificado y límites de la evidencia

El despliegue Bicep `satfumc-prod` terminó `Succeeded` en `rg-sat-fumc-prod`. La Function App `satfumcfunc0e83b2486979` está `Running`, usa Linux/Flex Consumption con Python 3.11 y Azure indexó 33 funciones tras publicar el paquete con Core Tools v4 y compilación remota. Azure SQL `SATFUMCOperational` está `Online`; se aplicó `sql_schema.sql` y se verificaron las nueve tablas esperadas. El deployment de Azure OpenAI `sat-gpt5-mini` y los recursos de Storage, Key Vault y Service Bus también fueron comprobados.

Easy Auth bloqueó solicitudes anónimas a `/` y `/api/poc/status` con `401`; `/.auth/login/aad` redirigió (`302`) a Microsoft. No se completó el inicio de sesión interactivo, la carga autenticada del dashboard ni la ejecución de un caso. La consulta de Application Insights de los últimos 14 días devolvió cero requests y cero dependencies (272 traces), por lo que tampoco hay evidencia de una invocación a GPT en esa ventana. Esto concuerda con el flujo: abrir/refrescar el dashboard no llama GPT; se requiere iniciar explícitamente un lote autenticado. El código de Functions aún persiste en Tables/Blob y no llama al repositorio SQL ni a Azure ML.

La suite automatizada local pasó 71 pruebas en la última ejecución. Estas son pruebas de código y contratos, no sustituyen la prueba autenticada en Azure. La advertencia Bicep `BCP187` sobre `sku` se emitió durante el provisioning, que finalizó correctamente; queda como asunto de esquema por revisar.

## 7. Interfaz y ejecución de GPT

La interfaz muestra conteos/riesgo del Digital Twin, perfiles sintéticos, alertas creadas por reglas, seguimientos sembrados y tendencias marcadas como simuladas. Estos elementos no son resultados GPT ni scoring de Azure ML. El análisis GPT solo aparece después de procesar un lote de hasta cinco casos pendientes; la página no hace inferencia al abrirse ni en el refresco automático.

El detalle operativo, los estados que habilitan el botón y la secuencia para comprobar un resultado GPT autenticado se documentan en [`docs/ScaleExperiments.md`](docs/ScaleExperiments.md#6-por-qu%C3%A9-pueden-no-verse-resultados-gpt).

## 8. Conclusiones y trabajo futuro

El repositorio y el despliegue verificado demuestran una base técnica para dos ramas de IA y una experiencia web de revisión, pero no una plataforma institucional lista para producción. El trabajo siguiente requiere autorización y conectores a fuentes, contrato común de snapshot, scoring AML y agentes en paralelo, integración de Azure SQL, pruebas E2E autenticadas, CI/CD con gates, monitoreo y seguridad de red.

Antes de cualquier uso real se debe validar Recall ≥ 0,80 y las métricas complementarias en cohortes temporales institucionales; evaluar fairness, privacidad y capacidad de intervención; y obtener aprobación de la Universidad. Mientras esos gates no se cumplan, el sistema debe permanecer como POC sintética.

## 9. Referencias internas

- [`docs/ProductionArchitecture.md`](docs/ProductionArchitecture.md) — arquitectura objetivo y estado verificable.
- [`docs/ProductionReadiness.md`](docs/ProductionReadiness.md) — gates de producción.
- [`docs/CloudDeploymentArchitecture.md`](docs/CloudDeploymentArchitecture.md) — evidencia y límites del despliegue Azure.
- [`docs/ScaleExperiments.md`](docs/ScaleExperiments.md) — escalas, métricas y flujo GPT de la interfaz.
- [`docs/AIArchitecture.md`](docs/AIArchitecture.md) — ramas predictiva y generativa.
- [`docs/DataArchitecture.md`](docs/DataArchitecture.md) — contratos y modelo de datos.
- [`docs/SyntheticDataStrategy.md`](docs/SyntheticDataStrategy.md) — límites del Digital Twin.
- [`azure/agent_platform/README.md`](azure/agent_platform/README.md) — POC de agentes.
