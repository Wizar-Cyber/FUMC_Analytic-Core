import pandas as pd
from typing import Dict, Any
from .base_agent import BaseAgent

class AgentMonitoring(BaseAgent):
    """
    Agente de Monitoreo:
    Resume niveles de riesgo por grupo. Drift y equidad requieren una línea base
    versionada y etiquetas observadas, por lo que no se infieren de una sola corrida.
    """

    def __init__(self):
        super().__init__(name="Agente_Monitoreo", role="Supervisión MLOps y Equidad")

    def run(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        df: pd.DataFrame = inputs["final_df"]
        self.logger.info("Monitoreando distribucion de predicciones y equidad institucional...")

        if df.empty:
            raise ValueError("No se pueden monitorear predicciones vacías.")
        if "nivel_riesgo" not in df:
            raise ValueError("Falta la columna nivel_riesgo para generar el reporte de monitoreo.")

        # Tasas de riesgo por sede
        tasa_riesgo_sede = {}
        if "sede" in df.columns:
            for s, sub in df.groupby("sede"):
                tasa = (sub["nivel_riesgo"].isin(["Alto", "Crítico"])).mean()
                tasa_riesgo_sede[str(s)] = round(float(tasa) * 100, 2)

        # Tasas de riesgo por programa
        tasa_riesgo_programa = {}
        if "programa" in df.columns:
            for p, sub in df.groupby("programa"):
                tasa = (sub["nivel_riesgo"].isin(["Alto", "Crítico"])).mean()
                tasa_riesgo_programa[str(p)] = round(float(tasa) * 100, 2)

        tasa_global_alta = float(df["nivel_riesgo"].isin(["Alto", "Crítico"]).mean())

        self.metrics = {
            "tasa_global_riesgo_alto": round(float(tasa_global_alta) * 100, 2),
            "riesgo_por_sede": tasa_riesgo_sede,
            "riesgo_por_programa": tasa_riesgo_programa,
            "deriva_evaluable": False,
            "equidad_evaluable": False,
            "equidad_motivo": "Se requieren etiquetas observadas y métricas por grupo.",
            "estado_salud_modelo": "Sin línea base de deriva; requiere monitoreo temporal"
        }

        self.logger.info(f"Monitoreo finalizado. Estado de salud: {self.metrics['estado_salud_modelo']}")

        return {
            "monitoring_report": self.metrics,
            "final_df": df
        }
