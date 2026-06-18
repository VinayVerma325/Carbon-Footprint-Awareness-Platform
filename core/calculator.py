from typing import Dict, Any, List, Optional

class CarbonCalculator:
    """Core calculation engine converting consumer metrics into CO2 emissions (in kg)."""

    # Constants representing carbon intensity factors (kg CO2 per unit)
    # Reference sources: EPA (US Environmental Protection Agency) and DEFRA (UK Department for Environment, Food & Rural Affairs)
    ELECTRICITY_CO2_PER_KWH = 0.385  # US Average Grid intensity
    NATURAL_GAS_CO2_PER_CUBIC_METER = 2.03  # ~2.03 kg per m3
    
    # Transport emission factors (kg CO2 per mile)
    TRANSPORT_FACTORS = {
        "petrol_car": 0.404,
        "diesel_car": 0.380,
        "hybrid_car": 0.200,
        "electric_car": 0.050,
        "motorcycle": 0.180,
        "bus": 0.100,
        "train": 0.050,
        "flight_short": 0.250,  # < 300 miles
        "flight_long": 0.150,   # >= 300 miles
        "bicycle": 0.0,
        "bike": 0.0,
        "walk": 0.0,
    }
    
    # Diet emission factors (kg CO2 per day)
    DIET_FACTORS = {
        "heavy_meat": 9.0,
        "average": 6.8,
        "no_beef": 5.2,
        "vegetarian": 4.7,
        "vegan": 4.1
    }
    
    # Waste emission factors (kg CO2 per kg of waste)
    WASTE_LANDFILL_FACTOR = 0.500
    WASTE_RECYCLE_FACTOR = 0.050

    @classmethod
    def calculate_electricity(cls, kwh: float) -> float:
        """Calculate carbon footprint from electricity usage in kWh."""
        if kwh < 0:
            raise ValueError("Electricity usage cannot be negative.")
        return round(kwh * cls.ELECTRICITY_CO2_PER_KWH, 3)

    @classmethod
    def calculate_gas(cls, cubic_meters: float) -> float:
        """Calculate carbon footprint from natural gas usage in cubic meters."""
        if cubic_meters < 0:
            raise ValueError("Gas usage cannot be negative.")
        return round(cubic_meters * cls.NATURAL_GAS_CO2_PER_CUBIC_METER, 3)

    @classmethod
    def calculate_transport(cls, distance_miles: float, mode: str, vehicle_type: Optional[str] = None) -> float:
        """Calculate travel carbon footprint based on distance, mode, and vehicle sub-type."""
        if distance_miles < 0:
            raise ValueError("Distance cannot be negative.")
        
        factor_key = mode.lower()
        if factor_key == "car" and vehicle_type:
            factor_key = f"{vehicle_type.lower()}_car"
        elif factor_key == "flight":
            factor_key = "flight_short" if distance_miles < 300 else "flight_long"
            
        factor = cls.TRANSPORT_FACTORS.get(factor_key, cls.TRANSPORT_FACTORS["petrol_car"])
        return round(distance_miles * factor, 3)

    @classmethod
    def calculate_diet(cls, days: int, diet_type: str) -> float:
        """Calculate diet carbon footprint for a given number of days."""
        if days < 0:
            raise ValueError("Days cannot be negative.")
        factor = cls.DIET_FACTORS.get(diet_type.lower(), cls.DIET_FACTORS["average"])
        return round(days * factor, 3)

    @classmethod
    def calculate_waste(cls, weight_kg: float, recycling_rate: float) -> float:
        """Calculate waste carbon footprint based on weight and recycling rate fraction (0.0 to 1.0)."""
        if weight_kg < 0:
            raise ValueError("Waste weight cannot be negative.")
        if not (0.0 <= recycling_rate <= 1.0):
            raise ValueError("Recycling rate must be between 0.0 and 1.0.")
            
        recycled_weight = weight_kg * recycling_rate
        landfill_weight = weight_kg - recycled_weight
        
        emissions = (landfill_weight * cls.WASTE_LANDFILL_FACTOR) + (recycled_weight * cls.WASTE_RECYCLE_FACTOR)
        return round(emissions, 3)

    @classmethod
    def calculate_total(cls, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Aggregate total footprint across multiple categories from input dict."""
        electricity_usage = float(inputs.get("electricity_kwh", 0))
        gas_usage = float(inputs.get("gas_m3", 0))
        
        # Transport logs can be a list of dicts: [{"distance": 10, "mode": "car", "vehicle_type": "hybrid"}]
        transport_logs = inputs.get("transport", [])
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
        
        total = round(electricity_co2 + gas_co2 + transport_co2 + diet_co2 + waste_co2, 3)
        
        return {
            "electricity_co2": electricity_co2,
            "gas_co2": gas_co2,
            "transport_co2": round(transport_co2, 3),
            "diet_co2": diet_co2,
            "waste_co2": waste_co2,
            "total_co2": total
        }

    @classmethod
    def calculate_net(cls, total_co2: float, daily_offset_kg: float) -> float:
        """Calculate net carbon footprint (total footprint minus offsets), ensuring it does not drop below 0."""
        if total_co2 < 0:
            raise ValueError("Total carbon footprint cannot be negative.")
        if daily_offset_kg < 0:
            raise ValueError("Offset amount cannot be negative.")
        return round(max(0.0, total_co2 - daily_offset_kg), 3)



class RecommendationEngine:
    """Analyzes carbon footprint patterns and outputs structured, personalized, actionable insights."""
    
    # Recommended sustainable daily limits in kg CO2
    TARGET_DAILY_LIMITS = {
        "electricity": 2.5,  # target ~75 kWh/month per person
        "gas": 1.5,
        "transport": 3.0,    # ~7-8 miles in standard petrol car, or more in cleaner modes
        "diet": 4.5,         # Target vegan/vegetarian/low beef range
        "waste": 0.2          # Target high recycling rate
    }

    @classmethod
    def analyze_and_recommend(cls, user_data: Dict[str, Any], historical_logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Analyze current inputs and historical footprint records to provide prioritized recommendations.
        
        Args:
            user_data: Dict containing current inputs or current profile data.
            historical_logs: List of past logs to detect trends.
            
        Returns:
            List of recommendation dicts, ordered by impact.
        """
        # Calculate daily averages from history or fallback to current data
        averages = {
            "electricity": 0.0,
            "gas": 0.0,
            "transport": 0.0,
            "diet": 0.0,
            "waste": 0.0
        }
        
        if historical_logs:
            num_logs = len(historical_logs)
            for log in historical_logs:
                averages["electricity"] += float(log.get("electricity_co2", 0))
                averages["gas"] += float(log.get("gas_co2", 0))
                averages["transport"] += float(log.get("transport_co2", 0))
                averages["diet"] += float(log.get("diet_co2", 0))
                averages["waste"] += float(log.get("waste_co2", 0))
            for k in averages:
                averages[k] /= num_logs
        else:
            # Fallback to current inputs
            current_co2 = CarbonCalculator.calculate_total(user_data)
            averages["electricity"] = current_co2["electricity_co2"]
            averages["gas"] = current_co2["gas_co2"]
            averages["transport"] = current_co2["transport_co2"]
            averages["diet"] = current_co2["diet_co2"]
            averages["waste"] = current_co2["waste_co2"]

        recommendations = []
        
        # Check Transport
        if averages["transport"] > cls.TARGET_DAILY_LIMITS["transport"]:
            excess = averages["transport"] - cls.TARGET_DAILY_LIMITS["transport"]
            savings = round(excess * 0.6, 2)  # assume 60% reduction possible
            recommendations.append({
                "category": "transport",
                "title": "Optimize Transit Choices",
                "description": "Your transportation footprint is high. Consider carpooling, switching to public transit or an EV, or using eco-routing on Google Maps.",
                "impact": "High" if excess > 5.0 else "Medium",
                "estimated_savings_kg": savings
            })

        # Check Electricity
        if averages["electricity"] > cls.TARGET_DAILY_LIMITS["electricity"]:
            excess = averages["electricity"] - cls.TARGET_DAILY_LIMITS["electricity"]
            savings = round(excess * 0.3, 2)  # assume 30% reduction from smart tech/behavior
            recommendations.append({
                "category": "electricity",
                "title": "Improve Home Energy Efficiency",
                "description": "Your household electricity consumption exceeds green baselines. Transition to LED bulbs, install smart thermostats, and unplug idle electronics.",
                "impact": "High" if excess > 4.0 else "Medium",
                "estimated_savings_kg": savings
            })

        # Check Diet
        if averages["diet"] > cls.TARGET_DAILY_LIMITS["diet"]:
            excess = averages["diet"] - cls.TARGET_DAILY_LIMITS["diet"]
            savings = round(excess * 0.4, 2)  # assume 40% reduction from diet adjustment
            recommendations.append({
                "category": "diet",
                "title": "Incorporate Plant-Based Options",
                "description": "Diet emissions are elevated. Replacing red meat with plant-based alternatives or implementing 'Meatless Mondays' yields high carbon savings.",
                "impact": "Medium" if excess < 3.0 else "High",
                "estimated_savings_kg": savings
            })

        # Check Waste
        if averages["waste"] > cls.TARGET_DAILY_LIMITS["waste"]:
            excess = averages["waste"] - cls.TARGET_DAILY_LIMITS["waste"]
            savings = round(excess * 0.8, 2)  # assume 80% reduction from high recycling rate
            recommendations.append({
                "category": "waste",
                "title": "Enhance Recycling & Composting",
                "description": "Your landfill waste output is high. Set up structured sorting for recyclables, compost food scraps, and purchase items with minimal packaging.",
                "impact": "Medium" if excess > 0.5 else "Low",
                "estimated_savings_kg": savings
            })
            
        # Add a default green nudge if doing exceptionally well
        if not recommendations:
            recommendations.append({
                "category": "general",
                "title": "Maintain Your Green Habits!",
                "description": "Outstanding work! Your carbon footprint is well within sustainable target limits. Keep tracking and sharing your tips with others.",
                "impact": "Low",
                "estimated_savings_kg": 0.0
            })

        # Sort recommendations by estimated carbon savings descending
        recommendations.sort(key=lambda x: x["estimated_savings_kg"], reverse=True)
        return recommendations
