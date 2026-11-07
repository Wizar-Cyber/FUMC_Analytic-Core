from __future__ import annotations

import math
import os
from typing import Any


_TOKEN_FIELDS = ("input_tokens", "output_tokens", "total_tokens")


def build_usage_report(
    socioeconomic: dict[str, int],
    academic: dict[str, int],
    synthesis: dict[str, int],
) -> dict[str, Any]:
    calls = {
        "socioeconomic": _validated_usage(socioeconomic),
        "academic": _validated_usage(academic),
        "synthesis": _validated_usage(synthesis),
    }
    total = {
        field: sum(usage[field] for usage in calls.values())
        for field in _TOKEN_FIELDS
    }
    try:
        input_rate = float(os.environ["AZURE_OPENAI_INPUT_PRICE_PER_1M_TOKENS"])
        output_rate = float(os.environ["AZURE_OPENAI_OUTPUT_PRICE_PER_1M_TOKENS"])
    except (KeyError, ValueError):
        input_rate = output_rate = None
    rates_valid = all(
        rate is not None and math.isfinite(rate) and rate >= 0
        for rate in (input_rate, output_rate)
    )
    estimate = (
        round(
            total["input_tokens"] * input_rate / 1_000_000
            + total["output_tokens"] * output_rate / 1_000_000,
            8,
        )
        if rates_valid
        else None
    )
    return {
        "calls": calls,
        "total": total,
        "cost_estimate": {
            "label": "estimated",
            "currency": "USD",
            "amount_usd": estimate,
            "input_price_per_1m_tokens": input_rate if rates_valid else None,
            "output_price_per_1m_tokens": output_rate if rates_valid else None,
            "basis": "actual input/output tokens and configured model rates",
        },
    }


def _validated_usage(value: dict[str, int]) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError("El uso de tokens de un agente no es válido.")
    usage = {}
    for field in _TOKEN_FIELDS:
        count = value.get(field)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("El uso de tokens de un agente no es válido.")
        usage[field] = count
    if usage["input_tokens"] + usage["output_tokens"] != usage["total_tokens"]:
        raise ValueError("El uso total de tokens no coincide con sus partes.")
    return usage
