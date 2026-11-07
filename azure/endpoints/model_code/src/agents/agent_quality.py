import pandas as pd
from typing import Any, Dict
from .base_agent import BaseAgent


class AgentQuality(BaseAgent):
    """Audit the institutional data-quality rules before features or scoring."""

    VARS_PROHIBIDAS = [
        "target_desercion", "reinscrito_t1", "reinscrito_t2", "no_reinscrito_t1",
        "no_reinscrito_t2", "fecha_retiro", "motivo_retiro", "tipo_retiro",
        "causa_no_continuidad", "graduado_hasta_t2", "fecha_graduacion",
        "fecha_egreso", "cumple_requisitos_grado", "transferencia_interna_hasta_t2",
        "aplazamiento_formal_hasta_t2", "estado_academico_t",
        "condicion_academica_cierre", "promedio_final_periodo",
        "estado_financiero_t", "estado_financiero_cierre_periodo",
        "probabilidad_riesgo_simulada", "nivel_riesgo_simulado",
    ]

    def __init__(self):
        super().__init__(name="Agente_Calidad_Datos", role="Validación y Gobierno de Datos")

    @staticmethod
    def _period_order(value: Any) -> tuple[int, int]:
        year, semester = str(value).split("-", maxsplit=1)
        return int(year), int(semester)

    def run(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        df: pd.DataFrame = inputs["main_df"].copy()
        target_df = inputs.get("target_df")
        key_columns = ["id_estudiante_anon", "periodo_id"]
        missing_keys = [column for column in key_columns if column not in df.columns]
        if missing_keys:
            raise ValueError(f"Faltan llaves obligatorias en la tabla principal: {missing_keys}")
        if df.empty:
            raise ValueError("La tabla principal no contiene registros.")
        if target_df is not None:
            target_keys_missing = [
                column for column in [*key_columns, "target_desercion"]
                if column not in target_df.columns
            ]
            if target_keys_missing:
                raise ValueError(f"Faltan campos obligatorios en la tabla target: {target_keys_missing}")

        rules = []
        severities = {
            "PK estudiante-periodo": "crítica",
            "Integridad de sedes": "crítica",
            "Consistencia temporal": "alta",
            "Rangos académicos y porcentajes": "alta",
            "Reglas contables básicas": "media",
            "Catálogos normalizados": "alta",
            "Fecha de corte y ausencia de fuga": "crítica",
            "Faltantes explícitos": "alta",
            "Cobertura histórica de cinco años": "alta",
            "Tablas anexas relacionadas": "alta",
            "Sesgo y equidad": "alta",
            "Desbalance de clases": "alta",
            "Versionado del dataset": "media",
        }

        def add_rule(name: str, passed: bool | None, detail: str) -> None:
            state = "no_evaluable" if passed is None else "cumple" if passed else "no_cumple"
            rules.append({
                "regla": name,
                "severidad": severities[name],
                "cumple": passed,
                "estado": state,
                "detalle": detail,
            })

        null_keys = int(df[key_columns].isna().any(axis=1).sum())
        duplicate_keys = int(df.duplicated(key_columns).sum())
        target_null_keys = (
            int(target_df[key_columns].isna().any(axis=1).sum()) if target_df is not None else 0
        )
        target_duplicates = int(target_df.duplicated(key_columns).sum()) if target_df is not None else 0
        keys_valid = null_keys == 0 and duplicate_keys == 0
        missing_targets = 0
        target_is_valid = True
        if target_df is not None:
            target_values = target_df["target_desercion"]
            target_is_valid = bool(
                target_values.notna().all()
                and set(target_values.unique()).issubset({0, 1})
            )
            target_keys_df = target_df[key_columns].drop_duplicates()
            source_keys_df = df[key_columns].drop_duplicates()
            missing_targets = int(
                (
                    source_keys_df.merge(
                        target_keys_df, on=key_columns, how="left", indicator=True
                    )["_merge"] == "left_only"
                ).sum()
            )
            keys_valid = (
                keys_valid
                and target_null_keys == 0
                and target_duplicates == 0
                and target_is_valid
                and missing_targets == 0
            )
        add_rule(
            "PK estudiante-periodo",
            keys_valid,
            (
                f"tabla principal: {null_keys} llaves nulas, {duplicate_keys} duplicadas; "
                f"target: {target_null_keys} llaves nulas, {target_duplicates} duplicadas, "
                f"{missing_targets} sin correspondencia, binario válido={target_is_valid}"
                if target_df is not None
                else f"tabla principal: {null_keys} llaves nulas, {duplicate_keys} duplicadas; target no requerido"
            ),
        )

        expected_sites = inputs.get("catalogos", {}).get("catalogos_sedes.parquet")
        observed_sites = set(df["sede"].dropna().astype(str)) if "sede" in df else set()
        missing_sites = sorted(set(expected_sites or []) - observed_sites) if expected_sites is not None else []
        site_nulls = int(df["sede"].isna().sum()) if "sede" in df else len(df)
        sites_valid = site_nulls == 0 and not missing_sites
        add_rule(
            "Integridad de sedes",
            sites_valid if expected_sites is not None else (False if site_nulls else None),
            f"{site_nulls} valores vacíos; sedes faltantes del catálogo: {missing_sites}"
            if expected_sites is not None
            else f"{site_nulls} valores vacíos; catálogo maestro no disponible",
        )

        if "cohorte_ingreso" in df and "periodo_id" in df:
            try:
                invalid_temporal = sum(
                    self._period_order(cohort) > self._period_order(period)
                    for cohort, period in zip(df["cohorte_ingreso"], df["periodo_id"])
                )
                add_rule(
                    "Consistencia temporal",
                    invalid_temporal == 0,
                    f"{invalid_temporal} cohortes posteriores al periodo observado",
                )
            except (TypeError, ValueError):
                add_rule("Consistencia temporal", False, "Formato de cohorte o periodo no válido")
        else:
            add_rule("Consistencia temporal", None, "Faltan cohorte_ingreso o periodo_id")

        ranges = {
            "promedio_semestre": (0.0, 5.0),
            "promedio_semestre_anterior": (0.0, 5.0),
            "promedio_acumulado": (0.0, 5.0),
            "mejor_promedio_hist": (0.0, 5.0),
            "peor_promedio_hist": (0.0, 5.0),
            "avance_plan_pct": (0.0, 100.0),
            "tasa_aprobacion": (0.0, 1.0),
            "intensidad_perdida": (0.0, 1.0),
            "creditos_inscritos": (0.0, None),
            "creditos_aprobados": (0.0, None),
            "creditos_reprobados": (0.0, None),
        }
        invalid_ranges = {}
        for column, (minimum, maximum) in ranges.items():
            if column not in df:
                continue
            values = pd.to_numeric(df[column], errors="coerce")
            invalid = values.notna()
            if minimum is not None:
                invalid &= values < minimum
            if maximum is not None:
                invalid |= values.notna() & (values > maximum)
            invalid_ranges[column] = int(invalid.sum())
            if invalid.any():
                df[column] = values.mask(invalid)
        range_errors = {name: count for name, count in invalid_ranges.items() if count}
        add_rule(
            "Rangos académicos y porcentajes",
            not range_errors,
            f"valores fuera de rango marcados como faltantes: {range_errors or 'ninguno'}",
        )

        credit_columns = ["creditos_aprobados", "creditos_reprobados", "creditos_inscritos"]
        if all(column in df for column in credit_columns):
            inconsistent_credits = int(
                (
                    df["creditos_aprobados"].fillna(0)
                    + df["creditos_reprobados"].fillna(0)
                    > df["creditos_inscritos"].fillna(0)
                ).sum()
            )
            add_rule(
                "Reglas contables básicas",
                inconsistent_credits == 0,
                f"{inconsistent_credits} filas exceden créditos inscritos (revisar homologaciones)",
            )
        else:
            add_rule("Reglas contables básicas", None, "Faltan columnas de créditos")

        catalogs = inputs.get("catalogos", {})
        catalog_checks = {
            "programa": catalogs.get("catalogos_programas.parquet"),
            "sede": catalogs.get("catalogos_sedes.parquet"),
        }
        catalog_errors = {}
        for column, expected in catalog_checks.items():
            if expected is not None and column in df:
                unknown = sorted(set(df[column].dropna().astype(str)) - set(expected))
                if unknown:
                    catalog_errors[column] = unknown
        uncatalogued = [
            column for column in ("modalidad", "jornada", "genero", "tipo_financiacion", "plan_estudios_id")
            if column in df and column not in catalog_checks
        ]
        if catalog_errors:
            add_rule("Catálogos normalizados", False, f"valores sin equivalencia: {catalog_errors}")
        elif uncatalogued:
            add_rule(
                "Catálogos normalizados",
                None,
                f"programa/sede verificables; faltan catálogos maestros para: {uncatalogued}",
            )
        elif any(expected is not None for expected in catalog_checks.values()):
            add_rule("Catálogos normalizados", True, "valores de programa y sede coinciden con catálogos")
        else:
            add_rule("Catálogos normalizados", None, "Catálogos maestros no disponibles")

        leak_columns = [
            column for column in df.columns
            if any(token in str(column).lower() for token in self.VARS_PROHIBIDAS)
        ]
        if leak_columns:
            df = df.drop(columns=leak_columns)
            self.logger.warning("Variables de desenlace excluidas: %s", leak_columns)
        add_rule(
            "Fecha de corte y ausencia de fuga",
            None,
            (
                f"columnas post-evento excluidas preventivamente: {leak_columns}; "
                "no hay metadatos de disponibilidad temporal por predictor"
                if leak_columns
                else "sin columnas de desenlace; fecha de disponibilidad por predictor no declarada"
            ),
        )

        predictor_nulls = {
            str(column): int(df[column].isna().sum())
            for column in df.columns
            if df[column].isna().any()
        }
        undocumented_nulls = [
            column for column, count in predictor_nulls.items()
            if count and f"{column}_missing_reason" not in df.columns
        ]
        add_rule(
            "Faltantes explícitos",
            not undocumented_nulls if predictor_nulls else True,
            (
                f"faltantes sin codificación de motivo: {undocumented_nulls}"
                if undocumented_nulls else "sin faltantes o con codificación de motivo"
            ),
        )

        periods = df["periodo_id"].dropna().astype(str).unique().tolist()
        try:
            ordered_periods = sorted(periods, key=self._period_order)
            years = sorted({self._period_order(period)[0] for period in ordered_periods})
            expected_periods = {
                f"{year}-{semester}" for year in range(years[0], years[-1] + 1)
                for semester in (1, 2)
            } if years else set()
            missing_periods = sorted(expected_periods - set(periods), key=self._period_order)
            history_ok = len(years) >= 5 and not missing_periods
            add_rule(
                "Cobertura histórica de cinco años",
                history_ok,
                f"{len(years)} años observados; periodos faltantes: {missing_periods}",
            )
        except (TypeError, ValueError):
            add_rule("Cobertura histórica de cinco años", False, "Periodos con formato no válido")

        related_tables = inputs.get("related_tables", {})
        source_keys = set(map(tuple, df[key_columns].dropna().drop_duplicates().itertuples(index=False, name=None)))
        foreign_key_errors = {}
        for name, table in related_tables.items():
            if not all(column in table for column in key_columns):
                foreign_key_errors[name] = "faltan columnas llave"
                continue
            related_keys = set(
                map(tuple, table[key_columns].dropna().drop_duplicates().itertuples(index=False, name=None))
            )
            foreign_key_errors[name] = int(len(related_keys - source_keys))
        if related_tables:
            foreign_key_errors = {
                name: issue for name, issue in foreign_key_errors.items()
                if issue != 0
            }
            add_rule(
                "Tablas anexas relacionadas",
                not foreign_key_errors,
                f"tablas verificadas: {len(related_tables)}; problemas: {foreign_key_errors or 'ninguno'}",
            )
        else:
            add_rule("Tablas anexas relacionadas", None, "No se recibieron tablas anexas")

        add_rule("Sesgo y equidad", None, "Requiere predicciones y etiquetas; se calcula durante la evaluación del modelo")

        if target_df is None:
            add_rule("Desbalance de clases", None, "No hay target; verificación solo aplica al entrenamiento")
            target_coverage = None
        else:
            target_values = target_df["target_desercion"]
            valid_target = target_values.notna().all() and set(target_values.unique()).issubset({0, 1})
            target_counts = target_values.value_counts().to_dict()
            target_coverage = {
                "clases": {str(key): int(value) for key, value in target_counts.items()},
                "registros_sin_target": missing_targets,
            }
            add_rule(
                "Desbalance de clases",
                bool(valid_target and len(target_counts) == 2),
                f"proporción por clase: {target_coverage['clases']}",
            )

        dataset_version = inputs.get("metrics_ingestion", {}).get("dataset_version")
        add_rule(
            "Versionado del dataset",
            bool(dataset_version) if dataset_version else None,
            f"snapshot: {dataset_version}" if dataset_version else "No se proporcionó ID de snapshot",
        )

        blocking_failures = [
            rule["regla"] for rule in rules
            if rule["cumple"] is False
            and rule["regla"] in {"PK estudiante-periodo", "Integridad de sedes"}
        ]
        if blocking_failures:
            raise ValueError("Fallaron validaciones críticas de calidad: " + "; ".join(blocking_failures))

        evaluable_rules = [rule for rule in rules if rule["cumple"] is not None]
        compliance = (
            sum(rule["cumple"] is True for rule in evaluable_rules) / len(evaluable_rules)
            if evaluable_rules else 0.0
        )
        self.metrics = {
            "tasa_cumplimiento_calidad": round(compliance * 100, 2),
            "reglas_auditadas": len(rules),
            "reglas_evaluables": len(evaluable_rules),
            "reglas_no_evaluables": sum(rule["cumple"] is None for rule in rules),
            "fuga_detectada": bool(leak_columns),
            "faltantes_por_columna": predictor_nulls,
            "target": target_coverage,
            "dataset_version": dataset_version,
        }

        self.logger.info(
            "Auditoría completada: %s/%s reglas evaluables cumplidas.",
            sum(rule["cumple"] is True for rule in evaluable_rules),
            len(evaluable_rules),
        )
        return {
            "clean_df": df,
            "target_df": target_df,
            "quality_report": rules,
            "metrics_quality": self.metrics,
            "related_tables": related_tables,
        }
