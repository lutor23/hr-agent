"""Read-only access to the mock employee data in mock_data/*.json."""

import json
from functools import lru_cache
from typing import Optional

from app import config


@lru_cache(maxsize=None)
def _load(name: str):
    return json.loads((config.MOCK_DATA_DIR / f"{name}.json").read_text(encoding="utf-8"))


def get_employee(employee_id: str) -> Optional[dict]:
    return next((e for e in _load("employees") if e["employee_id"] == employee_id), None)


def get_pto_balance(employee_id: str) -> Optional[dict]:
    return _load("pto_balances").get(employee_id)


def get_benefits(employee_id: str) -> Optional[dict]:
    return _load("benefits").get(employee_id)
