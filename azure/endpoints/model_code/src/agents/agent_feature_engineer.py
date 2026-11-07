import pandas as pd
from typing import Dict, Any, List
from .base_agent import BaseAgent
from src.ml.feature_engineering import engineer_features, feature_columns

class AgentFeatureEngineer(BaseAgent):
    """
    Agente de Ingenieria de Caracteristicas:
    Calcula variables relacionales e indicadores de riesgo definidos en el diccionario FUMC:
      - Interacciones entre situacion financiera y desempeño academico
      - Scores de engagement en plataforma virtual
      - Flags de vulnerabilidad multidimensional
    """

    def __init__(self):
        super().__init__(name="Agente_Ingenieria_Caracteristicas", role="Transformación y Enriquecimiento de Datos")

    def run(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        df: pd.DataFrame = inputs["clean_df"].copy()
        self.logger.info("Construyendo variables compuestas y relacionales de riesgo...")
        df = engineer_features(df)
        active_num, active_cat = feature_columns(df)
        total_features = active_num + active_cat

        self.metrics = {
            "num_variables_generadas": len(total_features),
            "variables_numericas": len(active_num),
            "variables_categoricas": len(active_cat)
        }

        self.logger.info(f"Ingenieria de variables finalizada. Total features: {len(total_features)}")

        return {
            "enriched_df": df,
            "feature_cols": total_features,
            "numeric_cols": active_num,
            "categorical_cols": active_cat,
            "target_df": inputs.get("target_df"),
            "metrics_features": self.metrics
        }
