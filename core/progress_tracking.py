from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum

from .calculations import estimate_daily_targets
from .models import MealEntry, ProgressRecord
from .progress_charts import (
    PERIOD_DAYS,
    PERIOD_LABELS,
    build_line_chart,
    period_start,
)


def _nutrition_by_day(user, start_date, end_date):
    return list(
        MealEntry.objects.filter(
            user=user,
            consumed=True,
            date__range=(start_date, end_date),
        )
        .values("date")
        .annotate(
            calories=Sum("calories"),
            protein_g=Sum("protein_g"),
        )
        .order_by("date")
    )


def _average(rows, field):
    if not rows:
        return None
    total = sum((row[field] or Decimal("0") for row in rows), Decimal("0"))
    return total / len(rows)


def _nutrition_series(rows, start_date, end_date, weekly):
    if weekly:
        buckets = {}
        for row in rows:
            index = (row["date"] - start_date).days // 7
            bucket_date = start_date + timedelta(days=index * 7)
            bucket = buckets.setdefault(
                bucket_date,
                {"calories": Decimal("0"), "protein_g": Decimal("0"), "days": 0},
            )
            bucket["calories"] += row["calories"] or Decimal("0")
            bucket["protein_g"] += row["protein_g"] or Decimal("0")
            bucket["days"] += 1
        actual = {
            field: [
                (bucket_date, bucket[field] / bucket["days"])
                for bucket_date, bucket in sorted(buckets.items())
            ]
            for field in ("calories", "protein_g")
        }
        table_rows = [
            {
                "date": bucket_date,
                "calories": bucket["calories"] / bucket["days"],
                "protein_g": bucket["protein_g"] / bucket["days"],
                "logged_days": bucket["days"],
            }
            for bucket_date, bucket in sorted(buckets.items())
        ]
        target_dates = []
        cursor = start_date
        while cursor <= end_date:
            target_dates.append(cursor)
            cursor += timedelta(days=7)
        return actual, target_dates, table_rows

    daily = {
        field: [(row["date"], row[field] or Decimal("0")) for row in rows]
        for field in ("calories", "protein_g")
    }
    target_dates = []
    cursor = start_date
    while cursor <= end_date:
        target_dates.append(cursor)
        cursor += timedelta(days=1)
    table_rows = [
        {
            "date": row["date"],
            "calories": row["calories"],
            "protein_g": row["protein_g"],
            "logged_days": 1,
        }
        for row in rows
    ]
    return daily, target_dates, table_rows


def _nutrition_chart(start_date, end_date, actual, target_dates, target, field, unit, weekly):
    series = []
    if target is not None:
        series.append(
            {
                "key": "target",
                "label": "Current daily target",
                "values": [(day, target) for day in target_dates],
            }
        )
    if actual[field]:
        series.append(
            {
                "key": "actual",
                "label": "Average per logged day" if weekly else "Consumed",
                "values": actual[field],
                "max_gap_days": 7 if weekly else 1,
            }
        )
    return build_line_chart(
        start_date,
        end_date,
        series,
        unit,
        precision=1 if unit == "g" else 0,
    )


def build_progress_context(user, profile, period, today):
    period = period if period in PERIOD_DAYS else "30d"
    start_date = period_start(period, today)
    weekly_charts = PERIOD_DAYS[period] > 30
    targets = estimate_daily_targets(profile)

    weight_history = ProgressRecord.objects.filter(
        user=user,
        weight_kg__isnull=False,
    ).order_by("date")
    first_weigh_in = weight_history.first()
    latest_weigh_in = weight_history.last()

    nutrition_rows = _nutrition_by_day(user, start_date, today)
    nutrition_actual, nutrition_target_dates, nutrition_table_rows = _nutrition_series(
        nutrition_rows,
        start_date,
        today,
        weekly_charts,
    )
    calorie_chart = _nutrition_chart(
        start_date,
        today,
        nutrition_actual,
        nutrition_target_dates,
        targets["calories"],
        "calories",
        "kcal",
        weekly_charts,
    )
    protein_chart = _nutrition_chart(
        start_date,
        today,
        nutrition_actual,
        nutrition_target_dates,
        targets["protein_g"],
        "protein_g",
        "g",
        weekly_charts,
    )

    weight_change = None
    goal_progress = None
    if first_weigh_in and latest_weigh_in:
        weight_change = round(
            float(latest_weigh_in.weight_kg - first_weigh_in.weight_kg),
            1,
        )
        planned_change = profile.target_weight_kg - first_weigh_in.weight_kg if profile.target_weight_kg else None
        if planned_change:
            raw_progress = (
                float(latest_weigh_in.weight_kg - first_weigh_in.weight_kg)
                / float(planned_change)
                * 100
            )
            goal_progress = round(max(0, min(100, raw_progress)))

    period_options = [
        {
            "value": key,
            "label": PERIOD_LABELS[key],
            "selected": key == period,
        }
        for key in PERIOD_DAYS
    ]
    return {
        "period": period,
        "period_options": period_options,
        "profile": profile,
        "targets": targets,
        "calorie_chart": calorie_chart,
        "protein_chart": protein_chart,
        "nutrition_table_rows": nutrition_table_rows,
        "nutrition_table_is_weekly": weekly_charts,
        "chart_frequency_note": (
            "Weekly averages; nutrition averages include only days with consumed meals recorded."
            if weekly_charts
            else "Daily values; days without consumed meal records are left unfilled, not counted as zero."
        ),
        "target_history_note": (
            "Current profile targets are shown for comparison across this date range; past target changes are not stored."
        ),
        "first_weigh_in": first_weigh_in,
        "latest_weigh_in": latest_weigh_in,
        "weight_change": weight_change,
        "goal_progress": goal_progress,
        "average_calories": _average(nutrition_rows, "calories"),
        "average_protein": _average(nutrition_rows, "protein_g"),
        "nutrition_days_logged": len(nutrition_rows),
        "recent_records": list(
            ProgressRecord.objects.filter(user=user).order_by("-date")[:30]
        ),
    }
