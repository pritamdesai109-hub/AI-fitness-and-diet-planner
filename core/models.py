from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.templatetags.static import static
from django.utils import timezone


class Profile(models.Model):
    GOAL_CHOICES = [
        ("weight_loss", "Weight loss"),
        ("muscle_gain", "Muscle gain"),
        ("maintenance", "Maintain weight"),
    ]
    ACTIVITY_CHOICES = [
        ("low", "Sedentary — mostly sitting, little planned exercise"),
        ("light", "Lightly active — regular walking or home workouts"),
        ("moderate", "Moderately active — exercise several days each week"),
        ("high", "Very active — frequent intense exercise or gym training"),
    ]
    DIET_CHOICES = [
        ("vegetarian", "Vegetarian"),
        ("non_vegetarian", "Non-vegetarian"),
        ("eggetarian", "Eggitarian (eggs only; no meat or fish)"),
    ]
    CALCULATION_SEX_CHOICES = [
        ("female", "Female formula coefficient"),
        ("male", "Male formula coefficient"),
    ]
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    goal = models.CharField(max_length=20, choices=GOAL_CHOICES, blank=True)
    age = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(13), MaxValueValidator(120)])
    calculation_sex = models.CharField(max_length=8, choices=CALCULATION_SEX_CHOICES, blank=True)
    height_cm = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True, validators=[MinValueValidator(1)])
    current_weight_kg = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True, validators=[MinValueValidator(1)])
    target_weight_kg = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True, validators=[MinValueValidator(1)])
    goal_target_date = models.DateField(null=True, blank=True, editable=False)
    activity_level = models.CharField(max_length=12, choices=ACTIVITY_CHOICES, blank=True)
    allergies = models.CharField(max_length=255, blank=True, editable=False)
    dietary_preference = models.CharField(max_length=30, choices=DIET_CHOICES, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.email}'s profile"

    @property
    def is_complete(self):
        return (
            self.goal in dict(self.GOAL_CHOICES)
            and self.age is not None
            and self.calculation_sex in dict(self.CALCULATION_SEX_CHOICES)
            and self.height_cm is not None
            and self.current_weight_kg is not None
            and self.target_weight_kg is not None
            and self.activity_level in dict(self.ACTIVITY_CHOICES)
            and self.dietary_preference in dict(self.DIET_CHOICES)
        )

    @property
    def bmi(self):
        if not self.height_cm or not self.current_weight_kg or self.height_cm <= 0 or self.current_weight_kg <= 0:
            return None
        height_m = float(self.height_cm) / 100
        return round(float(self.current_weight_kg) / (height_m * height_m), 1)


class Exercise(models.Model):
    external_id = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=100, blank=True)
    equipment = models.CharField(max_length=255, blank=True)
    muscles = models.CharField(max_length=255, blank=True)
    image_url = models.URLField(blank=True)
    video_url = models.URLField(blank=True)
    video_codec = models.CharField(max_length=30, blank=True)
    video_embeddable = models.BooleanField(default=False)
    license_name = models.CharField(max_length=120, blank=True)
    license_url = models.URLField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def video_mime_type(self):
        if self.video_url.lower().split("?", 1)[0].endswith(".mp4"):
            return "video/mp4"
        if self.video_url.lower().split("?", 1)[0].endswith(".webm"):
            return "video/webm"
        return ""


class Food(models.Model):
    slug = models.SlugField(max_length=120, unique=True, null=True, blank=True)
    name = models.CharField(max_length=180)
    category = models.CharField(max_length=80, blank=True, default="")
    aliases = models.JSONField(default=dict, blank=True)
    search_terms = models.JSONField(default=list, blank=True)
    image_filename = models.CharField(max_length=255, blank=True, default="")
    food_state = models.CharField(max_length=80, blank=True, default="")
    nutrition_basis = models.CharField(max_length=80, blank=True, default="")
    calories_per_100g = models.DecimalField(max_digits=10, decimal_places=3, validators=[MinValueValidator(0)])
    protein_per_100g = models.DecimalField(max_digits=10, decimal_places=3, validators=[MinValueValidator(0)])
    carbs_per_100g = models.DecimalField(max_digits=10, decimal_places=3, validators=[MinValueValidator(0)])
    fat_per_100g = models.DecimalField(max_digits=10, decimal_places=3, validators=[MinValueValidator(0)])
    fiber_per_100g = models.DecimalField(max_digits=10, decimal_places=3, default=0, validators=[MinValueValidator(0)])
    sugar_per_100g = models.DecimalField(max_digits=10, decimal_places=3, default=0, validators=[MinValueValidator(0)])
    sodium_per_100g = models.DecimalField(max_digits=10, decimal_places=3, default=0, validators=[MinValueValidator(0)])
    serving_options = models.JSONField(default=list, blank=True)
    nutrition_source = models.JSONField(default=dict, blank=True)
    is_vegetarian = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def image_url(self):
        return static(f"files/{self.image_filename}") if self.image_filename else ""

    @property
    def food_state_label(self):
        return self.food_state.replace("_", " ").title() if self.food_state else "Not specified"

    @property
    def nutrition_status_label(self):
        status = (self.nutrition_source or {}).get("current_value_status", "")
        if status == "provisional_estimate_needs_source_verification":
            return "Provisional estimate — source verification needed"
        if status == "recipe_dependent_estimate_needs_recipe_standardization":
            return "Recipe-dependent estimate — standardization needed"
        return "Nutrition status not verified"


class MealEntry(models.Model):
    MEAL_CHOICES = [
        ("breakfast", "Breakfast"),
        ("snack", "Snacks"),
        ("lunch", "Lunch"),
        ("dinner", "Dinner"),
    ]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="meal_entries")
    saved_plan = models.ForeignKey(
        "SavedPlan",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meal_entries",
    )
    plan_item_index = models.PositiveSmallIntegerField(null=True, blank=True)
    food = models.ForeignKey(Food, on_delete=models.SET_NULL, null=True, blank=True, related_name="meal_entries")
    date = models.DateField()
    meal_type = models.CharField(max_length=12, choices=MEAL_CHOICES)
    food_name = models.CharField(max_length=160)
    quantity = models.CharField(max_length=60, blank=True)
    serving_unit = models.CharField(max_length=30, blank=True)
    weight_in_grams = models.DecimalField(max_digits=8, decimal_places=3, default=0, validators=[MinValueValidator(0)])
    calories = models.DecimalField(max_digits=10, decimal_places=3, default=0, validators=[MinValueValidator(0)])
    protein_g = models.DecimalField(max_digits=10, decimal_places=3, default=0, validators=[MinValueValidator(0)])
    carbs_g = models.DecimalField(max_digits=10, decimal_places=3, default=0, validators=[MinValueValidator(0)])
    fat_g = models.DecimalField(max_digits=10, decimal_places=3, default=0, validators=[MinValueValidator(0)])
    fiber_g = models.DecimalField(max_digits=10, decimal_places=3, default=0, validators=[MinValueValidator(0)])
    sugar_g = models.DecimalField(max_digits=10, decimal_places=3, default=0, validators=[MinValueValidator(0)])
    sodium_mg = models.DecimalField(max_digits=10, decimal_places=3, default=0, validators=[MinValueValidator(0)])
    consumed = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "meal_type", "created_at"]


class ProgressRecord(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="progress_records")
    date = models.DateField()
    weight_kg = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True, validators=[MinValueValidator(1)])
    waist_cm = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True, validators=[MinValueValidator(1)])
    steps = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MaxValueValidator(200000)],
    )
    activity_minutes = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MaxValueValidator(1440)],
    )
    water_ml = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MaxValueValidator(10000)])
    notes = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(fields=["user", "date"], name="unique_progress_record_per_day"),
        ]

    def __str__(self):
        return f"{self.user.email} progress on {self.date}"


class SavedPlan(models.Model):
    PLAN_CHOICES = [
        ("meal", "Meal plan"),
        ("workout", "Workout plan"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_plans")
    plan_type = models.CharField(max_length=12, choices=PLAN_CHOICES)
    date = models.DateField(default=timezone.localdate)
    payload = models.JSONField(default=dict, blank=True)
    completed_items = models.JSONField(default=list, blank=True)
    is_added_to_tracker = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_plan_type_display()} for {self.user.email} on {self.date}"
