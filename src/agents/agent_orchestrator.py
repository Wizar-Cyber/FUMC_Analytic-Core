import json
from typing import Dict, Any
from pathlib import Path
from .base_agent import BaseAgent
from .agent_ingestion import AgentIngestion
from .agent_quality import AgentQuality
from .agent_feature_engineer import AgentFeatureEngineer
from .agent_prediction import AgentPrediction
from .agent_explainability import AgentExplainability
from .agent_monitoring import AgentMonitoring
from dashboards.render_summary import render_dashboard

class AgentOrchestrator(BaseAgent):
    """
    Agente Coordinador:
    Orquesta secuencialmente el flujo de trabajo multiagente:
      Ingesta -> Calidad -> Features -> Prediccion -> Explicabilidad -> Monitoreo.
    Genera el reporte consolidado y exporta resultados para consumo de la plataforma.
    """

    def __init__(self, model_path: str = "./outputs/sat_fumc_lightgbm.joblib"):
        super().__init__(name="Agente_Coordinador", role="Orquestador General del Sistema")
        self.ingestion = AgentIngestion()
        self.quality = AgentQuality()
        self.feature_eng = AgentFeatureEngineer()
        self.prediction = AgentPrediction(model_path=model_path)
        self.explainability = AgentExplainability()
        self.monitoring = AgentMonitoring()

    def run(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        self.logger.info("=" * 60)
        self.logger.info("INICIANDO EJECUCIÓN DE LA RED MULTI-AGENTE SAT-FUMC")
        self.logger.info("=" * 60)

        # 1. Ingesta
        out_ingest = self.ingestion.run(inputs)

        # 2. Calidad de Datos
        out_quality = self.quality.run(out_ingest)

        # 3. Ingenieria de Caracteristicas
        out_features = self.feature_eng.run(out_quality)

        # 4. Prediccion y Scoring
        inputs_pred = {**out_features, "threshold": inputs.get("threshold", 0.35)}
        out_pred = self.prediction.run(inputs_pred)

        # 5. Explicabilidad e Intervenciones
        out_expl = self.explainability.run(out_pred)

        # 6. Monitoreo y Supervisión
        out_mon = self.monitoring.run(out_expl)

        # Consolidacion de resultados
        final_df = out_mon["final_df"]
        output_dir = Path(inputs.get("output_dir", "./outputs"))
        output_dir.mkdir(parents=True, exist_ok=True)

        # Guardar el dataset consolidado para consumo de la plataforma.
        export_cols = [
            "id_estudiante_anon", "periodo_id", "programa", "sede", "jornada", "modalidad",
            "estrato_socioeconomico", "semestres_cursados", "probabilidad_desercion",
            "nivel_riesgo", "alerta_activa", "factor_riesgo_principal", "intervencion_sugerida"
        ]
        available_cols = [c for c in export_cols if c in final_df.columns]
        predictions_df = final_df[available_cols]

        predictions_df.to_parquet(output_dir / "predicciones_estudiante_periodo.parquet", index=False)
        predictions_df.to_csv(output_dir / "predicciones_estudiante_periodo.csv", index=False)
        render_dashboard(predictions_df, output_dir / "dashboard_resumen.html")

        resumen_ejecucion = {
            "ingesta": self.ingestion.metrics,
            "calidad": {
                **self.quality.metrics,
                "detalle_reglas": out_quality["quality_report"],
            },
            "caracteristicas": self.feature_eng.metrics,
            "prediccion": self.prediction.metrics,
            "explicabilidad": self.explainability.metrics,
            "monitoreo": self.monitoring.metrics,
        }

        with open(output_dir / "reporte_ejecucion_multiagente.json", "w", encoding="utf-8") as f:
            json.dump(resumen_ejecucion, f, indent=2, ensure_ascii=False)

        self.logger.info("=" * 60)
        self.logger.info("RED MULTI-AGENTE FINALIZÓ EXITOSAMENTE")
        self.logger.info(f"Resultados exportados a: {output_dir}")
        self.logger.info("=" * 60)

        return {
            "final_df": final_df,
            "summary_report": resumen_ejecucion
        }
