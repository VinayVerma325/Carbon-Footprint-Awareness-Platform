"""
Carbon footprint calculation engine and personalized recommendation generator.

This module contains two public classes:

* :class:`CarbonCalculator` — Converts raw consumer metrics (electricity kWh,
  gas m³, travel distance, diet profile, waste kg) into kilograms of CO₂-
  equivalent emissions using EPA and DEFRA reference coefficients.

* :class:`RecommendationEngine` — Compares a user's calculated footprint
  against sustainable daily targets and produces prioritized, actionable
  insights sorted by estimated carbon-saving potential.

All emission factors are sourced from:
    • US EPA — *Greenhouse Gas Equivalencies Calculator*
    • UK DEFRA — *Government GHG Conversion Factors for Company Reporting*
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional

from exceptions import ValidationError

# ---------------------------------------------------------------------------
# Carbon Calculator
# ---------------------------------------------------------------------------


class CarbonCalculator:
    """Core calculation engine converting consumer metrics into CO₂ emissions (kg).

    Every class-method validates its inputs and raises
    :class:`~exceptions.ValidationError` on illegal values (negative usage,
    recycling rate outside [0, 1], etc.).  Results are rounded to three
    decimal places to avoid floating-point display noise.

    Usage::

        >>> CarbonCalculator.calculate_electricity(100.0)
        38.5
        >>> CarbonCalculator.calculate_total({
        ...     "electricity_kwh": 10, "gas_m3": 2,
        ...     "transport": [{"distance": 15, "mode": "car", "vehicle_type": "hybrid"}],
        ...     "diet_type": "vegetarian", "diet_days": 1,
        ...     "waste_kg": 2, "waste_recycling_rate": 0.5,
        ... })["total_co2"]
        16.16
    """

    # -- Emission intensity constants -----------------------------------------

    #: US average grid electricity intensity (kg CO₂e per kWh).
    ELECTRICITY_CO2_PER_KWH: float = 0.385

    #: Natural gas combustion factor (kg CO₂e per cubic metre).
    NATURAL_GAS_CO2_PER_CUBIC_METER: float = 2.03

    #: Transport emission factors (kg CO₂e per mile) keyed by canonical mode.
    TRANSPORT_FACTORS: Dict[str, float] = {
        "petrol_car": 0.404,
        "diesel_car": 0.380,
        "hybrid_car": 0.200,
        "electric_car": 0.050,
        "motorcycle": 0.180,
        "bus": 0.100,
        "train": 0.050,
        "flight_short": 0.250,   # < 300 miles
        "flight_long": 0.150,    # ≥ 300 miles
        "bicycle": 0.0,
        "bike": 0.0,
        "walk": 0.0,
    }

    #: Diet emission factors (kg CO₂e per person per day).
    DIET_FACTORS: Dict[str, float] = {
        "heavy_meat": 9.0,
        "average": 6.8,
        "no_beef": 5.2,
        "vegetarian": 4.7,
        "vegan": 4.1,
    }

    #: Waste-to-landfill emission factor (kg CO₂e per kg waste).
    WASTE_LANDFILL_FACTOR: float = 0.500

    #: Recycled-material emission factor (kg CO₂e per kg waste).
    WASTE_RECYCLE_FACTOR: float = 0.050

    # -- Individual category calculators --------------------------------------

    @classmethod
    def calculate_electricity(cls, kwh: float) -> float:
        """Calculate CO₂ emissions from household electricity usage.

        Args:
            kwh: Electricity consumed in kilowatt-hours (must be ≥ 0).

        Returns:
            Emissions in kg CO₂e, rounded to three decimal places.

        Raises:
            ValidationError: If *kwh* is negative.
        """
        if kwh < 0:
            raise ValidationError(
                "Electricity usage cannot be negative.",
                field="electricity_kwh",
            )
        return round(kwh * cls.ELECTRICITY_CO2_PER_KWH, 3)

    @classmethod
    def calculate_gas(cls, cubic_meters: float) -> float:
        """Calculate CO₂ emissions from natural gas consumption.

        Args:
            cubic_meters: Gas volume in cubic metres (must be ≥ 0).

        Returns:
            Emissions in kg CO₂e, rounded to three decimal places.

        Raises:
            ValidationError: If *cubic_meters* is negative.
        """
        if cubic_meters < 0:
            raise ValidationError(
                "Gas usage cannot be negative.",
                field="gas_m3",
            )
        return round(cubic_meters * cls.NATURAL_GAS_CO2_PER_CUBIC_METER, 3)

    @classmethod
    def calculate_transport(
        cls,
        distance_miles: float,
        mode: str,
        vehicle_type: Optional[str] = None,
    ) -> float:
        """Calculate travel CO₂ emissions based on distance, mode, and fuel type.

        The method resolves a canonical factor key from the combination of
        ``mode`` and ``vehicle_type``.  For flights, the factor is chosen
        automatically based on whether the distance is below or above the
        300-mile threshold (short-haul vs. long-haul).

        Args:
            distance_miles: Trip distance in miles (must be ≥ 0).
            mode: Travel mode (e.g. ``"car"``, ``"bus"``, ``"flight"``).
            vehicle_type: Sub-type for car/motorcycle (e.g. ``"petrol"``,
                ``"hybrid"``, ``"electric"``).  Ignored for other modes.

        Returns:
            Emissions in kg CO₂e, rounded to three decimal places.

        Raises:
            ValidationError: If *distance_miles* is negative.
        """
        if distance_miles < 0:
            raise ValidationError(
                "Distance cannot be negative.",
                field="distance",
            )

        factor_key = mode.lower()
        if factor_key == "car" and vehicle_type:
            factor_key = f"{vehicle_type.lower()}_car"
        elif factor_key == "flight":
            factor_key = "flight_short" if distance_miles < 300 else "flight_long"

        factor = cls.TRANSPORT_FACTORS.get(
            factor_key, cls.TRANSPORT_FACTORS["petrol_car"]
        )
        return round(distance_miles * factor, 3)

    @classmethod
    def calculate_diet(cls, days: int, diet_type: str) -> float:
        """Calculate dietary CO₂ emissions for a given period.

        Args:
            days: Number of days to account for (must be ≥ 0).
            diet_type: Diet profile key (e.g. ``"vegan"``, ``"average"``).
                Unrecognised values fall back to ``"average"``.

        Returns:
            Emissions in kg CO₂e, rounded to three decimal places.

        Raises:
            ValidationError: If *days* is negative.
        """
        if days < 0:
            raise ValidationError(
                "Days cannot be negative.",
                field="diet_days",
            )
        factor = cls.DIET_FACTORS.get(diet_type.lower(), cls.DIET_FACTORS["average"])
        return round(days * factor, 3)

    @classmethod
    def calculate_waste(cls, weight_kg: float, recycling_rate: float) -> float:
        """Calculate waste disposal CO₂ emissions.

        The recycling rate partitions total waste into a recycled fraction
        (lower emission factor) and a landfill fraction (higher factor).

        Args:
            weight_kg: Total waste weight in kilograms (must be ≥ 0).
            recycling_rate: Fraction of waste recycled, in ``[0.0, 1.0]``.

        Returns:
            Emissions in kg CO₂e, rounded to three decimal places.

        Raises:
            ValidationError: If *weight_kg* is negative or *recycling_rate*
                is outside ``[0.0, 1.0]``.
        """
        if weight_kg < 0:
            raise ValidationError(
                "Waste weight cannot be negative.",
                field="waste_kg",
            )
        if not (0.0 <= recycling_rate <= 1.0):
            raise ValidationError(
                "Recycling rate must be between 0.0 and 1.0.",
                field="waste_recycling_rate",
            )

        recycled_weight = weight_kg * recycling_rate
        landfill_weight = weight_kg - recycled_weight

        emissions = (
            landfill_weight * cls.WASTE_LANDFILL_FACTOR
            + recycled_weight * cls.WASTE_RECYCLE_FACTOR
        )
        return round(emissions, 3)

    # -- Aggregate calculator -------------------------------------------------

    @classmethod
    def calculate_total(cls, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Aggregate total footprint across all emission categories.

        Accepts a flat dictionary of raw input values (matching the
        :class:`CarbonCalculationRequest` schema) and returns a breakdown
        dictionary with per-category and total emissions.

        Args:
            inputs: Dictionary with keys ``electricity_kwh``, ``gas_m3``,
                ``transport`` (list of dicts), ``diet_type``, ``diet_days``,
                ``waste_kg``, ``waste_recycling_rate``.

        Returns:
            Dictionary with keys ``electricity_co2``, ``gas_co2``,
            ``transport_co2``, ``diet_co2``, ``waste_co2``, ``total_co2``.
        """
        electricity_usage = float(inputs.get("electricity_kwh", 0))
        gas_usage = float(inputs.get("gas_m3", 0))

        transport_logs: List[Dict[str, Any]] = inputs.get("transport", [])
        diet_type = inputs.get("diet_type", "average")
        diet_days = int(inputs.get("diet_days", 1))
        waste_kg = float(inputs.get("waste_kg", 0))
        waste_recycling_rate = float(inputs.get("waste_recycling_rate", 0.0))

        electricity_co2 = cls.calculate_electricity(electricity_usage)
        gas_co2 = cls.calculate_gas(gas_usage)

        transport_co2 = 0.0
        for log in transport_logs:
            dist = float(log.get("distance", 0))
            mode = log.get("mode", "car")
            vtype = log.get("vehicle_type", "petrol")
            transport_co2 += cls.calculate_transport(dist, mode, vtype)

        diet_co2 = cls.calculate_diet(diet_days, diet_type)
        waste_co2 = cls.calculate_waste(waste_kg, waste_recycling_rate)

        total = round(
            electricity_co2 + gas_co2 + transport_co2 + diet_co2 + waste_co2, 3
        )

        return {
            "electricity_co2": electricity_co2,
            "gas_co2": gas_co2,
            "transport_co2": round(transport_co2, 3),
            "diet_co2": diet_co2,
            "waste_co2": waste_co2,
            "total_co2": total,
        }

    @classmethod
    def calculate_net(cls, total_co2: float, daily_offset_kg: float) -> float:
        """Compute net carbon footprint after applying green-action offsets.

        Net emissions are clamped to a minimum of ``0.0`` — offset credits
        cannot produce a *negative* footprint.

        Args:
            total_co2: Gross daily emissions in kg CO₂e (must be ≥ 0).
            daily_offset_kg: Sum of offset credits for the day (must be ≥ 0).

        Returns:
            Net emissions in kg CO₂e (≥ 0), rounded to three decimal places.

        Raises:
            ValidationError: If either argument is negative.
        """
        if total_co2 < 0:
            raise ValidationError(
                "Total carbon footprint cannot be negative.",
                field="total_co2",
            )
        if daily_offset_kg < 0:
            raise ValidationError(
                "Offset amount cannot be negative.",
                field="daily_offset_kg",
            )
        return round(max(0.0, total_co2 - daily_offset_kg), 3)


# ---------------------------------------------------------------------------
# Recommendation Engine
# ---------------------------------------------------------------------------


class RecommendationEngine:
    """Analyzes carbon footprint patterns and outputs structured, prioritized insights.

    Compares per-category averages (from historical logs or current inputs)
    against evidence-based sustainable daily limits and generates actionable
    recommendations sorted by estimated savings potential.

    Usage::

        >>> recs = RecommendationEngine.analyze_and_recommend(
        ...     user_data={"electricity_kwh": 20, ...},
        ...     historical_logs=[],
        ... )
        >>> recs[0]["category"]
        'electricity'
    """

    #: Recommended sustainable daily limits (kg CO₂e per person per day).
    TARGET_DAILY_LIMITS: Dict[str, float] = {
        "electricity": 2.5,   # ≈ 75 kWh/month per person
        "gas": 1.5,
        "transport": 3.0,     # ≈ 7–8 miles in standard petrol car
        "diet": 4.5,          # Vegetarian / low-beef range
        "waste": 0.2,         # High recycling rate
    }

    @classmethod
    def analyze_and_recommend(
        cls,
        user_data: Dict[str, Any],
        historical_logs: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Generate prioritized, category-specific carbon-reduction recommendations.

        When *historical_logs* are available the engine averages across all
        past records; otherwise it falls back to a single-shot calculation
        from *user_data*.

        Args:
            user_data: Current user inputs or profile data.
            historical_logs: List of past calculation log dictionaries.

        Returns:
            List of recommendation dicts ordered by ``estimated_savings_kg``
            descending.  Each dict contains ``category``, ``title``,
            ``description``, ``impact`` (``"High"``/``"Medium"``/``"Low"``),
            and ``estimated_savings_kg``.
        """
        # Calculate daily averages from history or fallback to current data
        averages: Dict[str, float] = {
            "electricity": 0.0,
            "gas": 0.0,
            "transport": 0.0,
            "diet": 0.0,
            "waste": 0.0,
        }

        if historical_logs:
            num_logs = len(historical_logs)
            for log in historical_logs:
                averages["electricity"] += float(log.get("electricity_co2", 0))
                averages["gas"] += float(log.get("gas_co2", 0))
                averages["transport"] += float(log.get("transport_co2", 0))
                averages["diet"] += float(log.get("diet_co2", 0))
                averages["waste"] += float(log.get("waste_co2", 0))
            for key in averages:
                averages[key] /= num_logs
        else:
            current_co2 = CarbonCalculator.calculate_total(user_data)
            averages["electricity"] = current_co2["electricity_co2"]
            averages["gas"] = current_co2["gas_co2"]
            averages["transport"] = current_co2["transport_co2"]
            averages["diet"] = current_co2["diet_co2"]
            averages["waste"] = current_co2["waste_co2"]

        recommendations: List[Dict[str, Any]] = []

        # --- Transport ---
        if averages["transport"] > cls.TARGET_DAILY_LIMITS["transport"]:
            excess = averages["transport"] - cls.TARGET_DAILY_LIMITS["transport"]
            savings = round(excess * 0.6, 2)  # assume 60% reduction possible
            recommendations.append({
                "category": "transport",
                "title": "Optimize Transit Choices",
                "description": (
                    "Your transportation footprint is high. Consider carpooling, "
                    "switching to public transit or an EV, or using eco-routing "
                    "on Google Maps."
                ),
                "impact": "High" if excess > 5.0 else "Medium",
                "estimated_savings_kg": savings,
            })

        # --- Electricity ---
        if averages["electricity"] > cls.TARGET_DAILY_LIMITS["electricity"]:
            excess = averages["electricity"] - cls.TARGET_DAILY_LIMITS["electricity"]
            savings = round(excess * 0.3, 2)  # 30% from smart tech/behavior
            recommendations.append({
                "category": "electricity",
                "title": "Improve Home Energy Efficiency",
                "description": (
                    "Your household electricity consumption exceeds green baselines. "
                    "Transition to LED bulbs, install smart thermostats, and unplug "
                    "idle electronics."
                ),
                "impact": "High" if excess > 4.0 else "Medium",
                "estimated_savings_kg": savings,
            })

        # --- Natural Gas ---
        if averages["gas"] > cls.TARGET_DAILY_LIMITS["gas"]:
            excess = averages["gas"] - cls.TARGET_DAILY_LIMITS["gas"]
            savings = round(excess * 0.35, 2)  # 35% from insulation/heat-pump
            recommendations.append({
                "category": "gas",
                "title": "Reduce Natural Gas Dependence",
                "description": (
                    "Your heating/cooking gas usage is above sustainable levels. "
                    "Consider upgrading insulation, switching to a heat pump, "
                    "or using induction cooking appliances."
                ),
                "impact": "High" if excess > 3.0 else "Medium",
                "estimated_savings_kg": savings,
            })

        # --- Diet ---
        if averages["diet"] > cls.TARGET_DAILY_LIMITS["diet"]:
            excess = averages["diet"] - cls.TARGET_DAILY_LIMITS["diet"]
            savings = round(excess * 0.4, 2)  # 40% from diet adjustment
            recommendations.append({
                "category": "diet",
                "title": "Incorporate Plant-Based Options",
                "description": (
                    "Diet emissions are elevated. Replacing red meat with plant-"
                    "based alternatives or implementing 'Meatless Mondays' yields "
                    "high carbon savings."
                ),
                "impact": "Medium" if excess < 3.0 else "High",
                "estimated_savings_kg": savings,
            })

        # --- Waste ---
        if averages["waste"] > cls.TARGET_DAILY_LIMITS["waste"]:
            excess = averages["waste"] - cls.TARGET_DAILY_LIMITS["waste"]
            savings = round(excess * 0.8, 2)  # 80% from improved recycling
            recommendations.append({
                "category": "waste",
                "title": "Enhance Recycling & Composting",
                "description": (
                    "Your landfill waste output is high. Set up structured sorting "
                    "for recyclables, compost food scraps, and purchase items with "
                    "minimal packaging."
                ),
                "impact": "Medium" if excess > 0.5 else "Low",
                "estimated_savings_kg": savings,
            })

        # Default green nudge if user is already sustainable
        if not recommendations:
            recommendations.append({
                "category": "general",
                "title": "Maintain Your Green Habits!",
                "description": (
                    "Outstanding work! Your carbon footprint is well within "
                    "sustainable target limits. Keep tracking and sharing your "
                    "tips with others."
                ),
                "impact": "Low",
                "estimated_savings_kg": 0.0,
            })

        # Sort recommendations by estimated carbon savings descending
        recommendations.sort(key=lambda x: x["estimated_savings_kg"], reverse=True)
        return recommendations
