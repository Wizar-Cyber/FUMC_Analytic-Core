# 13.02 | Lista de preparación para producción

> El estado global y la evidencia Azure están en [`ProductionArchitecture.md`](./ProductionArchitecture.md) y [`CloudDeploymentArchitecture.md`](./CloudDeploymentArchitecture.md). **Infraestructura desplegada no equivale a producto institucional listo.** Corte: 2026-11-09.

## 1. Matriz de preparación

| Área | Estado | Evidencia / brecha |
|---|---|---|
| Aprovisionamiento Azure | **Completado para la POC** | Bicep `Succeeded`; Function App Linux/Python 3.11 `Running`; Storage, Key Vault, Service Bus, Application Insights, Azure OpenAI provisionados. El servidor SQL no existía en el RG hasta 2026-11-10 (la versión anterior de esta tabla lo daba por provisionado) |
| Publicación Functions | **Completada** | `FUMCanalyticscore`, zip deploy con build remoto. Cuatro actividades Durable heredadas fallan al indexarse y no se usan |
| Acceso Entra | **Completado para la POC** | Sesión interactiva autenticada con `200`; los `POST` funcionan tras añadir el dominio a «Allowed external redirect URLs» (protección CSRF de Easy Auth) |
| SQL | **Integrado y verificado desde Functions (2026-11-12)** | La app escribe con su identidad administrada predicciones, propuestas, ejecuciones de agente y auditoría; lote E2E de 20 casos con 20 propuestas y 80 ejecuciones de agente en SQL. Faltan backup/restore y retención verificados |
| AML → Functions | **Parcial** | La cohorte de 15.000 estudiantes se puntuó con el endpoint `sat-fumc-endpoint` (modelo v2) mediante script; la interfaz no llama al endpoint en tiempo real y el reentrenamiento en AML falló |
| Datos FUMC autorizados | **Pendiente** | No existen conectores institucionales ni aprobación de tratamiento |
| Evidencia ML | **Insuficiente para promoción institucional** | Runs sintéticos a 10k y 100k obtuvieron Recall 0,8453/0,8162, pero alertaron 70,17%/78,68%; ambos `promotion_eligible=0`. Sin validación institucional ni capacidad de alertas aprobada; ver [`ScaleExperiments.md`](./ScaleExperiments.md). La recalibración 5k–100k con generador 2.1.0 (10 semillas por tamaño) da recall ≈ 0,60 con 40 % de alertas y exige ≈ 62–65 % para recall 0,80; 0 de 210 corridas cumplen recall ≥ 0,75, alertas ≤ 50 % y precisión ≥ 0,30, y el modelo está a ≤ 0,007 de AUC del techo teórico; ver [`Recalibration.md`](./Recalibration.md) |
| Prueba E2E autenticada | **Completada con datos sintéticos** | Lote de 20 casos lanzado desde la interfaz: 20 procesados, 0 fallidos; ver [`E2EValidation.md`](./E2EValidation.md) |
| Operación y CD | **Pendiente** | Sin CD institucional con OIDC/aprobaciones/rollback, SLO productivos, política privada o plan de operación validado |

## 2. Bloqueos antes de datos reales

1. **Gobierno:** aprobar finalidad, fuentes, base legal, responsable, privacidad, residencia, minimización, retención y acceso.
2. **Target y temporalidad:** acordar definición de deserción, madurez de outcome, ventanas y features disponibles en cada corte; resolver censoring y datos faltantes.
3. **Datos y calidad:** integrar fuentes autorizadas, pseudonimizar, versionar datasets y probar duplicados, leakage, drift y reglas de calidad.
4. **Modelo:** evaluación temporal con holdout institucional y separación por estudiante/cohorte; Recall ≥ 0,80 junto con precisión, F1, AUC, calibración, tasa de alertas, capacidad y fairness. Bloquear promoción si no supera los gates.
5. **Integración funcional:** compartir un snapshot/version común entre AML y agentes; conservar score/provenance; probar errores, timeout, idempotencia, DLQ y contrato end-to-end.
6. **Persistencia:** repositorio, migraciones (`SchemaVersion`), RBAC mínimo y pruebas de escritura/lectura ya existen contra Azure SQL; faltan despliegue en Functions, backup/restore y política de retención verificados.
7. **Identidad y seguridad:** completar prueba de usuario autorizado, validar allowlist, Managed Identity, referencias Key Vault, mínimo privilegio, red, privacidad, escaneo y respuesta a incidentes.
8. **Operación:** CI/CD con OIDC y ambientes, revisión y rollback; App Insights con dashboards, alertas, latencia, costo, errores, SLO y runbooks.
9. **Uso humano:** validación con orientadores y formación. Toda salida generativa es borrador; no habilitar decisiones automáticas ni contacto al estudiante.

## 3. Orden recomendado de cierre

1. ~~Completar inicio de sesión Entra y probar una lectura de bajo impacto con `200` como revisor permitido.~~ Completado el 2026-11-12.
2. Confirmar inicialización sintética, Managed Identity y roles de Storage/Service Bus/Azure OpenAI.
3. Ejecutar una prueba controlada de un caso y una aprobación/rechazo sintético; validar telemetría y errores.
4. ~~Diseñar y probar la integración Azure SQL desde Functions.~~ Verificada el 2026-11-12; faltan backup/restore y retención.
5. Integrar AML solo cuando haya contrato común, endpoint autorizado y pruebas de scoring.
6. Mantener sin uso institucional hasta completar gobierno, evaluación y operación de los puntos anteriores.

## 4. Reentrenamiento y retroalimentación

La revisión del orientador es una señal de proceso, no la etiqueta de deserción. El target solo se actualiza cuando la fuente institucional confirma el resultado y se cumple la ventana aprobada. Reentrenar en jobs versionados de Azure ML; comparar candidato/champion, auditar fairness y aprobar promoción con rollback antes de recibir tráfico.

## 5. Criterio de salida

La solución permanece como POC sintética. El despliegue de recursos y la aplicación del esquema SQL son hitos de infraestructura; no prueban desempeño, integración ni aptitud para priorizar estudiantes reales.
