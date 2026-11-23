from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings


ACTIVITY_FACTORS = {
    "low": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "high": 1.725,
}

GOAL_CALORIE_ADJUSTMENTS = {
    "weight_loss": -0.10,
    "muscle_gain": 0.05,
    "maintenance": 0.0,
}

PROTEIN_GRAMS_PER_KG = {
    "weight_loss": 1.6,
    "muscle_gain": 1.8,
    "maintenance": 1.4,
}

STEP_TARGETS = {
    "low": 6000,
    "light": 7500,
    "moderate": 9000,
    "high": 10000,
}


def estimate_energy(profile):
    """Return Mifflin-St Jeor estimates only when the required adult inputs exist."""
    if (
        not profile.age
        or profile.age < 18
        or not profile.calculation_sex
        or not profile.height_cm
        or not profile.current_weight_kg
        or not profile.goal
        or not profile.activity_level
    ):
        return None

    activity_factors = getattr(settings, "FITFORGE_ACTIVITY_FACTORS", ACTIVITY_FACTORS)
    goal_adjustments = getattr(
        settings,
        "FITFORGE_GOAL_CALORIE_ADJUSTMENTS",
        GOAL_CALORIE_ADJUSTMENTS,
    )
    if profile.activity_level not in activity_factors or profile.goal not in goal_adjustments:
        return None

    weight = float(profile.current_weight_kg)
    height = float(profile.height_cm)
    age = profile.age
    coefficient = 5 if profile.calculation_sex == "male" else -161
    bmr = 10 * weight + 6.25 * height - 5 * age + coefficient
    tdee = bmr * activity_factors[profile.activity_level]
    target = tdee * (1 + goal_adjustments[profile.goal])

    return {
        "bmr": round(bmr),
        "tdee": round(tdee),
        "target": round(target),
        "method": "Mifflin-St Jeor",
    }


def estimate_daily_targets(profile):
    energy = estimate_energy(profile)
    protein_target = None
    carbohydrate_target = None
    fat_target = None
    if profile.age and profile.age >= 18 and profile.current_weight_kg and profile.goal:
        protein_rates = getattr(
            settings,
            "FITFORGE_PROTEIN_GRAMS_PER_KG",
            PROTEIN_GRAMS_PER_KG,
        )
        rate = protein_rates.get(profile.goal)
        if rate is not None:
            protein_target = int(
                (Decimal(profile.current_weight_kg) * Decimal(str(rate))).quantize(
                    Decimal("1"),
                    rounding=ROUND_HALF_UP,
                )
            )
        if energy and protein_target is not None:
            fat_ratio = Decimal(str(getattr(settings, "FITFORGE_FAT_CALORIE_RATIO", 0.30)))
            if Decimal("0") <= fat_ratio <= Decimal("1"):
                calories = Decimal(energy["target"])
                fat_target = int(
                    (calories * fat_ratio / Decimal("9")).quantize(
                        Decimal("1"),
                        rounding=ROUND_HALF_UP,
                    )
                )
                remaining_carbs = (
                    calories
                    - Decimal(protein_target * 4)
                    - Decimal(fat_target * 9)
                ) / Decimal("4")
                carbohydrate_target = max(
                    0,
                    int(
                        remaining_carbs.quantize(
                            Decimal("1"),
                            rounding=ROUND_HALF_UP,
                        )
                    ),
                )

    step_targets = getattr(settings, "FITFORGE_STEP_TARGETS", STEP_TARGETS)
    step_target = step_targets.get(profile.activity_level)

    weekly_activity_target = getattr(
        settings,
        "FITFORGE_WEEKLY_ACTIVITY_TARGET_MINUTES",
        150,
    )

    return {
        "energy": energy,
        "calories": energy["target"] if energy else None,
        "maintenance_calories": energy["tdee"] if energy else None,
        "protein_g": protein_target,
        "carbs_g": carbohydrate_target,
        "fat_g": fat_target,
        "steps": step_target,
        "activity_minutes": (weekly_activity_target + 6) // 7,
        "weekly_activity_minutes": weekly_activity_target,
    }
