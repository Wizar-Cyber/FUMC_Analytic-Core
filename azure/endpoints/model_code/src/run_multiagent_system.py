"""
=============================================================================
SAT-FUMC: Ejecutor Principal de Pruebas Multi-Agente
=============================================================================
Ejecuta la orquestacion de todos los agentes:
  1. Agente Ingestor
  2. Agente Calidad de Datos (Reglas del Diccionario FUMC)
  3. Agente Feature Engineer (Variables de Negocio)
  4. Agente Predictivo (Scoring con LightGBM)
  5. Agente Explicabilidad (Mapeo de 'Te quiero en la U')
  6. Agente Monitoreo (Equidad institucional y alertas)
=============================================================================
"""
import sys
import argparse
from pathlib import Path

# Agregar src al path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents.agent_orchestrator import AgentOrchestrator

def parse_args():
    parser = argparse.ArgumentParser(description="Ejecutar el flujo multiagente SAT-FUMC.")
    parser.add_argument("--data_dir", default="./data/raw", help="Directorio con Parquet de entrada.")
    parser.add_argument("--output_dir", default="./outputs", help="Directorio para resultados.")
    parser.add_argument(
        "--model_path",
        default="./outputs/sat_fumc_lightgbm.joblib",
        help="Ruta local o montada al pipeline sklearn serializado.",
    )
    parser.add_argument("--threshold", type=float, default=0.35, help="Umbral de activación de alertas.")
    parser.add_argument(
        "--require_target",
        action="store_true",
        help="Exigir target_trazabilidad.parquet (solo para evaluaciones con etiquetas).",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if not 0 <= args.threshold <= 1:
        raise ValueError("--threshold debe estar entre 0 y 1.")
    print("=" * 70)
    print("SISTEMA DE ALERTA TEMPRANA - FUNDACIÓN UNIVERSITARIA MARÍA CANO")
    print("Prueba de Ejecución Integral de la Red Multi-Agente")
    print("=" * 70)

    orchestrator = AgentOrchestrator(model_path=args.model_path)

    inputs = {
        "data_dir": args.data_dir,
        "output_dir": args.output_dir,
        "threshold": args.threshold,
        "require_target": args.require_target,
    }

    results = orchestrator.run(inputs)

    summary = results["summary_report"]
    print("\n" + "-" * 50)
    print("RESUMEN DE PRUEBAS MULTI-AGENTE:")
    print("-" * 50)
    print(f"1. Ingesta:        {summary['ingesta']['registros_estudiantes_periodo']:,} registros analizados.")
    print(f"2. Calidad:        {summary['calidad']['tasa_cumplimiento_calidad']}% cumplimiento de reglas.")
    print(f"3. Features:       {summary['caracteristicas']['num_variables_generadas']} variables calculadas.")
    print(f"4. Prediccion:     {summary['prediccion']['alertas_tempranas_activas']:,} alertas tempranas generadas.")
    print(f"5. Explicabilidad: {summary['explicabilidad']['intervenciones_urgentes']:,} planes de intervencion asignados.")
    print(f"6. Monitoreo:      Estado de salud -> {summary['monitoreo']['estado_salud_modelo']}")
    print("-" * 50)
    print("\nArchivos listos para visualizacion en Power BI:")
    print(f"  -> {Path(args.output_dir) / 'predicciones_multiagente_powerbi.parquet'}")
    print(f"  -> {Path(args.output_dir) / 'predicciones_multiagente_powerbi.csv'}")
    print(f"  -> {Path(args.output_dir) / 'dashboard_resumen.html'}")
    print(f"  -> {Path(args.output_dir) / 'reporte_ejecucion_multiagente.json'}")

if __name__ == "__main__":
    main()
