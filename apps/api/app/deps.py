"""Shared FastAPI dependencies (P1-S09).

Centralising dependency providers here keeps routers thin and makes them easy
to override in tests via ``app.dependency_overrides``.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.config import Settings, get_settings

# Reusable typed dependency: inject application settings into a route with
# ``settings: SettingsDep``.
SettingsDep = Annotated[Settings, Depends(get_settings)]
