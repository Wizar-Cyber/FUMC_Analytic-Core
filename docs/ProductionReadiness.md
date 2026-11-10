# 13.02 | Lista de preparación para producción

> El estado global y la evidencia Azure están en [`ProductionArchitecture.md`](./ProductionArchitecture.md) y [`CloudDeploymentArchitecture.md`](./CloudDeploymentArchitecture.md). **Infraestructura desplegada no equivale a producto institucional listo.** Corte: 2026-11-09.

## 1. Matriz de preparación

| Área | Estado | Evidencia / brecha |
|---|---|---|
| Aprovisionamiento Azure | **Completado para la POC** | Bicep `Succeeded`; Function App Linux/Python 3.11 `Running`; Storage, Key Vault, Service Bus, Application Insights, Azure OpenAI y SQL provisionados |
| Publicación Functions | **Completada** | Core Tools v4/build remoto; host inició y 33 funciones se indexaron |
| Acceso Entra | **Configurado; prueba parcial** | Rutas anónimas `401`; login Entra `302`. Sin `200` posterior a autenticación interactiva |
| SQL | **Base/esquema listos, integración pendiente** | `SATFUMCOperational` Online y nueve tablas creadas; Functions sigue usando Azure Tables/Blob |
| AML → Functions | **Pendiente** | El Digital Twin de la POC genera su score; no se verificó invocación del endpoint AML desde la app |
| Datos FUMC autorizados | **Pendiente** | No existen conectores institucionales ni aprobación de tratamiento |
| Evidencia ML | **Insuficiente para promoción** | Recall ≥ 0,80 no demostrado; métricas históricas no conciliadas; job no ejecutado en esta verificación |
| Prueba E2E autenticada | **Pendiente** | No se completó sign-in con cuenta permitida ni ejecución de caso autenticado |
| Operación y CD | **Pendiente** | Sin CD institucional con OIDC/aprobaciones/rollback, SLO productivos, política privada o plan de operación validado |

## 2. Bloqueos antes de datos reales

1. **Gobierno:** aprobar finalidad, fuentes, base legal, responsable, privacidad, residencia, minimización, retención y acceso.
2. **Target y temporalidad:** acordar definición de deserción, madurez de outcome, ventanas y features disponibles en cada corte; resolver censoring y datos faltantes.
3. **Datos y calidad:** integrar fuentes autorizadas, pseudonimizar, versionar datasets y probar duplicados, leakage, drift y reglas de calidad.
4. **Modelo:** evaluación temporal con holdout institucional y separación por estudiante/cohorte; Recall ≥ 0,80 junto con precisión, F1, AUC, calibración, tasa de alertas, capacidad y fairness. Bloquear promoción si no supera los gates.
5. **Integración funcional:** compartir un snapshot/version común entre AML y agentes; conservar score/provenance; probar errores, timeout, idempotencia, DLQ y contrato end-to-end.
6. **Persistencia:** conectar el repositorio a Azure SQL (actualmente solo hay esquema), agregar migraciones/versionado, RBAC, auditoría, backup/restore, retención y pruebas de escritura/lectura.
7. **Identidad y seguridad:** completar prueba de usuario autorizado, validar allowlist, Managed Identity, referencias Key Vault, mínimo privilegio, red, privacidad, escaneo y respuesta a incidentes.
8. **Operación:** CI/CD con OIDC y ambientes, revisión y rollback; App Insights con dashboards, alertas, latencia, costo, errores, SLO y runbooks.
9. **Uso humano:** validación con orientadores y formación. Toda salida generativa es borrador; no habilitar decisiones automáticas ni contacto al estudiante.

## 3. Orden recomendado de cierre

1. Completar inicio de sesión Entra y probar una lectura de bajo impacto con `200` como revisor permitido.
2. Confirmar inicialización sintética, Managed Identity y roles de Storage/Service Bus/Azure OpenAI.
3. Ejecutar una prueba controlada de un caso y una aprobación/rechazo sintético; validar telemetría y errores.
4. Diseñar y probar la integración Azure SQL en entorno no productivo; no afirmar persistencia SQL hasta probarla desde Functions.
5. Integrar AML solo cuando haya contrato común, endpoint autorizado y pruebas de scoring.
6. Mantener sin uso institucional hasta completar gobierno, evaluación y operación de los puntos anteriores.

## 4. Reentrenamiento y retroalimentación

La revisión del orientador es una señal de proceso, no la etiqueta de deserción. El target solo se actualiza cuando la fuente institucional confirma el resultado y se cumple la ventana aprobada. Reentrenar en jobs versionados de Azure ML; comparar candidato/champion, auditar fairness y aprobar promoción con rollback antes de recibir tráfico.

## 5. Criterio de salida

La solución permanece como POC sintética. El despliegue de recursos y la aplicación del esquema SQL son hitos de infraestructura; no prueban desempeño, integración ni aptitud para priorizar estudiantes reales.
