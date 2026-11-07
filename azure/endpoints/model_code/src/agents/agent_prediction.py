import joblib
import pandas as pd
from pathlib import Path
from typing import Dict, Any
from .base_agent import BaseAgent

class AgentPrediction(BaseAgent):
    """
    Agente Predictivo:
    Carga el modelo serializado (LightGBM) o ejecuta scoring por lotes/en tiempo real.
    Produce la probabilidad calibrada de desercion y clasifica el nivel de riesgo.
    """

    def __init__(self, model_path: str = "./outputs/sat_fumc_lightgbm.joblib"):
        super().__init__(name="Agente_Predictivo", role="Scoring y Clasificación de Riesgo")
        self.model_path = Path(model_path)
        self.model = None

    def _load_model(self):
        if self.model is None:
            if not self.model_path.exists():
                # Ruta alternativa
                alt_path = Path("./models/model_champion.joblib")
                if alt_path.exists():
                    self.model_path = alt_path
                else:
                    raise FileNotFoundError(f"No se encontro el modelo serializado en {self.model_path}")
            self.logger.info(f"Cargando modelo campeon desde {self.model_path}...")
            self.model = joblib.load(self.model_path)

    def run(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        self._load_model()
        df: pd.DataFrame = inputs["enriched_df"]
        feature_cols = inputs["feature_cols"]
        threshold = float(inputs.get("threshold", 0.35))
        if not 0 <= threshold <= 1:
            raise ValueError("El umbral de alerta debe estar entre 0 y 1.")
        if df.empty:
            raise ValueError("No hay registros para ejecutar el scoring.")

        model_features = list(getattr(self.model, "feature_names_in_", []))
        if not model_features:
            raise ValueError("El modelo no expone feature_names_in_; no se puede validar su contrato.")
        missing_features = [name for name in model_features if name not in df.columns]
        if missing_features:
            raise ValueError(f"Faltan variables requeridas por el modelo: {missing_features}")

        self.logger.info(f"Ejecutando scoring predictivo para {len(df):,} estudiantes (Threshold={threshold})...")

        X = df[model_features].copy()
        probas = self.model.predict_proba(X)[:, 1]
        if len(probas) != len(df) or not pd.Series(probas).between(0, 1).all():
            raise ValueError("El modelo devolvió probabilidades inválidas o un número inesperado de resultados.")

        predictions = []
        for i, p in enumerate(probas):
            prob = float(p)
            if prob >= 0.75:
                nivel = "Crítico"
            elif prob >= 0.50:
                nivel = "Alto"
            elif prob >= 0.25:
                nivel = "Medio"
            else:
                nivel = "Bajo"

            predictions.append({
                "probabilidad_desercion": round(prob, 4),
                "nivel_riesgo": nivel,
                "alerta_activa": int(prob >= threshold)
            })

        pred_df = pd.DataFrame(predictions)
        scored_df = pd.concat([df.reset_index(drop=True), pred_df], axis=1)

        distribucion = pred_df["nivel_riesgo"].value_counts().to_dict()
        alertas_totales = int(pred_df["alerta_activa"].sum())

        self.metrics = {
            "total_evaluados": len(df),
            "alertas_tempranas_activas": alertas_totales,
            "tasa_alertas": round((alertas_totales / len(df)) * 100, 2),
            "distribucion_riesgo": distribucion
        }

        self.logger.info(f"Scoring finalizado. Alertas activas: {alertas_totales:,} ({self.metrics['tasa_alertas']}%)")

        return {
            "scored_df": scored_df,
            "predictions_summary": pred_df,
            "metrics_prediction": self.metrics,
            "feature_cols": feature_cols
        }
