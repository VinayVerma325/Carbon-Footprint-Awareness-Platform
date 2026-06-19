"""
Core calculation engine package.

Exports:
    CarbonCalculator      – Converts consumer activity metrics into kg CO₂e.
    RecommendationEngine  – Analyzes footprint patterns and generates insights.
"""

from core.calculator import CarbonCalculator, RecommendationEngine

__all__ = ["CarbonCalculator", "RecommendationEngine"]
