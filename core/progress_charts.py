from datetime import timedelta


PERIOD_DAYS = {
    "7d": 7,
    "30d": 30,
    "3m": 90,
    "6m": 183,
    "1y": 365,
}

PERIOD_LABELS = {
    "7d": "7 days",
    "30d": "30 days",
    "3m": "3 months",
    "6m": "6 months",
    "1y": "1 year",
}


def selected_period(value):
    return value if value in PERIOD_DAYS else "30d"


def period_start(period, end_date):
    return end_date - timedelta(days=PERIOD_DAYS[period] - 1)


def _date_label(value):
    return f"{value.strftime('%b')} {value.day}"


def build_line_chart(start_date, end_date, series, unit, precision=0):
    chart_values = [
        float(value)
        for item in series
        for _, value in item["values"]
        if value is not None
    ]
    if not chart_values:
        return None

    width = 760
    height = 260
    left = 58
    right = 18
    top = 18
    bottom = 42
    plot_width = width - left - right
    plot_height = height - top - bottom
    minimum = min(chart_values)
    maximum = max(chart_values)
    if minimum == maximum:
        padding = max(abs(minimum) * 0.05, 1)
    else:
        padding = (maximum - minimum) * 0.08
    minimum -= padding
    maximum += padding

    total_days = max((end_date - start_date).days, 1)

    def x_position(point_date):
        fraction = (point_date - start_date).days / total_days
        return round(left + max(0, min(1, fraction)) * plot_width, 1)

    def y_position(value):
        fraction = (float(value) - minimum) / (maximum - minimum)
        return round(top + (1 - fraction) * plot_height, 1)

    rendered_series = []
    for item in series:
        values = sorted(
            ((point_date, value) for point_date, value in item["values"] if value is not None),
            key=lambda point: point[0],
        )
        paths = []
        markers = []
        segment = []
        previous_date = None
        max_gap_days = item.get("max_gap_days")
        for point_date, value in values:
            if (
                segment
                and max_gap_days is not None
                and (point_date - previous_date).days > max_gap_days
            ):
                if len(segment) > 1:
                    paths.append(" ".join(segment))
                segment = []
            x = x_position(point_date)
            y = y_position(value)
            segment.append(f"{x},{y}")
            display_value = f"{float(value):.{precision}f}"
            markers.append(
                {
                    "x": x,
                    "y": y,
                    "title": f"{point_date.isoformat()}: {display_value} {unit}",
                }
            )
            previous_date = point_date
        if len(segment) > 1:
            paths.append(" ".join(segment))
        rendered_series.append(
            {
                "key": item["key"],
                "label": item["label"],
                "paths": paths,
                "markers": markers,
            }
        )

    y_ticks = []
    for index in range(5):
        value = maximum - (maximum - minimum) * index / 4
        y_ticks.append(
            {
                "y": round(top + plot_height * index / 4, 1),
                "label": f"{value:.{precision}f}",
            }
        )

    x_ticks = []
    span = (end_date - start_date).days
    for index in range(5):
        tick_date = start_date + timedelta(days=round(span * index / 4))
        x_ticks.append({"x": x_position(tick_date), "label": _date_label(tick_date)})

    return {
        "width": width,
        "height": height,
        "left": left,
        "right": width - right,
        "top": top,
        "bottom": height - bottom,
        "series": rendered_series,
        "x_ticks": x_ticks,
        "y_ticks": y_ticks,
        "unit": unit,
    }


