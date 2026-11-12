"""Cliente por lotes del endpoint de Azure ML (contrato de azure/endpoints/model_code/score.py).

No hay fallback: si el endpoint no responde tras los reintentos, se lanza
EndpointScoringError. La clave nunca se incluye en mensajes de error ni en logs.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

DEFAULT_BATCH_SIZE = 200
DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_RETRIES = 4
DEFAULT_BACKOFF_SECONDS = 2.0
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
_MODEL_ID = re.compile(r"/models/(?P<name>[^/]+)/versions/(?P<version>[^/]+)$")


class EndpointScoringError(RuntimeError):
    pass


@dataclass(frozen=True)
class EndpointSettings:
    url: str
    key: str
    deployment: str = "blue"

    def __repr__(self) -> str:
        return f"EndpointSettings(url={self.url!r}, key='***', deployment={self.deployment!r})"


@dataclass(frozen=True)
class ModelInfo:
    name: str
    version: str


def settings_from_env(env: Mapping[str, str] | None = None) -> EndpointSettings:
    env = os.environ if env is None else env
    url = env.get("AZURE_ML_ENDPOINT_URL", "").strip()
    key = env.get("AZURE_ML_ENDPOINT_KEY", "").strip()
    if not url or not key:
        raise EndpointScoringError(
            "Define AZURE_ML_ENDPOINT_URL y AZURE_ML_ENDPOINT_KEY para puntuar contra el endpoint de Azure ML."
        )
    return EndpointSettings(url=url, key=key, deployment=env.get("AZURE_ML_DEPLOYMENT_NAME", "blue") or "blue")


def _json_safe(value: Any) -> Any:
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def clean_record(record: Mapping[str, Any], columns: Iterable[str]) -> dict[str, Any]:
    return {name: _json_safe(record.get(name)) for name in columns}


def _post(
    settings: EndpointSettings,
    records: Sequence[Mapping[str, Any]],
    *,
    timeout: float,
    opener: Callable[..., Any],
) -> list[float]:
    request = urllib.request.Request(
        settings.url,
        data=json.dumps({"data": list(records)}, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.key}",
            "azureml-model-deployment": settings.deployment,
        },
        method="POST",
    )
    with opener(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    payload = json.loads(body)
    if isinstance(payload, str):  # algunos despliegues devuelven el JSON como cadena
        payload = json.loads(payload)
    predictions = payload.get("predictions") if isinstance(payload, dict) else None
    if not isinstance(payload, dict) or payload.get("status") != "success" or not isinstance(predictions, list):
        raise EndpointScoringError("Respuesta del endpoint sin predicciones válidas.")
    if len(predictions) != len(records):
        raise EndpointScoringError(
            f"El endpoint devolvió {len(predictions)} predicciones para {len(records)} registros."
        )
    probabilities = []
    for item in predictions:
        value = item.get("probabilidad_desercion") if isinstance(item, dict) else None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
            raise EndpointScoringError("El endpoint devolvió una probabilidad fuera de [0, 1].")
        probabilities.append(float(value))
    return probabilities


def score_records(
    records: Sequence[Mapping[str, Any]],
    settings: EndpointSettings,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    retries: int = DEFAULT_RETRIES,
    backoff: float = DEFAULT_BACKOFF_SECONDS,
    opener: Callable[..., Any] = urllib.request.urlopen,
    sleep: Callable[[float], None] = time.sleep,
) -> list[float]:
    """Puntúa los registros por lotes y devuelve las probabilidades en el mismo orden."""
    if batch_size < 1:
        raise ValueError("batch_size debe ser mayor que cero.")
    results: list[float] = []
    for offset in range(0, len(records), batch_size):
        batch = records[offset : offset + batch_size]
        last_error = "sin detalle"
        for attempt in range(retries + 1):
            try:
                results.extend(_post(settings, batch, timeout=timeout, opener=opener))
                break
            except urllib.error.HTTPError as error:
                last_error = f"HTTP {error.code}"
                if error.code not in RETRYABLE_STATUS:
                    raise EndpointScoringError(
                        f"El endpoint rechazó el lote {offset // batch_size + 1} ({last_error}); no se reintenta."
                    ) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
                last_error = type(error).__name__
            except (ValueError, json.JSONDecodeError):
                raise EndpointScoringError(
                    f"Respuesta no interpretable del endpoint en el lote {offset // batch_size + 1}."
                ) from None
            if attempt < retries:
                sleep(backoff * (2**attempt))
        else:
            raise EndpointScoringError(
                f"El endpoint de Azure ML no respondió tras {retries + 1} intentos en el lote "
                f"{offset // batch_size + 1} ({last_error}). No se usa ningún fallback."
            )
    return results


def parse_model_id(model_id: str) -> ModelInfo:
    match = _MODEL_ID.search(model_id or "")
    if match:
        return ModelInfo(name=match["name"], version=match["version"])
    short = re.fullmatch(r"azureml:(?P<name>[^:/]+):(?P<version>[^:/]+)", model_id or "")
    if short:
        return ModelInfo(name=short["name"], version=short["version"])
    raise EndpointScoringError(f"No se pudo interpretar el id del modelo: {model_id!r}")


def resolve_model_info(
    settings: EndpointSettings,
    *,
    explicit: tuple[str, str] | None = None,
    env: Mapping[str, str] | None = None,
    describe_deployment: Callable[[], str] | None = None,
) -> ModelInfo:
    """Nombre y versión del modelo vigente: explícito, variables de entorno o el despliegue."""
    env = os.environ if env is None else env
    if explicit and explicit[0] and explicit[1]:
        return ModelInfo(*explicit)
    name, version = env.get("AZURE_ML_MODEL_NAME", ""), env.get("AZURE_ML_MODEL_VERSION", "")
    if name and version:
        return ModelInfo(name, version)
    describe = describe_deployment or _describe_deployment_with_sdk(settings)
    return parse_model_id(describe())


def _describe_deployment_with_sdk(settings: EndpointSettings) -> Callable[[], str]:
    def describe() -> str:
        try:
            from azure.ai.ml import MLClient
            from azure.identity import DefaultAzureCredential
        except ImportError as error:
            raise EndpointScoringError(
                "No se puede resolver la versión del modelo: instala azure-ai-ml o define "
                "AZURE_ML_MODEL_NAME y AZURE_ML_MODEL_VERSION."
            ) from error
        config_path = os.path.join(os.path.dirname(__file__), "..", "..", "azure", "config.json")
        try:
            client = MLClient.from_config(DefaultAzureCredential(), path=config_path)
            endpoint_name = settings.url.split("//", 1)[-1].split(".", 1)[0]
            deployment = client.online_deployments.get(name=settings.deployment, endpoint_name=endpoint_name)
        except Exception as error:
            raise EndpointScoringError(
                "No se pudo consultar el despliegue en Azure ML para resolver la versión del modelo "
                f"({type(error).__name__}). Define AZURE_ML_MODEL_NAME y AZURE_ML_MODEL_VERSION."
            ) from None
        return str(deployment.model)

    return describe
