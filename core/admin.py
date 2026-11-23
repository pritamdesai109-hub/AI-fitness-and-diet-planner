from django.contrib import admin

from .models import Exercise, Food, MealEntry, Profile, ProgressRecord


admin.site.register(Profile)
admin.site.register(Exercise)


@admin.register(Food)
class FoodAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "is_vegetarian", "is_active", "nutrition_basis")
    list_filter = ("category", "is_vegetarian", "is_active")
    search_fields = ("name", "slug")


admin.site.register(MealEntry)
admin.site.register(ProgressRecord)
