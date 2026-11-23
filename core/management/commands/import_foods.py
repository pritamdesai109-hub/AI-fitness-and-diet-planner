import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Food


_NUTRIENT_FIELDS = {
    "calories_per_100g": "calories_kcal",
    "protein_per_100g": "protein_g",
    "carbs_per_100g": "carbohydrates_g",
    "fat_per_100g": "fat_g",
    "fiber_per_100g": "fiber_g",
    "sugar_per_100g": "sugar_g",
    "sodium_per_100g": "sodium_mg",
}


def _validate_record(record, index, image_directory):
    errors = []
    if not isinstance(record, dict):
        return None, [f"record {index}: expected an object"]

    slug = record.get("id")
    if not isinstance(slug, str) or not slug.strip() or len(slug) > 120:
        errors.append("invalid id")
    if not isinstance(record.get("name"), str) or not record["name"].strip():
        errors.append("missing name")
    if not isinstance(record.get("category"), str) or not record["category"].strip():
        errors.append("missing category")

    aliases = record.get("aliases")
    if not isinstance(aliases, dict) or any(
        not isinstance(names, list) or any(not isinstance(name, str) for name in names)
        for names in aliases.values()
    ):
        errors.append("aliases must be language-keyed lists of strings")

    search_terms = record.get("search_terms")
    if not isinstance(search_terms, list) or any(not isinstance(term, str) for term in search_terms):
        errors.append("search_terms must be a list of strings")

    nutrition = record.get("nutrition_per_100g")
    values = {}
    if not isinstance(nutrition, dict):
        errors.append("missing nutrition_per_100g")
    else:
        for model_field, data_field in _NUTRIENT_FIELDS.items():
            try:
                value = Decimal(str(nutrition[data_field]))
            except (KeyError, TypeError, ValueError, InvalidOperation):
                errors.append(f"invalid {data_field}")
                continue
            if not value.is_finite() or value < 0 or value > Decimal("9999999.999"):
                errors.append(f"invalid {data_field}")
            else:
                values[model_field] = value

    servings = record.get("serving_options")
    if not isinstance(servings, list):
        errors.append("serving_options must be a list")
    else:
        for serving_index, serving in enumerate(servings):
            if not isinstance(serving, dict) or not isinstance(serving.get("label"), str):
                errors.append(f"serving option {serving_index} needs a label")
                continue
            weight = serving.get("weight_g")
            if weight is None:
                if not serving.get("requires_user_weight"):
                    errors.append(f"serving option {serving_index} has no weight")
            else:
                try:
                    weight_value = Decimal(str(weight))
                except (TypeError, ValueError, InvalidOperation):
                    errors.append(f"serving option {serving_index} has an invalid weight")
                    continue
                if not weight_value.is_finite() or weight_value <= 0:
                    errors.append(f"serving option {serving_index} has an invalid weight")

    image = record.get("image")
    image_filename = ""
    if not isinstance(image, dict):
        errors.append("missing image metadata")
    else:
        filename = image.get("filename")
        if filename:
            if not isinstance(filename, str) or Path(filename).name != filename:
                errors.append("image filename must be a local filename")
            elif (image_directory / filename).is_file():
                image_filename = filename

    if not isinstance(record.get("nutrition_source"), dict):
        errors.append("missing nutrition_source")
    if not isinstance(record.get("is_vegetarian"), bool):
        errors.append("is_vegetarian must be a boolean")
    if not isinstance(record.get("is_active"), bool):
        errors.append("is_active must be a boolean")

    if errors:
        return None, [f"record {index} ({slug or 'unknown'}): {error}" for error in errors]

    return {
        "slug": slug,
        "name": record["name"].strip(),
        "category": record["category"].strip(),
        "aliases": aliases,
        "search_terms": search_terms,
        "image_filename": image_filename,
        "food_state": str(record.get("food_state") or ""),
        "nutrition_basis": str(record.get("nutrition_basis") or ""),
        "serving_options": servings,
        "nutrition_source": record["nutrition_source"],
        "is_vegetarian": record["is_vegetarian"],
        "is_active": record["is_active"],
        **values,
    }, []


class Command(BaseCommand):
    help = "Import the bundled local Indian food catalog."

    def handle(self, *args, **options):
        data_path = settings.BASE_DIR / "static" / "data" / "fitforge_indian_foods.json"
        image_directory = settings.BASE_DIR / "static" / "files"
        try:
            payload = json.loads(data_path.read_text(encoding="utf-8"))
        except OSError as error:
            raise CommandError(f"Food dataset could not be read: {data_path}") from error
        except json.JSONDecodeError as error:
            raise CommandError(f"Food dataset contains invalid JSON: {error}") from error

        records = payload.get("foods") if isinstance(payload, dict) else None
        if not isinstance(records, list):
            raise CommandError("Food dataset must contain a 'foods' list.")
        expected_count = payload.get("food_count")
        if expected_count is not None and expected_count != len(records):
            raise CommandError("Food dataset food_count does not match the records.")

        valid_records = []
        invalid_records = []
        missing_images = []
        seen_slugs = set()
        for index, record in enumerate(records, start=1):
            normalized, errors = _validate_record(record, index, image_directory)
            if errors:
                invalid_records.extend(errors)
                continue
            if normalized["slug"] in seen_slugs:
                invalid_records.append(f"record {index}: duplicate id {normalized['slug']}")
                continue
            seen_slugs.add(normalized["slug"])
            if record["image"].get("filename") and not normalized["image_filename"]:
                missing_images.append(record["image"]["filename"])
            valid_records.append(normalized)

        if invalid_records:
            details = "; ".join(invalid_records[:10])
            raise CommandError(
                f"Food import stopped: {len(invalid_records)} invalid field(s). {details}"
            )

        created_count = 0
        updated_count = 0
        with transaction.atomic():
            dataset_slugs = [record["slug"] for record in valid_records]
            Food.objects.filter(slug__isnull=False).exclude(slug__in=dataset_slugs).update(is_active=False)
            for record in valid_records:
                _, created = Food.objects.update_or_create(
                    slug=record["slug"],
                    defaults=record,
                )
                if created:
                    created_count += 1
                else:
                    updated_count += 1

        for filename in missing_images:
            self.stderr.write(self.style.WARNING(f"Missing local image: {filename}"))
        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {len(valid_records)} foods ({created_count} created, "
                f"{updated_count} updated); {len(missing_images)} image(s) missing."
            )
        )
