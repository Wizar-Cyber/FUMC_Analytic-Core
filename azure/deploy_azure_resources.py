import os
import sys
import json
from pathlib import Path
from azure.identity import AzureCliCredential, DefaultAzureCredential, ClientSecretCredential
from azure.ai.ml import MLClient
from azure.ai.ml.entities import (
    Model,
    Environment,
    ManagedOnlineEndpoint,
    ManagedOnlineDeployment,
    Data
)
from azure.ai.ml.constants import AssetTypes

ROOT_DIR = Path(__file__).parent.parent
CONFIG_PATH = ROOT_DIR / "config.json"

def get_authenticated_client():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # 1. Intentar con credenciales de entorno si existen
    if "AZURE_TENANT_ID" in os.environ and "AZURE_CLIENT_ID" in os.environ and "AZURE_CLIENT_SECRET" in os.environ:
        print("Usando ClientSecretCredential desde variables de entorno...")
        cred = ClientSecretCredential(
            tenant_id=os.environ["AZURE_TENANT_ID"],
            client_id=os.environ["AZURE_CLIENT_ID"],
            client_secret=os.environ["AZURE_CLIENT_SECRET"]
        )
    else:
        print("Usando DefaultAzureCredential (Azure CLI / Visual Studio / az login)...")
        cred = DefaultAzureCredential()

    client = MLClient(
        credential=cred,
        subscription_id=cfg["subscription_id"],
        resource_group_name=cfg["resource_group"],
        workspace_name=cfg["workspace_name"]
    )
    return client, cfg

def deploy():
    print("=" * 70)
    print("DESPLIEGUE SAT-FUMC EN MICROSOFT FOUNDRY / AZURE MACHINE LEARNING")
    print("=" * 70)

    ml_client, cfg = get_authenticated_client()

    print(f"\n[1/4] Verificando acceso al Workspace '{cfg['workspace_name']}'...")
    ws = ml_client.workspaces.get(cfg["workspace_name"])
    print(f"      Conectado exitosamente en región: {ws.location}")

    # 1. Registrar Dataset (Data Asset)
    print("\n[2/4] Registrando Data Asset en Azure ML...")
    data_path = ROOT_DIR / "data" / "raw"
    data_asset = Data(
        name="fumc_digital_twin_data",
        version="1",
        description="Dataset longitudinal del Digital Twin FUMC (70,595 registros en Parquet)",
        path=str(data_path),
        type=AssetTypes.URI_FOLDER
    )
    created_data = ml_client.data.create_or_update(data_asset)
    print(f"      Data Asset registrado: {created_data.name} (v{created_data.version})")

    # 2. Registrar Entorno Gestionado
    print("\n[3/4] Registrando Entorno de Ejecución (Conda)...")
    env_asset = Environment(
        name="sat_fumc_lightgbm_env",
        version="1",
        description="Entorno Python 3.10 con LightGBM, SHAP, Scikit-learn y MLflow",
        image="mcr.microsoft.com/azureml/openmpi4.1.0-ubuntu20.04:latest",
        conda_file=str(ROOT_DIR / "azure" / "environments" / "conda.yaml")
    )
    created_env = ml_client.environments.create_or_update(env_asset)
    print(f"      Entorno registrado: {created_env.name} (v{created_env.version})")

    # 3. Registrar Modelo
    print("\n[4/4] Registrando Modelo en Azure ML Model Registry...")
    model_path = ROOT_DIR / "outputs" / "sat_fumc_lightgbm.joblib"
    if not model_path.exists():
        model_path = ROOT_DIR / "models" / "model_champion.joblib"

    model_asset = Model(
        name="SAT_FUMC_LightGBM_Model",
        version="1",
        path=str(model_path),
        type=AssetTypes.CUSTOM_MODEL,
        description="Modelo único LightGBM para predicción de deserción estudiantil FUMC (Recall 73.2%)"
    )
    created_model = ml_client.models.create_or_update(model_asset)
    print(f"      Modelo registrado: {created_model.name} (v{created_model.version})")

    print("\n" + "=" * 70)
    print("DESPLIEGUE DE COMPONENTES CORE EN AZURE COMPLETADO")
    print("Los datos, entorno y modelo están 100% disponibles en Azure Machine Learning.")
    print("=" * 70)

if __name__ == "__main__":
    try:
        deploy()
    except Exception as e:
        print(f"\nERROR DURANTE EL DESPLIEGUE: {e}")
        sys.exit(1)
