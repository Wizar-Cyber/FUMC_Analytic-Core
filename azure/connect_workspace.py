"""
=============================================================================
SAT-FUMC: Conector y Verificador de Workspace Azure Machine Learning / Foundry
=============================================================================
Lee la configuracion institucional de 'config.json':
  - Subscription ID: 1e396bfa-74b2-482c-90bd-7139f55f6204
  - Resource Group: reiberdavidlozanoromero-rg
  - Workspace Name: FUMC_Analytics_Core
=============================================================================
"""
import json
import os
from pathlib import Path
from azure.identity import DefaultAzureCredential
from azure.ai.ml import MLClient

CONFIG_PATH = Path(__file__).parent.parent / "config.json"

def get_ml_client():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as config_file:
            cfg = json.load(config_file)
    else:
        cfg = {}

    cfg = {
        "subscription_id": os.getenv("AZURE_SUBSCRIPTION_ID", cfg.get("subscription_id")),
        "resource_group": os.getenv("AZURE_RESOURCE_GROUP", cfg.get("resource_group")),
        "workspace_name": os.getenv("AZUREML_WORKSPACE_NAME", cfg.get("workspace_name")),
    }
    missing = [key for key, value in cfg.items() if not value]
    if missing:
        raise ValueError(
            "Falta la configuración Azure requerida: "
            + ", ".join(missing)
            + ". Defina variables de entorno o configure config.json."
        )

    credential = DefaultAzureCredential()
    ml_client = MLClient(
        credential=credential,
        subscription_id=cfg["subscription_id"],
        resource_group_name=cfg["resource_group"],
        workspace_name=cfg["workspace_name"]
    )
    return ml_client, cfg

if __name__ == "__main__":
    client, config = get_ml_client()
    client.workspaces.get(config["workspace_name"])
    print("[OK] Autenticación y acceso al workspace de Azure ML confirmados.")
