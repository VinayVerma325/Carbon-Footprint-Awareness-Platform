"""
Pytest shared fixtures and configuration for the CarbonWise test suite.

Provides reusable fixtures for:
    • FastAPI ``TestClient`` with isolated temporary database.
    • Pre-configured ``FirestoreRepository`` in local-fallback mode.
    • Sample input data dictionaries.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, Generator

import pytest

# Ensure project root is on sys.path
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
)


@pytest.fixture
def sample_inputs() -> Dict[str, Any]:
    """Return a standard set of carbon calculation inputs for testing."""
    return {
        "electricity_kwh": 10.0,
        "gas_m3": 2.0,
        "transport": [
            {"distance": 15.0, "mode": "car", "vehicle_type": "hybrid"},
            {"distance": 5.0, "mode": "walk"},
        ],
        "diet_type": "vegetarian",
        "diet_days": 1,
        "waste_kg": 2.0,
        "waste_recycling_rate": 0.5,
    }


@pytest.fixture
def sustainable_inputs() -> Dict[str, Any]:
    """Return inputs that stay within all sustainable daily limits."""
    return {
        "electricity_kwh": 2.0,
        "gas_m3": 0.0,
        "transport": [
            {"distance": 2.0, "mode": "car", "vehicle_type": "electric"}
        ],
        "diet_type": "vegan",
        "waste_kg": 0.2,
        "waste_recycling_rate": 0.9,
    }
