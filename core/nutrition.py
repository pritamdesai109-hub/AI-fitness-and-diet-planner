from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from .models import Food


NUTRIENTS = (
    ("calories", "calories_per_100g"),
    ("protein_g", "protein_per_100g"),
    ("carbs_g", "carbs_per_100g"),
    ("fat_g", "fat_per_100g"),
    ("fiber_g", "fiber_per_100g"),
    ("sugar_g", "sugar_per_100g"),
    ("sodium_mg", "sodium_per_100g"),
)
_THREE_PLACES = Decimal("0.001")


def _decimal(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError("Enter a valid serving quantity.") from error
    if not number.is_finite():
        raise ValueError("Enter a finite serving quantity.")
    return number


def resolve_serving(food, serving_option, serving_count, custom_grams):
    if serving_option == "custom":
        weight = _decimal(custom_grams)
        if not Decimal("0.1") <= weight <= Decimal("10000"):
            raise ValueError("Custom servings must be between 0.1 and 10,000 g.")
        weight = weight.quantize(_THREE_PLACES, rounding=ROUND_HALF_UP)
        return weight, f"{weight.normalize():f} g", "g"

    try:
        option_index = int(serving_option)
        if option_index < 0:
            raise ValueError
        option = food.serving_options[option_index]
        base_weight = _decimal(option["weight_g"])
        count = _decimal(serving_count)
    except (IndexError, KeyError, TypeError, ValueError) as error:
        raise ValueError("Choose a valid serving option.") from error

    if (
        base_weight <= 0
        or not Decimal("0.1") <= count <= Decimal("100")
    ):
        raise ValueError("Choose a valid serving quantity.")

    weight = (base_weight * count).quantize(_THREE_PLACES, rounding=ROUND_HALF_UP)
    label = str(option["label"])
    if count != 1:
        label = f"{count.normalize():f} × {label}"
    return weight, label, str(option.get("unit") or "serving")


def calculate_nutrients(food, weight_in_grams):
    weight = _decimal(weight_in_grams)
    if not Decimal("0") < weight <= Decimal("10000"):
        raise ValueError("Serving weight must be between 0 and 10,000 g.")
    multiplier = weight / Decimal("100")
    return {
        output_name: (Decimal(getattr(food, model_field)) * multiplier).quantize(
            _THREE_PLACES,
            rounding=ROUND_HALF_UP,
        )
        for output_name, model_field in NUTRIENTS
    }


def find_foods(query="", category=""):
    foods = list(Food.objects.filter(is_active=True, slug__isnull=False).order_by("name"))
    if category:
        foods = [food for food in foods if food.category == category]

    term = query.strip().casefold()
    if not term:
        return foods

    matches = []
    for food in foods:
        searchable = [food.name, food.category, food.food_state]
        searchable.extend(food.search_terms or [])
        for names in (food.aliases or {}).values():
            if isinstance(names, list):
                searchable.extend(names)
        if any(term in str(value).casefold() for value in searchable if value):
            matches.append(food)
    return matches
