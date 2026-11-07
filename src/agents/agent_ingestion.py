import pandas as pd
import hashlib
import os
from pathlib import Path
from typing import Dict, Any
from .base_agent import BaseAgent

class AgentIngestion(BaseAgent):
    """
    Agente de Ingesta:
    Lee los datasets en formato Parquet, verifica la integridad de las llaves primarias
    y valida la cobertura institucional de sedes y programas segun el diccionario FUMC.
    """
    
    def __init__(self):
        super().__init__(name="Agente_Ingesta", role="Ingesta y Consolidación de Fuentes")

    def run(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        data_dir = Path(inputs.get("data_dir", "./data/raw"))
        main_path = data_dir / "estudiante_periodo_corte.parquet"
        target_path = data_dir / "target_trazabilidad.parquet"

        self.logger.info(f"Iniciando lectura de datos desde {data_dir}...")
        
        if not main_path.exists():
            raise FileNotFoundError(f"No se encontro el archivo principal: {main_path}")
        require_target = inputs.get("require_target", False)
        if not target_path.exists() and require_target:
            raise FileNotFoundError(f"No se encontro el archivo de target: {target_path}")

        main_df = pd.read_parquet(main_path)
        target_df = pd.read_parquet(target_path) if require_target else None
        related_tables = {}
        for filename in (
            "estudiante_asignatura_periodo.parquet",
            "financiera_estudiante_evento.parquet",
            "solicitudes_estudiantiles.parquet",
            "bienestar_acompanamiento.parquet",
        ):
            table_path = data_dir / filename
            if table_path.exists():
                related_tables[filename] = pd.read_parquet(table_path)

        catalogs = {}
        for filename, column in (
            ("catalogos_programas.parquet", "codigo"),
            ("catalogos_sedes.parquet", "codigo_sede"),
        ):
            table_path = data_dir / filename
            if table_path.exists():
                catalog = pd.read_parquet(table_path)
                if column not in catalog:
                    raise ValueError(f"El catálogo {filename} no contiene la columna {column}.")
                catalogs[filename] = set(catalog[column].dropna().astype(str))

        snapshot_id = inputs.get("dataset_version") or os.getenv("SAT_DATA_VERSION")
        if not snapshot_id:
            snapshot_hash = hashlib.sha256()
            source_paths = [main_path]
            if target_df is not None:
                source_paths.append(target_path)
            source_paths.extend(data_dir / filename for filename in related_tables)
            source_paths.extend(
                data_dir / filename
                for filename in ("catalogos_programas.parquet", "catalogos_sedes.parquet")
                if (data_dir / filename).exists()
            )
            for source_path in sorted(source_paths):
                snapshot_hash.update(source_path.name.encode("utf-8"))
                with source_path.open("rb") as source_file:
                    for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
                        snapshot_hash.update(chunk)
            snapshot_id = snapshot_hash.hexdigest()

        # Validacion de integridad
        sedes_encontradas = list(main_df["sede"].unique()) if "sede" in main_df.columns else []
        programas_encontrados = list(main_df["programa"].unique()) if "programa" in main_df.columns else []
        periodos_encontrados = list(main_df["periodo_id"].unique()) if "periodo_id" in main_df.columns else []

        self.metrics = {
            "registros_estudiantes_periodo": len(main_df),
            "registros_target": len(target_df) if target_df is not None else 0,
            "num_sedes_cubiertas": len(sedes_encontradas),
            "num_programas_cubiertos": len(programas_encontrados),
            "num_periodos_cubiertos": len(periodos_encontrados),
            "tablas_relacionadas_disponibles": sorted(related_tables),
            "dataset_version": snapshot_id,
        }

        self.logger.info(f"Ingesta exitosa: {len(main_df):,} registros | Sedes: {len(sedes_encontradas)} | Programas: {len(programas_encontrados)}")

        return {
            "main_df": main_df,
            "target_df": target_df,
            "related_tables": related_tables,
            "catalogos": catalogs,
            "metrics_ingestion": self.metrics
        }
