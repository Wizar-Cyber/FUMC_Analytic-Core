import pandas as pd
import numpy as np
from typing import Dict, Any, List
from .base_agent import BaseAgent

class AgentExplainability(BaseAgent):
    """
    Agente de Explicabilidad y Recomendacion:
    Identifica los factores criticos causantes del riesgo y asigna de manera automatizada
    la intervencion focalizada correspondiente dentro de los 4 pilares de 'Te quiero en la U':
      - Acogida
      - Apoyo Psicoeducativo
      - Apoyo Socioeconomico
      - Graduacion e Insercion
    """

    INTERVENCIONES = {
        "mora": "Apoyo socioeconómico — Acuerdo de financiación o gestión de beca",
        "prueba": "Tutoría de permanencia — Acompañamiento tutorial urgente",
        "lms": "Fase de acogida — Contacto para reconexión con plataforma virtual",
        "promedio": "Apoyo psicoeducativo — Métodos de estudio y refuerzo en materias críticas",
        "bienestar": "Vinculación preventiva al programa 'Te quiero en la U'",
        "vulnerable": "Atención integral — Apoyo de bienestar universitario",
        "regular": "Seguimiento preventivo regular"
    }

    def __init__(self):
        super().__init__(name="Agente_Explicabilidad", role="Interpretabilidad e Intervención Focalizada")

    def run(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        df: pd.DataFrame = inputs["scored_df"]
        self.logger.info("Generando explicaciones de riesgo y recomendando intervenciones de 'Te quiero en la U'...")

        intervenciones_asignadas = []
        factores_principales = []

        for idx, row in df.iterrows():
            prob = row.get("probabilidad_desercion", 0.0)
            nivel = row.get("nivel_riesgo", "Bajo")

            if nivel in ["Alto", "Crítico"]:
                if row.get("saldo_mora", 0) > 400_000 or row.get("bloqueo_financiero", 0) == 1:
                    factor = "Mora financiera activa"
                    accion = self.INTERVENCIONES["mora"]
                elif row.get("en_prueba_academica_actual", 0) == 1 or row.get("historial_prueba_academica", 0) == 1:
                    factor = "Bajo rendimiento / Prueba académica"
                    accion = self.INTERVENCIONES["prueba"]
                elif row.get("engagement_lms", 1.0) < 0.35 or row.get("desconexion_lms", 0) == 1:
                    factor = "Desconexión de plataforma virtual"
                    accion = self.INTERVENCIONES["lms"]
                elif row.get("promedio_acumulado", 4.0) < 3.2:
                    factor = "Promedio acumulado en zona de riesgo"
                    accion = self.INTERVENCIONES["promedio"]
                elif row.get("asistio_tquieroenlaU", 1) == 0:
                    factor = "Falta de participación en bienestar"
                    accion = self.INTERVENCIONES["bienestar"]
                else:
                    factor = "Vulnerabilidad académica y socioeconómica"
                    accion = self.INTERVENCIONES["vulnerable"]
            elif nivel == "Medio":
                factor = "Alerta temprana moderada"
                accion = "Contacto preventivo del consejero estudiantil"
            else:
                factor = "Rendimiento y vinculación estable"
                accion = self.INTERVENCIONES["regular"]

            factores_principales.append(factor)
            intervenciones_asignadas.append(accion)

        df["factor_riesgo_principal"] = factores_principales
        df["intervencion_sugerida"] = intervenciones_asignadas

        # Resumen de intervenciones prioritarias
        top_intervenciones = pd.Series(intervenciones_asignadas).value_counts().to_dict()

        self.metrics = {
            "estudiantes_con_plan_intervencion": len(df),
            "intervenciones_urgentes": sum(1 for n in df["nivel_riesgo"] if n in ["Alto", "Crítico"]),
            "tipo_explicacion": "heuristica_de_reglas_de_negocio",
            "distribucion_intervenciones": top_intervenciones
        }

        self.logger.info(f"Intervenciones generadas. Casos criticos/altos asignados: {self.metrics['intervenciones_urgentes']:,}")

        return {
            "final_df": df,
            "metrics_explainability": self.metrics
        }
