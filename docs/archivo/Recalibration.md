# 04.03 | Recalibración integral del modelo: experimentos 5k–100k, estabilidad y viabilidad de despliegue

> **Corte de evidencia: 2026-11-11.** Todos los datos son **sintéticos** (Digital Twin, escenario `baseline`, semilla 42). Nada de lo aquí reportado es evidencia de desempeño institucional.
> **Alcance de las cifras:** §1–§11 usan el generador 2.0.0 (modo `legacy`); §12 repite el análisis con el generador 2.1.0 corregido y es la referencia vigente.
> Código: [scripts/recalibration_lib.py](../../scripts/recalibration_lib.py), [scripts/recalibration_experiments.py](../../scripts/recalibration_experiments.py), [scripts/recalibration_report.py](../../scripts/recalibration_report.py). Resultados crudos: `outputs/recalibration/` (`matriz_consolidada.csv`, `resumen_etapas.csv`, `estabilidad_multisemilla.csv`, `bootstrap_estudiantes.csv`, `estadistica.json`, `tablas.md`, `figs/`).

## 1. Conclusión

**Ninguna configuración es promovible, y la causa no es el ajuste del modelo.** Con las mismas variables del proyecto, el modelo recalibrado alcanza el techo de información de los datos sintéticos: su AUC es estadísticamente indistinguible del de un *oráculo* que conoce la función de riesgo real del generador (brecha entre −0,003 y +0,004; el modelo no queda significativamente por debajo del oráculo en ningún tamaño).

| | Baseline del proyecto | Configuración final |
|---|---:|---:|
| AUC-ROC (media 7 tamaños) | 0,653 | **0,669** |
| Brier / ECE | 0,234 / 0,207 | **0,187 / 0,039** |
| % alertas con la regla «recall ≥ 0,80 en validación» | 62,3 % | **53,9 %** |
| Recall con esa regla | 0,762 | 0,707 |
| Recall con **40 %** de alertas (capacidad fija) | 0,558 | **0,571** |
| Dispersión del AUC entre tamaños (sd) | 0,027 | **0,017** |

Para recall ≈ 0,80 hace falta alertar ≈ 63–69 % de los estudiantes en todos los tamaños. Con 40 % de alertas el recall máximo observado es ≈ 0,57–0,60. **Ninguna de las 420 corridas finales (7 tamaños × 10 semillas × 2 protocolos × 3 políticas) cumple a la vez recall ≥ 0,75, alertas ≤ 50 % y precisión ≥ 0,30.** El criterio de promovibilidad del enunciado es inalcanzable con estos datos, no solo con este modelo.

## 2. Protocolo y criterios (fijados antes de iterar)

- **Variables:** exactamente el contrato de `src/ml/feature_engineering.py`. Únicas adiciones: transformaciones determinísticas de esas mismas columnas (promedio del semestre en curso = `promedio_semestre_anterior + tendencia_promedio`, y indicadores de umbral: promedio < 3,0, mora > 0, rezago > 15, estrato ≤ 2, sin apoyo de permanencia, producto de factores). Sin fuentes nuevas.
- **Tamaños:** 5.000, 10.000, 15.000, 25.000, 50.000, 75.000, 100.000 **estudiantes** (no filas; cada estudiante genera ≈ 5,5 snapshots). Generador `generate_digital_twin.py` v2.0.0, mismo escenario y semilla; sin etiquetas inmaduras en ningún tamaño.
- **Split (igual al del proyecto):** test = estudiantes disjuntos en los dos últimos periodos (20 %); validación = un periodo previo con otros estudiantes (20 %); el umbral se elige solo con validación y el modelo se reajusta después con fit + validación.
- **Criterio de promovibilidad por corrida** (el enunciado dice «recall cercano o superior a 0,80», «carga compatible» y «precisión suficiente» sin cifras; se fijaron así): recall ≥ 0,75; alertas ≤ 50 % (≤ 40 % deseable); precisión ≥ 0,30 (≈ 1,1–1,5× la prevalencia). Debe cumplirse en **todos** los tamaños.
- **Evidencia estadística:** 10 semillas de partición por tamaño y protocolo; IC95 % t entre semillas; bootstrap por estudiante (400 remuestras); ANOVA entre tamaños; t de una muestra contra 0,80.

| Estudiantes | `dataset_version` (prefijo) | Snapshots | Prevalencia |
|---:|---|---:|---:|
| 5.000 | `a917b077569c` | 27.459 | 21,27 % |
| 10.000 | `443c5cbd0c9e` | 55.105 | 20,86 % |
| 15.000 | `9880f71bd11f` | 83.335 | 20,75 % |
| 25.000 | `30887b1dc3c6` | 139.067 | 20,75 % |
| 50.000 | `15b201d81d2a` | 275.869 | 20,93 % |
| 75.000 | `523102e1b66f` | 416.227 | 20,78 % |
| 100.000 | `fb5d4ccc9fd2` | 553.822 | 20,84 % |

Los Parquet quedaron en un directorio temporal de la sesión (no se versionan). Se regeneran con `SAT_SYNTHETIC_STUDENTS=<n> SAT_MAX_SNAPSHOT_ROWS=<10n> SAT_SYNTHETIC_SEED=42 SAT_OUTPUT_DIR=<dir> python src/data_generation/generate_digital_twin.py`.

## 3. Causas raíz de los comportamientos contradictorios

**C1. Techo de información (la causa principal).** El generador sortea la deserción con un riesgo instantáneo `h` (media 0,107 en los datos) construido con las variables del contrato, y la etiqueta cubre además un sorteo futuro no observable. Reconstruyendo `h` con la fórmula del generador (diagnóstico, nunca usado como feature):

| Estudiantes | AUC oráculo | AUC modelo final (10 semillas) | Brecha media (IC95 %) |
|---:|---:|---:|---:|
| 5.000 | 0,655 | 0,657 | −0,002 (±0,005) |
| 10.000 | 0,673 | 0,668 | +0,004 (±0,006) |
| 15.000 | 0,671 | 0,671 | 0,000 (±0,004) |
| 25.000 | 0,676 | 0,679 | −0,003 (±0,002) |
| 50.000 | 0,663 | 0,664 | −0,001 (±0,001) |
| 75.000 | 0,671 | 0,673 | −0,002 (±0,001) |
| 100.000 | 0,670 | 0,671 | −0,001 (±0,001) |

Incluso el oráculo, con 40 % de alertas, tiene recall 0,58 (50 %: 0,67; 70 %: 0,84). Para recall 0,80 con 40 % de alertas y prevalencia ≈ 0,21 haría falta un AUC ≈ 0,84 (aproximación binormal), frente a 0,67 disponible.

**C2. Etiquetas no estacionarias en los dos últimos periodos.** La prevalencia sube de 19–22 % a 27–30 % en 2025-1/2025-2 mientras el riesgo medio `h` no cambia (0,10–0,11). Según `generate_digital_twin.py` (bloque de seguimiento posterior al último snapshot, líneas ≈ 750–769), esos periodos reciben un sorteo adicional de deserción en la ventana de la etiqueta (≈ 3 sorteos frente a ≈ 2 en periodos anteriores). Efecto: el umbral fijado en validación (prevalencia 0,22–0,25) se desplaza en test (0,27–0,29). Es un artefacto del generador, no un patrón de negocio. En la iteración 2 (§12) se corrigió el generador y la hipótesis se confirmó por intervención.

**C3. Ruido de muestreo con tamaños pequeños.** Con 5k, la validación tiene 418 filas y el test 826. La desviación entre semillas del AUC es 0,018 en 5k y 0,005 en 100k; la de las alertas de la regla recall ≥ 0,80, 0,059 frente a 0,015. Las «contradicciones» entre tamaños (recall 0,69 en 5k, 0,79–0,80 en 10k/15k/100k) están dentro de ese ruido: el oráculo también oscila entre 0,63 y 0,69 en test según el tamaño.

**C4. Regla de umbral frágil.** «Mayor precisión con recall ≥ 0,80 en validación» elige un punto del borde de una curva casi plana, y con `class_weight='balanced'` el umbral absoluto (0,38–0,45) no se transfiere (ECE 0,22). Es la fuente de las alertas de 56–68 % del baseline.

**C5. El 100k previo (precisión 0,87, Brier 0,44).** No se reprodujo: en la configuración actual no hay etiquetas inmaduras en ningún tamaño y el 100k da precisión 0,35 y Brier 0,19. La documentación previa reporta 67.426 etiquetas inmaduras en esa variante; la hipótesis es que el filtrado de etiquetas maduras sesgaba el test, pero **no se probó**. Esa corrida no es comparable con esta.

## 4. Ajustes realizados y su impacto

Todas las cifras son medias sobre los 7 tamaños, semilla 42, protocolo del proyecto (detalle por tamaño en `outputs/recalibration/tablas.md`).

| # | Ajuste | AUC | AUC-PR | Brier | ECE | Recall (regla val.) | Alertas (regla val.) | Recall @40 % | Efecto |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| 0 | Baseline LightGBM del proyecto | 0,653 | 0,430 | 0,234 | 0,207 | 0,762 | 62,3 % | 0,558 | Referencia (XGBoost: AUC 0,646) |
| 1 | + features reconstruidas | 0,658 | 0,438 | 0,233 | 0,206 | 0,790 | 64,8 % | 0,564 | +0,005 AUC |
| 2 | Hiperparámetros (16 configs; elegida: 4 hojas, `min_child=300`, λ=10, con pesos balanceados) | 0,668 | 0,447 | 0,237 | 0,224 | 0,791 | 63,6 % | 0,570 | +0,010 AUC; las 16 configs dan AUC de test 0,655–0,666 (6 tamaños, sin 100k) |
| 3 | Pesos de clase: ninguno / √ / balanceado | 0,666 / 0,667 / 0,668 | 0,446–0,447 | 0,188 / 0,194 / 0,237 | 0,043 / 0,084 / 0,224 | 0,721 / 0,758 / 0,791 | 55 / 60 / 64 % | 0,565–0,571 | No mejora el ranking; solo mueve alertas y empeora calibración |
| 4 | Muestreo (sub/sobremuestreo) | 0,666 | 0,444–0,447 | 0,192–0,240 | 0,072–0,230 | 0,786–0,796 | 63–64 % | 0,564–0,567 | Igual que los pesos |
| 5 | Calibración (sigmoide / isotónica) | 0,666–0,668 | 0,439–0,447 | 0,188 | 0,044–0,047 | 0,691–0,727 | 52–56 % | 0,564–0,570 | Recupera calibración (ECE 0,22 → 0,045); sin ganancia de ranking |
| 6 | Regresión logística (C=0,1) / XGBoost poco profundo | **0,669** / 0,666 | **0,451** / 0,447 | 0,187 / 0,188 | 0,039 / 0,042 | 0,707 / 0,718 | 54 / 55 % | 0,571 / 0,569 | **Elegida**: igual de buena, simple, calibrada y más estable |
| 7 | Política de decisión | — | — | — | — | — | — | — | Ver §6 |

**Honestidad sobre la selección.** Entre las etapas 3–6 las diferencias de AUC (< 0,003) están dentro del ruido entre semillas. La logística se eligió por parsimonia, calibración y menor varianza entre tamaños, **no** por superioridad. La etapa 2 se eligió por métricas de validación; las 3–6 se compararon con promedios de test, porque todas convergen al mismo valor y no hay un ganador cuya elección pudiera sobreajustarse. SMOTE no se probó: las variables categóricas ordinales lo hacen poco apropiado.

**Configuración final (`FINAL_logit_C0.1`):** regresión logística L2 (`C=0,1`), sin pesos de clase ni muestreo, imputación por mediana con indicador de faltante, estandarización, one-hot de categóricas; variables del contrato + 8 transformaciones determinísticas; probabilidades sin calibración adicional (ECE 0,039); política de decisión por **capacidad** (alertar al top-k % por riesgo en cada ciclo).

## 5. Evolución de métricas por tamaño (semilla 42, protocolo del proyecto)

Política de capacidad 40 % (`cap40_topk`):

| Estudiantes | n test | Prev. test | AUC | AUC-PR | Recall | Precisión | F1 | Especificidad | FPR | Alertas |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 5.000 | 826 | 0,285 | 0,633 | 0,418 | 0,536 | 0,382 | 0,446 | 0,655 | 0,345 | 40 % |
| 10.000 | 1.656 | 0,269 | 0,667 | 0,434 | 0,570 | 0,384 | 0,458 | 0,663 | 0,337 | 40 % |
| 15.000 | 2.573 | 0,278 | 0,672 | 0,455 | 0,564 | 0,392 | 0,462 | 0,663 | 0,337 | 40 % |
| 25.000 | 4.255 | 0,276 | 0,688 | 0,473 | 0,599 | 0,413 | 0,489 | 0,676 | 0,324 | 40 % |
| 50.000 | 8.348 | 0,286 | 0,669 | 0,457 | 0,571 | 0,408 | 0,476 | 0,668 | 0,332 | 40 % |
| 75.000 | 12.688 | 0,283 | 0,675 | 0,467 | 0,573 | 0,406 | 0,475 | 0,669 | 0,331 | 40 % |
| 100.000 | 16.880 | 0,280 | 0,677 | 0,453 | 0,584 | 0,409 | 0,481 | 0,672 | 0,328 | 40 % |

Regla original (recall ≥ 0,80 en validación) con el modelo final:

| Estudiantes | Recall | Precisión | F1 | Especificidad | FPR | Alertas |
|---:|---:|---:|---:|---:|---:|---:|
| 5.000 | 0,702 | 0,353 | 0,470 | 0,489 | 0,511 | 56,5 % |
| 10.000 | 0,691 | 0,352 | 0,466 | 0,531 | 0,469 | 52,9 % |
| 15.000 | 0,748 | 0,358 | 0,484 | 0,483 | 0,517 | 58,1 % |
| 25.000 | 0,717 | 0,374 | 0,492 | 0,542 | 0,458 | 52,9 % |
| 50.000 | 0,675 | 0,378 | 0,484 | 0,555 | 0,445 | 51,0 % |
| 75.000 | 0,699 | 0,380 | 0,492 | 0,549 | 0,451 | 52,1 % |
| 100.000 | 0,715 | 0,373 | 0,490 | 0,533 | 0,467 | 53,7 % |

Matriz del baseline, por escala y política `cap50_topk`: `outputs/recalibration/tablas.md`. Matriz consolidada completa (todas las etapas × tamaños × políticas): `outputs/recalibration/matriz_consolidada.csv`.

Figura: `outputs/recalibration/figs/metricas_por_tamano.png`.

## 6. Estabilidad estadística

**Entre semillas (10 por tamaño; capacidad 40 %, protocolo del proyecto).**

| Estudiantes | AUC (IC95 %) | sd AUC | Recall (IC95 %) | sd recall | Precisión (sd) |
|---:|---|---:|---|---:|---|
| 5.000 | 0,657 ± 0,013 | 0,018 | 0,564 ± 0,017 | 0,024 | 0,387 (0,029) |
| 10.000 | 0,668 ± 0,018 | 0,025 | 0,575 ± 0,021 | 0,029 | 0,395 (0,031) |
| 15.000 | 0,671 ± 0,007 | 0,010 | 0,571 ± 0,007 | 0,010 | 0,405 (0,018) |
| 25.000 | 0,679 ± 0,006 | 0,008 | 0,580 ± 0,009 | 0,012 | 0,410 (0,009) |
| 50.000 | 0,664 ± 0,006 | 0,008 | 0,567 ± 0,006 | 0,009 | 0,403 (0,011) |
| 75.000 | 0,673 ± 0,004 | 0,005 | 0,574 ± 0,003 | 0,004 | 0,413 (0,007) |
| 100.000 | 0,671 ± 0,004 | 0,005 | 0,576 ± 0,006 | 0,009 | 0,408 (0,004) |

- **Entre tamaños, el recall a capacidad fija es homogéneo** en el protocolo del proyecto (ANOVA F = 1,15; p = 0,35). La media global es 0,572 ± 0,004 (70 corridas). El AUC sí difiere (F = 2,73; p = 0,02), por la oscilación del oráculo (C3), no por el modelo.
- **La dispersión cae con el tamaño:** sd del recall 0,024 (5k) → 0,009 (100k).
- **Ventana estacionaria** (test 2024-1/2024-2, sin el artefacto C2): AUC 0,654, recall @40 % = 0,575 ± 0,005; hay heterogeneidad entre tamaños (ANOVA p ≈ 10⁻⁹), concentrada en 5k, 15k y 75k, y el AUC cae a 0,629–0,640 en 5k y 15k. La precisión baja a 0,27–0,30 porque la prevalencia de ese test es menor.
- **Contra el objetivo:** recall @40 % frente a 0,80, t de una muestra p ≈ 4·10⁻⁸¹ (protocolo del proyecto) y ≈ 2·10⁻⁷⁰ (ventana estacionaria). La brecha es sistemática, no de muestreo.
- **Bootstrap por estudiante (semilla 42):** alertas necesarias para alcanzar recall 0,80 = 68,6 % (IC95 % 60,9–73,8 %) en 5k, 63,0 % (59,0–68,7) en 10k, 62,3 % (59,6–65,2) en 25k, 63,9 % (62,3–65,7) en 100k. En ningún tamaño el IC baja de 59 %; el límite superior de 50 % queda excluido en todos.

**Regla original, 10 semillas × 7 tamaños (70 corridas por protocolo):** protocolo del proyecto, alertas medias 53,7 % y recall 0,702; solo 5 corridas tienen alertas ≤ 50 %, 3 tienen recall ≥ 0,75 y ninguna ambas. Ventana estacionaria: recall 0,779 con 63,2 % de alertas y precisión 0,26; 0/70 con alertas ≤ 50 %.

**Criterio de promovibilidad (recall ≥ 0,75, alertas ≤ 50 %, precisión ≥ 0,30), corridas que cumplen los tres a la vez:**

| Protocolo | Política | Corridas | Recall ≥ 0,75 | Alertas ≤ 50 % | Precisión ≥ 0,30 | **Los tres** |
|---|---|---:|---:|---:|---:|---:|
| Proyecto | recall ≥ 0,80 en validación | 70 | 3 | 5 | 70 | **0** |
| Proyecto | capacidad 40 % | 70 | 0 | 70 | 70 | **0** |
| Proyecto | capacidad 50 % | 70 | 0 | 59 | 70 | **0** |
| Estacionaria | recall ≥ 0,80 en validación | 70 | 59 | 0 | 1 | **0** |
| Estacionaria | capacidad 40 % | 70 | 0 | 70 | 31 | **0** |
| Estacionaria | capacidad 50 % | 70 | 0 | 47 | 4 | **0** |

Figura: `outputs/recalibration/figs/estabilidad_semillas.png`.

## 7. Curvas Precision–Recall y ROC

`outputs/recalibration/figs/curvas_pr_roc.png` (7 tamaños, semilla 42, y el oráculo agregado en gris discontinuo). Las curvas de 25k–100k se superponen con el oráculo; las de 5k–10k se separan por ruido de muestra. Precisión a recall 0,80 ≈ 0,33–0,36 en todos los tamaños (prevalencia de test ≈ 0,28).

## 8. Análisis de carga operativa

Curva del modelo final en 100k (test, prevalencia 0,28), por cada 1.000 estudiantes evaluados en un ciclo:

| Alertas | Recall | Precisión | Estudiantes alertados | Desertores detectados | Alertas por desertor detectado |
|---:|---:|---:|---:|---:|---:|
| 20 % | 0,342 | 0,478 | 200 | 96 | 2,1 |
| 30 % | 0,470 | 0,438 | 300 | 132 | 2,3 |
| **40 %** | **0,584** | **0,409** | 400 | 164 | 2,4 |
| **50 %** | **0,683** | **0,382** | 500 | 191 | 2,6 |
| 60 % | 0,766 | 0,357 | 600 | 214 | 2,8 |
| 65 % | 0,807 | 0,348 | 650 | 226 | 2,9 |
| 70 % | 0,844 | 0,337 | 700 | 236 | 3,0 |

Para alcanzar recall 0,80 se revisan ≈ 650 de cada 1.000 estudiantes: operativamente inviable según el umbral de 40–50 % del enunciado. Con 40 % se revisan 400 y se pierde el 42 % de los desertores. La precisión no cae por debajo de 0,33 en ningún punto; el cuello de botella es el recall, no la precisión. Estas cifras dependen de la prevalencia de test, inflada por C2 (con prevalencia ≈ 0,21 la precisión sería menor); la capacidad real de intervención de la universidad no está documentada en el repositorio y debe confirmarse.

Figura: `outputs/recalibration/figs/recall_vs_alertas.png`.

## 9. Recomendación sobre despliegue

**No desplegar para priorizar estudiantes.** Con los datos sintéticos actuales:

1. El criterio de promovibilidad no se cumple en ninguna corrida (0/420), y el techo teórico (oráculo) confirma que tampoco se cumpliría con otro algoritmo.
2. Lo que sí está demostrado: la solución es **estable y reproducible**. A capacidad fija el recall es homogéneo entre tamaños (p = 0,35), el modelo está bien calibrado (ECE 0,039) y su dispersión disminuye con el tamaño. Esto la hace apta para seguir desarrollándose, no para decidir sobre estudiantes.
3. Un despliegue **solo de observación** (sombra, sin intervención ni priorización), con política de capacidad, sigue siendo coherente con la nota del proyecto de que es una POC sintética.

## 10. Acciones concretas para llegar a un modelo promovible

1. **Corregir el generador antes de volver a evaluar.** Igualar el número de sorteos de la etiqueta en los periodos finales (C2) o reservar test en periodos estacionarios. Es independiente de los criterios de negocio y elimina el desplazamiento de umbrales.
2. **Aumentar la señal, no afinar hiperparámetros.** Hoy el AUC es 0,67 y se necesita ≈ 0,84 para recall 0,80 con 40 % de alertas. Opciones: etiqueta con menos ruido (horizonte más corto o definida solo con el sorteo del periodo en curso), mayor dispersión del riesgo en el generador, o datos reales. Cualquiera exige decisión del equipo; no se aplicó aquí.
3. **Probar variables de trayectoria (rezagos de las mismas columnas).** No se probaron porque exigirían historia por estudiante en el scoring y el enunciado pedía las mismas variables en el contrato.
4. **Revisar los criterios o definir la capacidad real.** Con 50 % de alertas el techo es recall ≈ 0,67–0,68; con 40 %, ≈ 0,58. Si la universidad puede revisar 40–50 %, un objetivo realista con estos datos es recall 0,57–0,68, no 0,80. Debe decidirlo la universidad con el costo de intervención y el de no intervenir.
5. **Adoptar la política de capacidad (top-k %)** en lugar de «recall ≥ 0,80 en validación»: fija la carga por construcción (sd de alertas = 0) y evita C4.
6. **Antes de cualquier uso real:** validar con datos institucionales bajo un protocolo temporal, revisar fairness por sede/programa/género, monitorear calibración (ECE) y definir aprobación humana, como ya exigen `docs/ProductionReadiness.md` y `docs/AzureFoundryIntegration.md`.

## 11. Limitaciones

- Todos los resultados son sintéticos; el techo del oráculo es una propiedad del generador, no de la deserción real.
- Un único generador y una única semilla de datos por tamaño; la variabilidad entre semillas es solo de partición/muestreo del split (y del ajuste del modelo), no de regeneración del dataset.
- El oráculo reconstruye el riesgo instantáneo desde las columnas (incluye `promedio_semestre`, que no es feature del modelo) y aproxima el efecto del apoyo previo con el snapshot anterior; es una cota práctica, no una cota exacta de Bayes.
- No se reentrenó ni se actualizó `models/*.joblib`; no se tocó el pipeline productivo (`train_pipeline.py`). Los scripts de experimentación son nuevos; el generador solo cambió en §12.
- Las cifras de §1–§11 se obtuvieron con el generador 2.0.0; la explicación de C2 se verificó después, corrigiéndolo (§12).
- La carga operativa se calcula sobre la prevalencia de test (inflada); la capacidad real de la universidad no está en el repositorio.


## 12. Iteración 2: generador corregido, etiqueta con menos ruido y variables de trayectoria

### 12.1 Corrección del generador (acción 1)

- **Defecto:** un sorteo de deserción en el snapshot `q` produce un evento en el periodo `q+1`. El bloque de seguimiento posterior al último snapshot colocaba su primer evento también en `último+1`, duplicando el sorteo del propio último snapshot. Resultado: ≈ 3 sorteos en la ventana de la etiqueta para 2025-1/2025-2 frente a ≈ 2 en el resto.
- **Cambio** ([generate_digital_twin.py](../../src/data_generation/generate_digital_twin.py)): nuevo parámetro `followup_alignment` (`aligned` por defecto; `legacy` conserva el comportamiento anterior). En `aligned`, los eventos de seguimiento se ubican un periodo después del snapshot virtual. `generator_version` pasa a **2.1.0** en [configs/synthetic_data.json](../../configs/synthetic_data.json). Los datasets 2.0.0 se reproducen con `followup_alignment: "legacy"`.
- **Verificación por intervención** (7 tamaños, semilla 42): la prevalencia de 2025-1/2025-2 baja de 0,298/0,271 (5k, legacy) a 0,207/0,202 (5k, corregido). En los 7 tamaños queda entre 0,197 y 0,218, frente a 0,18–0,21 en los demás periodos. Prevalencia global 0,191–0,198. Sin etiquetas inmaduras.
- **Pruebas:** `tests/test_synthetic_generator.py` incluye una prueba de regresión que exige una brecha de prevalencia (últimos dos periodos − anteriores) < 0,04 en `aligned` y > 0,05 en `legacy`; actualicé la versión esperada a 2.1.0. Suite completa: 108 pasan, 1 omitida.

| Estudiantes | `dataset_version` (prefijo, 2.1.0) | Snapshots | Prevalencia | Prev. 2025-1 / 2025-2 |
|---:|---|---:|---:|---|
| 5.000 | `359454cb2e16` | 27.898 | 19,07 % | 0,207 / 0,202 |
| 10.000 | `743112558b4e` | 55.582 | 19,84 % | 0,218 / 0,208 |
| 15.000 | `acdf7581a455` | 83.453 | 19,45 % | 0,210 / 0,197 |
| 25.000 | `20b5676edc69` | 138.268 | 19,72 % | 0,206 / 0,202 |
| 50.000 | `0edb4a7f05be` | 277.042 | 19,59 % | 0,210 / 0,207 |
| 75.000 | `4a5cbc9fe79e` | 415.362 | 19,73 % | 0,213 / 0,210 |
| 100.000 | `1416e8469a6c` | 553.727 | 19,74 % | 0,211 / 0,207 |

### 12.2 Resultados sobre datos corregidos (10 semillas × 7 tamaños; detalle en `outputs/recalibration/v2_generador_corregido/`)

Configuración final (regresión logística, features reconstruidas), política de capacidad 40 %:

| Estudiantes | AUC (media) | Recall (IC95 %) | Precisión | F1 | Alertas | Alertas para recall 0,80 (IC95 % bootstrap, semilla 42) |
|---:|---:|---|---:|---:|---:|---|
| 5.000 | 0,670 | 0,595 ± 0,019 | 0,301 | 0,399 | 40 % | 64,3 % (59,5–69,6) |
| 10.000 | 0,687 | 0,615 ± 0,015 | 0,334 | 0,433 | 40 % | 64,2 % (59,5–70,8) |
| 15.000 | 0,680 | 0,605 ± 0,019 | 0,313 | 0,412 | 40 % | 62,3 % (57,7–66,7) |
| 25.000 | 0,672 | 0,596 ± 0,010 | 0,302 | 0,401 | 40 % | 62,9 % (59,4–67,3) |
| 50.000 | 0,672 | 0,597 ± 0,008 | 0,312 | 0,410 | 40 % | 64,0 % (60,1–66,9) |
| 75.000 | 0,677 | 0,603 ± 0,003 | 0,319 | 0,417 | 40 % | 64,7 % (62,9–67,0) |
| 100.000 | 0,673 | 0,600 ± 0,003 | 0,314 | 0,412 | 40 % | 63,5 % (61,7–65,5) |

- **Homogeneidad entre tamaños:** ANOVA del recall a 40 %: F = 1,55; p = 0,18. Media global 0,601 ± 0,004. La desviación del recall cae de 0,026 (5k) a 0,005 (100k). El AUC apenas rechaza homogeneidad (p = 0,050).
- **Contra el objetivo:** recall frente a 0,80, p ≈ 2·10⁻⁷³.
- **Modelo vs. oráculo (AUC):** brecha +0,007 ± 0,005 (5k), +0,004 ± 0,003 (10k), 0,000 ± 0,003 (15k), −0,002 ± 0,002 (25k) y ≤ 0,001 en valor absoluto en 50k–100k. El modelo queda a ≤ 0,007 del techo; la brecha es pequeña pero significativa en 5k y 10k.
- **Mejora sobre el baseline del proyecto** (diferencias pareadas por tamaño y semilla, n = 21): AUC +0,015 ± 0,005 (p < 0,001); recall a 40 % +0,021 ± 0,007; AUC-PR +0,025 ± 0,008; Brier 0,237 → 0,154. Con la regla de recall ≥ 0,80, las alertas bajan de 62,6 % a 54,2 %.
- **Criterio de promovibilidad** (recall ≥ 0,75, alertas ≤ 50 %, precisión ≥ 0,30); corridas que cumplen cada condición, de 70:

| Política | Recall ≥ 0,75 | Alertas ≤ 50 % | Precisión ≥ 0,30 | **Los tres** |
|---|---:|---:|---:|---:|
| recall ≥ 0,80 en validación | 13 | 6 | 5 | **0** |
| capacidad 40 % | 0 | 70 | 57 | **0** |
| capacidad 50 % | 0 | 55 | 14 | **0** |

La corrección elimina el desplazamiento de umbrales, pero **no mueve el techo**: el oráculo tiene recall 0,60 con 40 % de alertas, 0,69 con 50 % y 0,81 con 65 %, prácticamente igual que con el generador anterior (0,58 / 0,67 / 0,80).

### 12.3 Etiqueta con menos ruido: análisis de sensibilidad (acción 2)

Con la etiqueta redefinida como «deserción en el **siguiente** periodo» (`horizon_periods = 1`, `outcome_followup_periods = 1`, solo para este análisis), 3 tamaños × 5 semillas:

| Estudiantes | Prevalencia | AUC oráculo | AUC modelo | Recall @40 % | Precisión @40 % | Recall @50 % | Precisión @50 % |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 10.000 | 0,114 | 0,681 | 0,676 | 0,618 | 0,176 | 0,714 | 0,163 |
| 25.000 | 0,108 | 0,682 | 0,681 | 0,633 | 0,171 | 0,719 | 0,155 |
| 50.000 | 0,114 | 0,677 | 0,679 | 0,633 | 0,180 | 0,724 | 0,165 |

Acortar el horizonte **no sube el techo** (AUC del oráculo 0,68, igual que con horizonte 2). El recall a 40 % sube a ≈ 0,63, pero la precisión baja a ≈ 0,17 por la menor prevalencia (≈ 0,11), por debajo del umbral de 0,30. El ruido dominante es el sorteo de Bernoulli de un riesgo con poca dispersión (media 0,107), no la parte no observable del futuro. Reducir ese ruido exigiría cambiar la dispersión del riesgo del generador, es decir, ajustar el mundo simulado al modelo; **no se hizo**, porque el resultado no tendría valor como evidencia. La alternativa real es probar con datos institucionales, que no tengo.

### 12.4 Variables de trayectoria (acción 3)

18 variables calculadas por estudiante solo con periodos ≤ actual y las mismas columnas del contrato (rezagos de promedio, mora, apoyo y engagement; acumulados y rachas). Diferencias pareadas frente a la misma configuración sin ellas, con el generador corregido:

| Modelo | n | ΔAUC (IC95 %) | p | ΔRecall @40 % (IC95 %) | p |
|---|---:|---|---:|---|---:|
| Logística | 70 | −0,0013 ± 0,0007 | 0,001 | −0,001 ± 0,002 | 0,31 |
| LightGBM poco profundo | 21 | +0,0002 ± 0,0010 | 0,60 | +0,002 ± 0,003 | 0,15 |

**No aportan señal** (en la logística, incluso empeoran levemente el AUC). Es coherente con el generador: el riesgo del periodo depende casi por completo de variables del propio snapshot; solo el apoyo del periodo anterior entra al riesgo, con un efecto de 0,88×. En datos reales las trayectorias podrían importar; esta simulación no puede mostrarlo. Además exigirían historia por estudiante en el scoring.

### 12.5 Capacidad real de la universidad (acción 4)

**No puedo definirla:** no figura en el repositorio (`docs/Scope.md` y `docs/Vision.md` solo piden evaluarla) y es una decisión de la universidad. Lo que sí puedo dar es la curva que necesita esa decisión: modelo final en 100k, prevalencia 0,20, datos corregidos, semilla 42, por cada 1.000 estudiantes.

| Alertas | Recall | Precisión | Estudiantes revisados | Desertores detectados | Alertas por desertor detectado |
|---:|---:|---:|---:|---:|---:|
| 20 % | 0,363 | 0,363 | 200 | 73 | 2,8 |
| 30 % | 0,485 | 0,323 | 300 | 97 | 3,1 |
| **40 %** | **0,600** | **0,300** | 400 | 120 | 3,3 |
| **50 %** | **0,682** | **0,273** | 500 | 136 | 3,7 |
| 60 % | 0,771 | 0,257 | 600 | 154 | 3,9 |
| 65 % | 0,810 | 0,249 | 650 | 162 | 4,0 |
| 70 % | 0,846 | 0,242 | 700 | 169 | 4,1 |

El oráculo da prácticamente lo mismo en cada fila (0,600 a 40 % y 0,693 a 50 %), así que esta curva es el límite de lo que estos datos permiten. Con 40–50 % de capacidad, el objetivo realista es recall 0,60–0,68, con ≈ 3,3–3,7 estudiantes revisados por cada desertor detectado.

### 12.6 Conclusión de la iteración 2

1. **El generador ya no distorsiona la evaluación**, pero el resultado de fondo no cambia: ninguna de las 210 corridas de la configuración final cumple el criterio de promovibilidad, y el modelo queda a ≤ 0,007 de AUC del techo.
2. **Ni acortar el horizonte ni añadir trayectorias suben el techo** en esta simulación.
3. **Pendiente, y fuera de lo que se puede resolver con estos datos:** validar con datos institucionales y que la universidad fije su capacidad de intervención. Con esa cifra, la curva de §12.5 indica de inmediato qué recall es alcanzable.
