from datetime import timedelta
from io import StringIO
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .forms import ProfileForm, RegistrationForm
from .ai_planning import PlanningError, generate_plan
from .integrations import ExerciseAPIError, _normalise_exercise, _wger_headers
from .models import Exercise, Food, MealEntry, Profile, ProgressRecord, SavedPlan
from .calculations import estimate_daily_targets, estimate_energy
from .nutrition import find_foods


class FitnessSiteTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="runner",
            email="runner@example.com",
            first_name="Runner",
            password="a-safe-test-password",
        )
        self.profile = Profile.objects.create(user=self.user, height_cm=170, current_weight_kg=72)

    def complete_profile(self, **overrides):
        values = {
            "goal": "weight_loss",
            "age": 30,
            "calculation_sex": "female",
            "height_cm": 170,
            "current_weight_kg": 72,
            "target_weight_kg": 65,
            "activity_level": "moderate",
            "dietary_preference": "vegetarian",
        }
        values.update(overrides)
        for field, value in values.items():
            setattr(self.profile, field, value)
        self.profile.save()
        return self.profile

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('dashboard')}")

    def test_login_does_not_offer_unavailable_email_password_reset(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Forgot your password?")

    def test_shared_layout_has_theme_toggle_and_hides_skip_link_text(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-theme-toggle")
        self.assertContains(response, "theme.js?v=2")
        self.assertContains(response, "site.css?v=7")
        self.assertNotContains(response, "Skip to content")

    def test_registration_only_asks_for_name_email_and_password(self):
        form = RegistrationForm(
            data={
                "first_name": "Fit Person",
                "email": "new@example.com",
                "password1": "a-safe-test-password",
                "password2": "a-safe-test-password",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            list(form.fields),
            ["first_name", "email", "password1", "password2"],
        )
        self.assertEqual(form.fields["password1"].help_text, "")
        self.assertEqual(form.fields["password2"].help_text, "")
        user = form.save()
        self.assertTrue(user.check_password("a-safe-test-password"))
        self.assertEqual(user.first_name, "Fit Person")
        self.assertEqual(user.email, "new@example.com")
        self.assertEqual(user.username, "new@example.com")

    def test_registration_requires_a_unique_email(self):
        User.objects.create_user(username="used@example.com", email="used@example.com", password="x")
        duplicate_email = RegistrationForm(
            data={
                "first_name": "New User",
                "email": "USED@example.com",
                "password1": "a-safe-test-password",
                "password2": "a-safe-test-password",
            }
        )
        self.assertFalse(duplicate_email.is_valid())
        self.assertIn("email", duplicate_email.errors)

    def test_registration_logs_in_and_redirects_to_required_profile_setup(self):
        response = self.client.post(
            reverse("register"),
            {
                "first_name": "Fit Person",
                "email": "new@example.com",
                "password1": "a-safe-test-password",
                "password2": "a-safe-test-password",
            },
        )
        self.assertRedirects(response, reverse("onboarding"), fetch_redirect_response=False)
        user = User.objects.get(email="new@example.com")
        self.assertTrue(Profile.objects.filter(user=user).exists())
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_email_login_normalizes_email_case(self):
        user = User.objects.create_user(
            username="mixed@example.com",
            email="mixed@example.com",
            password="a-safe-test-password",
        )
        response = self.client.post(
            reverse("login"),
            {"username": "MIXED@Example.com", "password": "a-safe-test-password"},
        )
        self.assertRedirects(response, reverse("dashboard"), fetch_redirect_response=False)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_profile_form_requires_the_profile_fields_and_only_three_diet_choices(self):
        form = ProfileForm()
        self.assertEqual(
            set(form.fields),
            {
                "goal",
                "age",
                "calculation_sex",
                "height_cm",
                "current_weight_kg",
                "target_weight_kg",
                "activity_level",
                "dietary_preference",
            },
        )
        self.assertTrue(all(field.required for field in form.fields.values()))
        self.assertEqual(
            [value for value, _ in form.fields["dietary_preference"].choices if value],
            ["vegetarian", "non_vegetarian", "eggetarian"],
        )
        data = {
            "goal": "weight_loss",
            "age": "30",
            "calculation_sex": "female",
            "height_cm": "170",
            "current_weight_kg": "72",
            "target_weight_kg": "65",
            "activity_level": "moderate",
            "dietary_preference": "eggetarian",
        }
        self.assertTrue(ProfileForm(data=data, instance=self.profile).is_valid())
        del data["target_weight_kg"]
        incomplete = ProfileForm(data=data, instance=self.profile)
        self.assertFalse(incomplete.is_valid())
        self.assertIn("target_weight_kg", incomplete.errors)

    def test_bmi_is_only_shown_when_profile_values_are_valid(self):
        self.assertEqual(self.profile.bmi, 24.9)
        self.profile.height_cm = 0
        self.assertIsNone(self.profile.bmi)

    def test_energy_estimate_requires_adult_profile_and_all_formula_inputs(self):
        self.assertIsNone(estimate_energy(self.profile))
        self.profile.age = 30
        self.profile.calculation_sex = "female"
        self.profile.activity_level = "moderate"
        self.profile.goal = "maintenance"
        result = estimate_energy(self.profile)
        self.assertIsNotNone(result)
        self.assertEqual(result["target"], result["tdee"])
        self.profile.age = 17
        self.assertIsNone(estimate_energy(self.profile))

    def test_daily_targets_are_profile_based_and_calorie_settings_are_configurable(self):
        self.profile.age = 30
        self.profile.calculation_sex = "female"
        self.profile.goal = "weight_loss"
        self.profile.activity_level = "moderate"
        self.profile.save()

        targets = estimate_daily_targets(self.profile)
        self.assertEqual(targets["calories"], 2053)
        self.assertEqual(targets["protein_g"], 115)
        self.assertEqual(targets["steps"], 9000)
        self.assertEqual(targets["activity_minutes"], 22)
        self.assertEqual(targets["weekly_activity_minutes"], 150)
        self.assertGreater(targets["carbs_g"], 0)
        self.assertGreater(targets["fat_g"], 0)

        with override_settings(
            FITFORGE_ACTIVITY_FACTORS={"moderate": 1.0},
            FITFORGE_GOAL_CALORIE_ADJUSTMENTS={"weight_loss": 0.0},
        ):
            configured = estimate_energy(self.profile)
        self.assertEqual(configured["target"], configured["bmr"])

    def test_exercise_normalization_uses_english_instructions_and_real_media(self):
        exercise = _normalise_exercise(
            {
                "id": 321,
                "category": {"name": "Legs"},
                "equipment": [{"name": "Barbell"}],
                "muscles": [{"name": "Quadriceps"}],
                "translations": [
                    {"language": 7, "name": "Agachamento", "description": "<p>Texto</p>"},
                    {"language": 2, "name": "Barbell squat", "description": "<p>Stand tall.</p><ol><li>Brace your core.</li><li>Squat down.</li></ol>"},
                ],
                "images": [{"image": "https://wger.de/media/squat.jpg", "is_main": True}],
                "videos": [{"video": "https://wger.de/media/squat.mp4", "codec": "h264", "is_main": True}],
                "license": {"short_name": "CC-BY-SA", "url": "http://creativecommons.org/licenses/by-sa/4.0/"},
            }
        )
        self.assertEqual(exercise["name"], "Barbell squat")
        self.assertEqual(exercise["description"], "Stand tall.\n• Brace your core.\n• Squat down.")
        self.assertEqual(exercise["image_url"], "https://wger.de/media/squat.jpg")
        self.assertTrue(exercise["video_embeddable"])
        self.assertEqual(exercise["license_url"], "https://creativecommons.org/licenses/by-sa/4.0/")

    def test_exercise_without_english_translation_is_not_mislabeled(self):
        exercise = _normalise_exercise(
            {"id": 322, "translations": [{"language": 7, "name": "Agachamento"}]}
        )
        self.assertIsNone(exercise)

    @patch(
        "core.views.get_exercises",
        side_effect=ExerciseAPIError("The exercise library is temporarily unavailable."),
    )
    def test_exercise_library_shows_saved_guides_when_wger_is_unavailable(self, _get_exercises):
        Exercise.objects.create(
            external_id=321,
            name="Saved squat guide",
            category="Legs",
            image_url="https://wger.de/media/squat.jpg",
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("exercises"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The exercise library is temporarily unavailable.")
        self.assertContains(response, "Showing previously saved exercise guides.")
        self.assertContains(response, "Saved squat guide")
        self.assertEqual(response.context["page_obj"].paginator.count, 1)

    def test_wger_api_key_is_sent_as_a_token_without_exposing_it(self):
        with patch("core.integrations.settings.WGER_API_KEY", "test-token"):
            self.assertEqual(_wger_headers()["Authorization"], "Token test-token")

    @patch(
        "core.views.get_exercises",
        return_value=[
            {
                "id": 73,
                "name": "Bench Press",
                "description": "Set up on a bench.",
                "category": "Chest",
                "equipment": "Barbell",
                "muscles": "Pectoralis major",
                "image_url": "https://wger.de/media/bench.png",
                "video_url": "",
            },
            {
                "id": 74,
                "name": "No media movement",
                "description": "",
                "category": "Chest",
                "equipment": "",
                "muscles": "",
                "image_url": "",
                "video_url": "",
            },
            {
                "id": 78,
                "name": "Unsupported video only",
                "description": "",
                "category": "Chest",
                "equipment": "",
                "muscles": "",
                "image_url": "",
                "video_url": "https://wger.de/media/unsupported.mov",
                "video_embeddable": False,
            },
        ],
    )
    def test_exercise_library_shows_media_cards_that_open_detail(self, _get_exercises):
        self.client.force_login(self.user)
        response = self.client.get(reverse("exercises"))
        self.assertContains(response, "Bench Press")
        self.assertNotContains(response, "No media movement")
        self.assertNotContains(response, "Unsupported video only")
        self.assertContains(response, reverse("exercise_detail", args=[73]))

        filtered = self.client.get(reverse("exercises"), {"q": "bench", "category": "Chest"})
        self.assertContains(filtered, "Bench Press")
        self.assertNotContains(filtered, "No media movement")
        self.assertContains(filtered, 'value="Chest" selected', html=False)

    def test_exercise_detail_shows_instructions_and_media(self):
        exercise = Exercise.objects.create(
            external_id=75,
            name="Dumbbell press",
            description="Lie back on the bench.\nPress the weights upward.",
            image_url="https://wger.de/media/press.png",
            muscles="Chest",
            equipment="Dumbbells",
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("exercise_detail", args=[exercise.external_id]))
        self.assertContains(response, "How to do it")
        self.assertContains(response, "Press the weights upward.")
        self.assertContains(response, "https://wger.de/media/press.png")

    def test_exercise_video_uses_muted_inline_autoplay_without_download_link(self):
        exercise = Exercise.objects.create(
            external_id=76,
            name="Barbell lunge",
            video_url="https://wger.de/media/barbell-lunge.mp4",
            video_codec="h264",
            video_embeddable=True,
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("exercise_detail", args=[exercise.external_id]))
        self.assertContains(response, "<video", html=False)
        self.assertContains(response, "controls autoplay muted loop playsinline preload=\"metadata\"", html=False)
        self.assertNotContains(response, "type=\"video/quicktime\"", html=False)
        self.assertNotContains(response, f'href="{exercise.video_url}"')
        self.assertContains(response, "Use the player controls to pause, replay, or turn the sound on.")

    def test_unsupported_exercise_video_uses_image_without_download_link(self):
        exercise = Exercise.objects.create(
            external_id=77,
            name="Dumbbell lunge",
            image_url="https://wger.de/media/lunge.png",
            video_url="https://wger.de/media/lunge.mov",
            video_codec="hevc",
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("exercise_detail", args=[exercise.external_id]))
        self.assertNotContains(response, "<video", html=False)
        self.assertContains(response, exercise.image_url)
        self.assertContains(response, "not supported for in-page playback")
        self.assertNotContains(response, f'href="{exercise.video_url}"')

    def test_food_library_searches_local_aliases_in_multiple_languages(self):
        almonds = Food.objects.create(
            slug="almonds",
            name="Almonds",
            category="Nuts & Seeds",
            aliases={
                "english": ["Almonds"],
                "hinglish": ["Badam"],
                "marathi": ["बदाम"],
            },
            search_terms=["almond", "badam", "बदाम"],
            image_filename="Almonds.png",
            calories_per_100g=579,
            protein_per_100g=21.2,
            carbs_per_100g=21.6,
            fat_per_100g=49.9,
        )
        Food.objects.create(
            slug="rice",
            name="White Rice (Cooked)",
            category="Grains",
            aliases={"hinglish": ["Chawal", "Bhat"]},
            search_terms=["rice", "chawal", "bhat"],
            calories_per_100g=130,
            protein_per_100g=2.7,
            carbs_per_100g=28.2,
            fat_per_100g=0.3,
        )
        self.assertEqual([food.slug for food in find_foods("Badam")], ["almonds"])
        self.assertEqual([food.slug for food in find_foods("बदाम")], ["almonds"])
        self.assertEqual([food.slug for food in find_foods("almond")], ["almonds"])
        self.assertEqual([food.slug for food in find_foods("Chawal")], ["rice"])
        self.assertEqual([food.slug for food in find_foods("Bhat")], ["rice"])

        self.client.force_login(self.user)
        response = self.client.get(reverse("nutrition"), {"q": "बदाम"})
        self.assertContains(response, "Almonds")
        self.assertNotContains(response, "White Rice")
        self.assertContains(response, "/static/files/Almonds.png")
        self.assertEqual(almonds.slug, "almonds")

    def test_food_import_is_idempotent_and_uses_local_image_files(self):
        call_command("import_foods", stdout=StringIO())
        first_count = Food.objects.filter(slug__isnull=False).count()
        call_command("import_foods", stdout=StringIO())
        self.assertEqual(first_count, 100)
        self.assertEqual(Food.objects.filter(slug__isnull=False).count(), first_count)
        almonds = Food.objects.get(slug="almonds")
        self.assertEqual(almonds.image_filename, "Almonds.png")
        self.assertEqual(almonds.image_url, "/static/files/Almonds.png")
        self.assertTrue(almonds.is_active)

    def test_food_detail_shows_provisional_values_and_json_servings(self):
        food = Food.objects.create(
            slug="whole_egg",
            name="Whole Egg",
            category="Dairy",
            image_filename="Whole Egg.png",
            calories_per_100g=155,
            protein_per_100g=12.6,
            carbs_per_100g=1.1,
            fat_per_100g=10.6,
            serving_options=[{"label": "1 egg", "weight_g": 50.0}],
            nutrition_source={
                "current_value_status": "provisional_estimate_needs_source_verification",
                "notes": "Verify this estimate.",
            },
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("food_detail", args=[food.slug]))
        self.assertContains(response, "Whole Egg")
        self.assertContains(response, "Provisional estimate")
        self.assertContains(response, "1 egg")
        self.assertContains(response, "/static/Whole%20Egg.png")
        self.assertContains(response, "food-nutrition-data")

    def test_add_to_meal_calculates_database_nutrients_and_keeps_plan_separate(self):
        food = Food.objects.create(
            slug="chicken_breast",
            name="Chicken Breast",
            category="Non-vegetarian",
            calories_per_100g=120,
            protein_per_100g=22.5,
            carbs_per_100g=0,
            fat_per_100g=2.6,
            fiber_per_100g=0,
            sugar_per_100g=0,
            sodium_per_100g=74,
            serving_options=[{"label": "1 portion", "weight_g": 100}],
        )
        self.client.force_login(self.user)
        today = timezone.localdate().isoformat()
        detail_url = reverse("add_food_to_log", args=[food.slug])
        planned_response = self.client.post(
            detail_url,
            {
                "entry_type": "plan",
                "meal_type": "lunch",
                "date": today,
                "serving_option": "0",
                "serving_count": "1.5",
            },
        )
        self.assertRedirects(
            planned_response,
            f"{reverse('nutrition_log')}?date={today}",
            fetch_redirect_response=False,
        )
        entry = MealEntry.objects.get(user=self.user, food=food)
        self.assertFalse(entry.consumed)
        self.assertEqual(entry.weight_in_grams, 150)
        self.assertEqual(entry.calories, 180)
        self.assertEqual(entry.protein_g, 33.750)
        self.assertEqual(entry.sodium_mg, 111)

        log_url = reverse("nutrition_log")
        planned_page = self.client.get(log_url, {"date": today})
        self.assertContains(planned_page, "Planned meals")
        self.assertContains(planned_page, "0.0</strong>")
        self.client.post(reverse("toggle_meal", args=[entry.pk]))
        entry.refresh_from_db()
        self.assertTrue(entry.consumed)
        self.assertEqual(MealEntry.objects.filter(user=self.user, food=food).count(), 1)
        consumed_page = self.client.get(log_url, {"date": today})
        self.assertContains(consumed_page, "180.0")

    def test_future_food_entries_remain_planned_until_the_date_arrives(self):
        food = Food.objects.create(
            slug="future-rice",
            name="Future rice",
            calories_per_100g=130,
            protein_per_100g=3,
            carbs_per_100g=28,
            fat_per_100g=0,
        )
        self.client.force_login(self.user)
        future_date = (timezone.localdate() + timedelta(days=1)).isoformat()
        add_url = reverse("add_food_to_log", args=[food.slug])
        self.client.post(
            add_url,
            {
                "entry_type": "plan",
                "meal_type": "lunch",
                "date": future_date,
                "serving_option": "custom",
                "grams": "100",
            },
        )
        entry = MealEntry.objects.get(user=self.user, food=food)
        self.assertFalse(entry.consumed)
        response = self.client.post(reverse("toggle_meal", args=[entry.pk]))
        self.assertRedirects(
            response,
            f"{reverse('nutrition_log')}?date={future_date}",
            fetch_redirect_response=False,
        )
        entry.refresh_from_db()
        self.assertFalse(entry.consumed)
        self.client.post(
            add_url,
            {
                "entry_type": "meal",
                "meal_type": "lunch",
                "date": future_date,
                "serving_option": "custom",
                "grams": "100",
            },
        )
        self.assertEqual(MealEntry.objects.filter(user=self.user, food=food).count(), 1)

    def test_food_database_values_are_scaled_to_the_logged_portion(self):
        self.client.force_login(self.user)
        food = Food.objects.create(
            slug="sample-food",
            name="Sample food",
            calories_per_100g=100,
            protein_per_100g=10,
            carbs_per_100g=20,
            fat_per_100g=5,
        )
        response = self.client.post(
            reverse("add_food_to_log", args=[food.slug]),
            {
                "serving_option": "custom",
                "grams": "150",
                "entry_type": "meal",
                "meal_type": "lunch",
                "date": "2026-11-20",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"{reverse('nutrition_log')}?date=2026-11-20")
        entry = MealEntry.objects.get(user=self.user, food=food)
        self.assertEqual(entry.calories, 150)
        self.assertEqual(str(entry.protein_g), "15.000")
        self.assertEqual(entry.quantity, "150 g")

    def test_invalid_serving_index_cannot_select_from_the_end_of_the_list(self):
        food = Food.objects.create(
            slug="one-portion",
            name="One portion",
            category="Other",
            calories_per_100g=100,
            protein_per_100g=10,
            carbs_per_100g=10,
            fat_per_100g=2,
            serving_options=[{"label": "1 serving", "weight_g": 100}],
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("add_food_to_log", args=[food.slug]),
            {
                "serving_option": "-1",
                "serving_count": "1",
                "entry_type": "meal",
                "meal_type": "breakfast",
                "date": "2026-11-20",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(MealEntry.objects.filter(user=self.user, food=food).exists())

    def test_progress_record_for_same_day_is_updated_not_duplicated(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("progress"),
            {
                "date": timezone.localdate().isoformat(),
                "weight_kg": "71.5",
                "waist_cm": "80",
                "steps": "5400",
                "activity_minutes": "35",
                "water_ml": "2100",
                "notes": "Updated",
            },
        )
        self.assertRedirects(response, f"{reverse('progress')}?period=30d")
        record = ProgressRecord.objects.get(user=self.user, date=timezone.localdate())
        self.assertEqual(ProgressRecord.objects.filter(user=self.user, date=timezone.localdate()).count(), 1)
        self.assertEqual(record.notes, "Updated")
        self.assertEqual(record.steps, 5400)
        self.assertEqual(record.activity_minutes, 35)
        self.assertEqual(record.water_ml, 2100)

    def test_progress_rejects_non_get_post_methods(self):
        self.client.force_login(self.user)
        response = self.client.put(reverse("progress"), {"steps": "5000"})
        self.assertEqual(response.status_code, 405)

    def test_editing_old_weigh_in_does_not_replace_current_profile_weight(self):
        today = timezone.localdate()
        ProgressRecord.objects.create(
            user=self.user,
            date=today - timedelta(days=3),
            weight_kg=72,
        )
        ProgressRecord.objects.create(
            user=self.user,
            date=today - timedelta(days=1),
            weight_kg=70,
        )
        self.profile.current_weight_kg = 70
        self.profile.save(update_fields=["current_weight_kg"])

        self.client.force_login(self.user)
        response = self.client.post(
            reverse("progress"),
            {
                "period": "30d",
                "date": (today - timedelta(days=3)).isoformat(),
                "weight_kg": "71.5",
                "waist_cm": "",
                "steps": "",
                "activity_minutes": "",
                "notes": "Corrected old entry",
            },
        )
        self.assertRedirects(response, f"{reverse('progress')}?period=30d")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.current_weight_kg, 70)

    def test_dashboard_uses_consumed_meals_recorded_activity_and_no_external_api(self):
        today = timezone.localdate()
        self.profile.age = 30
        self.profile.calculation_sex = "female"
        self.profile.goal = "weight_loss"
        self.profile.activity_level = "moderate"
        self.profile.target_weight_kg = 65
        self.profile.dietary_preference = "vegetarian"
        self.profile.save()
        MealEntry.objects.create(
            user=self.user,
            date=today,
            meal_type="breakfast",
            food_name="Logged meal",
            calories=1000,
            protein_g=60,
            carbs_g=100,
            fat_g=30,
            consumed=True,
        )
        MealEntry.objects.create(
            user=self.user,
            date=today,
            meal_type="lunch",
            food_name="Planned meal",
            calories=9000,
            protein_g=900,
            carbs_g=900,
            fat_g=900,
            consumed=False,
        )
        ProgressRecord.objects.create(
            user=self.user,
            date=today,
            steps=5400,
            activity_minutes=35,
        )
        self.client.force_login(self.user)
        with patch("core.views.get_exercises", side_effect=AssertionError("dashboard must not call wger")) as api:
            response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        api.assert_not_called()
        self.assertEqual(response.context["nutrition"]["calories"], 1000)
        self.assertEqual(response.context["nutrition"]["protein_g"], 60)
        self.assertEqual(response.context["today_record"].steps, 5400)
        self.assertEqual(response.context["nutrition_progress"][0]["percentage"], 49)
        self.assertContains(response, "5400")
        self.assertContains(response, "Nutrition today")
        self.assertContains(response, "Recorded activity and hydration")
        self.assertContains(response, "35 min")
        self.assertNotContains(response, "Quick actions")
        self.assertNotContains(response, "daily-summary-panel")
        self.assertNotContains(response, "Completed workouts")
        self.assertNotContains(response, "Completed workouts")

        nav = response.content.decode().split('<nav class="main-nav"', 1)[1].split("</nav>", 1)[0]
        self.assertEqual(nav.count("<a "), 4)
        self.assertNotIn(">Workouts<", nav)
        for route in ("dashboard", "exercises", "nutrition", "progress"):
            self.assertIn(reverse(route), nav)

    def test_dashboard_incomplete_profile_shows_setup_instead_of_invented_targets(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["profile_complete"])
        self.assertContains(response, "Finish setting up your fitness profile")
        self.assertContains(response, "Complete profile")
        self.assertContains(response, "—")
        self.assertNotContains(response, "daily-summary-panel")

    @patch(
        "core.views.generate_plan",
        return_value={
            "workout": [
                {"exercise_id": 131, "sets": 3, "reps": "10-12", "rest_seconds": 60, "tip": "Move with control."},
                {"exercise_id": 132, "sets": 3, "reps": 8, "rest_seconds": 60, "tip": "Keep a straight line."},
                {"exercise_id": 133, "sets": 3, "duration_seconds": 30, "rest_seconds": 45, "tip": "Breathe steadily."},
            ],
            "advice": "Stop if you feel pain.",
        },
    )
    def test_workout_planner_links_only_to_available_exercise_guides(self, generate):
        for exercise_id, name in ((131, "Bodyweight squat"), (132, "Push-up"), (133, "Plank")):
            Exercise.objects.create(
                external_id=exercise_id,
                name=name,
                equipment="Bodyweight",
                image_url=f"https://wger.de/media/{exercise_id}.jpg",
            )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("ai_workout"),
            {"level": "beginner"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["plan"]["workout"]), 3)
        self.assertContains(response, reverse("exercise_detail", args=[131]))
        self.assertContains(response, "30 sec")
        self.assertContains(response, "Stop if you feel pain.")
        prompt = generate.call_args.args[0]
        self.assertIn('"experience_level": "beginner"', prompt)
        self.assertIn('"id": 131', prompt)
        self.assertNotContains(response, "Available equipment")
        self.assertNotContains(response, "Today's workout focus")

    @patch(
        "core.views.generate_plan",
        return_value={
            "workout": [
                {"exercise_id": exercise_id, "sets": 2, "reps": 10, "rest_seconds": 60, "tip": "Move with control."}
                for exercise_id in (132, 133, 134)
            ],
        },
    )
    def test_workout_planner_avoids_exercises_from_recent_saved_sessions(self, generate):
        for exercise_id in (131, 132, 133, 134):
            Exercise.objects.create(
                external_id=exercise_id,
                name=f"Exercise {exercise_id}",
                image_url=f"https://wger.de/media/{exercise_id}.jpg",
            )
        SavedPlan.objects.create(
            user=self.user,
            plan_type="workout",
            date=timezone.localdate() - timedelta(days=1),
            payload={
                "level": "beginner",
                "workout": [{"exercise_id": 131, "guide_name": "Exercise 131"}],
            },
            completed_items=[0],
        )
        self.client.force_login(self.user)
        response = self.client.post(reverse("ai_workout"), {"level": "beginner"})
        self.assertEqual(response.status_code, 200)
        prompt = generate.call_args.args[0]
        self.assertNotIn('"id": 131', prompt)
        self.assertIn('"recent_workout_history"', prompt)
        self.assertIn('"completed": true', prompt)

    @patch(
        "core.views.generate_plan",
        return_value={
            "workout": [
                {"exercise_id": 999999, "sets": 3, "reps": "10", "rest_seconds": 60, "tip": "Stay controlled."},
                {"exercise_id": 131, "sets": 3, "reps": "10", "rest_seconds": 60, "tip": "Stay controlled."},
                {"exercise_id": 132, "sets": 3, "reps": "10", "rest_seconds": 60, "tip": "Stay controlled."},
            ],
        },
    )
    def test_workout_planner_rejects_exercises_outside_the_library(self, _generate):
        for exercise_id in (131, 132):
            Exercise.objects.create(
                external_id=exercise_id,
                name=f"Exercise {exercise_id}",
                image_url=f"https://wger.de/media/{exercise_id}.jpg",
            )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("ai_workout"),
            {"level": "beginner"},
        )
        self.assertIsNone(response.context["plan"])
        self.assertContains(response, "invalid exercise")
        self.assertNotContains(response, "999999")

    @patch(
        "core.views.generate_plan",
        return_value={
            "workout": [
                {"exercise_id": exercise_id, "sets": 4, "reps": "8-10", "rest_seconds": 90, "tip": "Move with control."}
                for exercise_id in (131, 132, 133)
            ],
        },
    )
    def test_advanced_workout_accepts_advanced_set_range(self, _generate):
        for exercise_id in (131, 132, 133):
            Exercise.objects.create(
                external_id=exercise_id,
                name=f"Exercise {exercise_id}",
                image_url=f"https://wger.de/media/{exercise_id}.jpg",
            )
        self.client.force_login(self.user)
        response = self.client.post(reverse("ai_workout"), {"level": "advanced"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["sets"] for item in response.context["plan"]["workout"]], [4, 4, 4])
        self.assertContains(response, 'value="advanced" required checked')

    def test_meal_planner_uses_catalog_values_and_saves_as_planned_entries(self):
        self.complete_profile()
        catalog_foods = [
            ("oats", "Oats", 380, 13, 68, 7),
            ("rice", "Cooked rice", 130, 3, 28, 0),
            ("paneer", "Paneer", 265, 18, 4, 20),
            ("chicken", "Chicken", 165, 31, 0, 4),
        ]
        for slug, name, calories, protein, carbs, fat in catalog_foods:
            Food.objects.create(
                slug=slug,
                name=name,
                calories_per_100g=calories,
                protein_per_100g=protein,
                carbs_per_100g=carbs,
                fat_per_100g=fat,
                is_vegetarian=slug != "chicken",
                serving_options=[{"label": "1 serving", "weight_g": 100}],
            )
        mock_plan = {
            "meals": [
                {"meal_type": "breakfast", "food_slug": "oats", "grams": 100, "reason": "A filling start."},
                {"meal_type": "lunch", "food_slug": "rice", "grams": 150, "reason": "A familiar staple."},
                {"meal_type": "dinner", "food_slug": "paneer", "grams": 120, "reason": "A protein-rich option."},
            ]
        }
        self.client.force_login(self.user)
        with patch("core.views.generate_plan", return_value=mock_plan) as generate:
            response = self.client.post(reverse("ai_meal_plan"), {"action": "generate"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Oats")
        self.assertNotContains(response, "Chicken")
        prompt = generate.call_args.args[0]
        self.assertIn('"diet_preference": "Vegetarian"', prompt)
        self.assertNotIn('"food_slug": "chicken"', prompt)

        response = self.client.post(
            reverse("ai_meal_plan"),
            {"action": "update", "index": "0", "food_slug": "rice", "grams": "150", "meal_type": "breakfast"},
        )
        self.assertRedirects(response, reverse("ai_meal_plan"), fetch_redirect_response=False)
        self.client.post(reverse("ai_meal_plan"), {"action": "save"})
        entries = MealEntry.objects.filter(user=self.user).order_by("meal_type")
        self.assertEqual(entries.count(), 3)
        breakfast = entries.get(meal_type="breakfast")
        self.assertFalse(breakfast.consumed)
        self.assertEqual(breakfast.food, Food.objects.get(slug="rice"))
        self.assertEqual(breakfast.weight_in_grams, 150)
        self.assertEqual(breakfast.calories, 195)
        saved_plan = SavedPlan.objects.get(user=self.user, plan_type="meal")
        original_payload = saved_plan.payload
        response = self.client.post(
            reverse("ai_meal_plan"),
            {"action": "update", "index": "0", "food_slug": "paneer", "grams": "100", "meal_type": "breakfast"},
        )
        self.assertContains(response, "already in your tracker")
        saved_plan.refresh_from_db()
        self.assertEqual(saved_plan.payload, original_payload)

        tracker = self.client.get(reverse("nutrition_log"))
        self.assertContains(tracker, "0.0</strong>")
        self.assertContains(tracker, "Planned meals")
        self.client.post(reverse("toggle_meal", args=[breakfast.pk]))
        tracker = self.client.get(reverse("nutrition_log"))
        self.assertContains(tracker, "195.0")
        saved_plan.refresh_from_db()
        self.assertEqual(saved_plan.completed_items, [0])
        history = self.client.get(reverse("progress"))
        self.assertEqual(history.context["saved_plans"][0].completed_count, 1)
        self.assertContains(history, "1/3 FOLLOWED")
        self.assertContains(history, "Eaten")
        self.client.post(reverse("delete_meal", args=[breakfast.pk]))
        tracker = self.client.get(reverse("nutrition_log"))
        self.assertContains(tracker, "0.0</strong>")
        saved_plan.refresh_from_db()
        self.assertEqual(saved_plan.completed_items, [])

    def test_meal_planner_uses_recent_history_and_avoids_mislabelled_meat(self):
        self.complete_profile()
        food_values = [
            ("old_oats", "Oats", "", True),
            ("old_rice", "Rice", "", True),
            ("old_paneer", "Paneer", "", True),
            ("new_oats", "Poha", "", True),
            ("new_rice", "Vegetable pulao", "", True),
            ("new_paneer", "Khichdi", "", True),
            ("chicken_curry", "Chicken Curry", "Indian Meals", True),
        ]
        foods = {}
        for slug, name, category, is_vegetarian in food_values:
            foods[slug] = Food.objects.create(
                slug=slug,
                name=name,
                category=category,
                calories_per_100g=100,
                protein_per_100g=5,
                carbs_per_100g=10,
                fat_per_100g=2,
                is_vegetarian=is_vegetarian,
            )
        yesterday = timezone.localdate() - timedelta(days=1)
        SavedPlan.objects.create(
            user=self.user,
            plan_type="meal",
            date=yesterday,
            payload={
                "meals": [
                    {"food_slug": "old_oats", "meal_type": "breakfast", "grams": "100", "reason": "Breakfast."},
                    {"food_slug": "old_rice", "meal_type": "lunch", "grams": "100", "reason": "Lunch."},
                    {"food_slug": "old_paneer", "meal_type": "dinner", "grams": "100", "reason": "Dinner."},
                ],
            },
            completed_items=[0],
        )
        MealEntry.objects.create(
            user=self.user,
            food=foods["old_oats"],
            date=yesterday,
            meal_type="breakfast",
            food_name="Oats",
            consumed=True,
        )
        plan = {
            "meals": [
                {"meal_type": "breakfast", "food_slug": "new_oats", "grams": 100, "reason": "A new start."},
                {"meal_type": "lunch", "food_slug": "new_rice", "grams": 150, "reason": "A balanced meal."},
                {"meal_type": "dinner", "food_slug": "new_paneer", "grams": 120, "reason": "A filling dish."},
            ]
        }
        self.client.force_login(self.user)
        with patch("core.views.generate_plan", return_value=plan) as generate:
            response = self.client.post(reverse("ai_meal_plan"), {"action": "generate"})
        self.assertEqual(response.status_code, 200)
        prompt = generate.call_args.args[0]
        self.assertIn('"recent_meal_history"', prompt)
        self.assertIn('"followed": true', prompt)
        self.assertIn('"foods_eaten_yesterday": ["Oats"]', prompt)
        self.assertNotIn('"food_slug": "old_oats"', prompt)
        self.assertNotIn('"food_slug": "old_rice"', prompt)
        self.assertNotIn('"food_slug": "chicken_curry"', prompt)
        self.assertEqual(
            [item["food_slug"] for item in response.context["saved_plan"].payload["meals"]],
            ["new_oats", "new_rice", "new_paneer"],
        )

    def test_meal_planner_rejects_raw_ingredients_and_side_dishes_as_main_meals(self):
        self.complete_profile()
        catalog = [
            ("tomato", "Tomato", "Vegetables"),
            ("idli_sambar", "Idli Sambar", "Indian Meals"),
            ("khichdi", "Vegetable Khichdi", "Indian Meals"),
            ("plain_dal", "Plain Cooked Dal", "Indian Meals"),
        ]
        for slug, name, category in catalog:
            Food.objects.create(
                slug=slug,
                name=name,
                category=category,
                calories_per_100g=100,
                protein_per_100g=5,
                carbs_per_100g=10,
                fat_per_100g=2,
                is_vegetarian=True,
            )
        self.client.force_login(self.user)
        for invalid_main in ("tomato", "plain_dal"):
            with self.subTest(food=invalid_main), patch(
                "core.views.generate_plan",
                return_value={
                    "meals": [
                        {"meal_type": "breakfast", "food_slug": "idli_sambar", "grams": 100, "reason": "Breakfast."},
                        {"meal_type": "lunch", "food_slug": invalid_main, "grams": 150, "reason": "Lunch."},
                        {"meal_type": "dinner", "food_slug": "khichdi", "grams": 120, "reason": "Dinner."},
                    ]
                },
            ):
                response = self.client.post(reverse("ai_meal_plan"), {"action": "generate"})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(
                response.context["plan"] is not None
                or SavedPlan.objects.filter(user=self.user, plan_type="meal").exists()
            )
        self.assertEqual(SavedPlan.objects.filter(user=self.user, plan_type="meal").count(), 1)

    def test_eggitarian_meal_planner_allows_eggs_but_rejects_meat_edits(self):
        self.complete_profile(dietary_preference="eggetarian")
        Food.objects.create(
            slug="whole_egg",
            name="Whole Egg",
            calories_per_100g=155,
            protein_per_100g=13,
            carbs_per_100g=1,
            fat_per_100g=11,
            is_vegetarian=False,
        )
        Food.objects.create(
            slug="tomato",
            name="Tomato",
            calories_per_100g=18,
            protein_per_100g=1,
            carbs_per_100g=4,
            fat_per_100g=0,
            is_vegetarian=True,
        )
        Food.objects.create(
            slug="chicken",
            name="Chicken",
            calories_per_100g=165,
            protein_per_100g=31,
            carbs_per_100g=0,
            fat_per_100g=4,
            is_vegetarian=False,
        )
        plan = {
            "meals": [
                {"meal_type": "breakfast", "food_slug": "whole_egg", "grams": 100, "reason": "Eggs."},
                {"meal_type": "lunch", "food_slug": "tomato", "grams": 150, "reason": "Vegetables."},
                {"meal_type": "dinner", "food_slug": "whole_egg", "grams": 100, "reason": "Eggs."},
            ]
        }
        self.client.force_login(self.user)
        with patch("core.views.generate_plan", return_value=plan) as generate:
            response = self.client.post(reverse("ai_meal_plan"), {"action": "generate"})
        self.assertEqual(response.status_code, 200)
        prompt = generate.call_args.args[0]
        self.assertIn('"food_slug": "whole_egg"', prompt)
        self.assertNotIn('"food_slug": "chicken"', prompt)
        response = self.client.post(
            reverse("ai_meal_plan"),
            {"action": "update", "index": "0", "food_slug": "chicken", "grams": "100", "meal_type": "breakfast"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "matches your diet preference")
        self.assertFalse(MealEntry.objects.filter(user=self.user).exists())

    @override_settings(GEMINI_API_KEY="")
    def test_gemini_planner_reports_missing_key_without_exposing_credentials(self):
        with self.assertRaisesMessage(PlanningError, "restart the Django server"):
            generate_plan("{}")

    @override_settings(GEMINI_API_KEY="test-api-key")
    def test_gemini_key_is_sent_in_server_request_header_not_url(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"candidates":[{"content":{"parts":[{"text":"{\\"ok\\":true}"}]}}]}'
        with patch("core.ai_planning.urlopen", return_value=response) as urlopen:
            self.assertEqual(generate_plan("{}"), {"ok": True})
        request = urlopen.call_args.args[0]
        self.assertNotIn("test-api-key", request.full_url)
        self.assertEqual(request.headers["X-goog-api-key"], "test-api-key")

    @override_settings(GEMINI_API_KEY="test-api-key")
    def test_gemini_rate_limit_returns_a_retryable_message(self):
        provider_error = HTTPError(
            "https://generativelanguage.googleapis.com/",
            429,
            "Too many requests",
            {},
            None,
        )
        with patch("core.ai_planning.urlopen", side_effect=provider_error):
            with self.assertRaisesMessage(PlanningError, "usage limit"):
                generate_plan("{}")

    def test_progress_shows_weight_stats_and_consumed_nutrition_only(self):
        today = timezone.localdate()
        self.profile.age = 30
        self.profile.calculation_sex = "female"
        self.profile.goal = "weight_loss"
        self.profile.activity_level = "moderate"
        self.profile.target_weight_kg = 70
        self.profile.dietary_preference = "vegetarian"
        self.profile.save()

        first_date = today - timedelta(days=40)
        latest_date = today - timedelta(days=1)
        ProgressRecord.objects.create(
            user=self.user,
            date=first_date,
            weight_kg=80,
            steps=7000,
            activity_minutes=30,
        )
        ProgressRecord.objects.create(
            user=self.user,
            date=latest_date,
            weight_kg=78,
            steps=8200,
            activity_minutes=40,
        )
        MealEntry.objects.create(
            user=self.user,
            date=latest_date,
            meal_type="lunch",
            food_name="Consumed meal",
            calories=850,
            protein_g=45,
            consumed=True,
        )
        MealEntry.objects.create(
            user=self.user,
            date=latest_date,
            meal_type="dinner",
            food_name="Planned meal",
            calories=5000,
            protein_g=500,
            consumed=False,
        )
        other_user = User.objects.create_user(username="other", password="a-safe-test-password")
        ProgressRecord.objects.create(
            user=other_user,
            date=latest_date,
            weight_kg=120,
            notes="Private weigh-in",
        )
        MealEntry.objects.create(
            user=other_user,
            date=latest_date,
            meal_type="dinner",
            food_name="Private meal",
            calories=9999,
            protein_g=999,
            consumed=True,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("progress"), {"period": "3m"})
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context["calorie_chart"])
        self.assertIsNotNone(response.context["protein_chart"])
        self.assertEqual(response.context["weight_change"], -2)
        self.assertEqual(response.context["goal_progress"], 20)
        self.assertEqual(response.context["average_calories"], 850)
        self.assertEqual(response.context["average_protein"], 45)
        self.assertContains(response, "Weekly averages")
        self.assertContains(response, "850.0 kcal")
        self.assertEqual(response.content.decode().count('<svg class="line-chart"'), 2)
        self.assertContains(
            response,
            '<polyline class="chart-line chart-line-target"',
            html=False,
        )
        self.assertContains(
            response,
            '<circle class="chart-point chart-point-actual"',
            html=False,
        )
        self.assertNotContains(response, "Workout history")
        self.assertContains(response, "Record progress and activity")
        self.assertNotContains(response, "Target and actual weight")
        self.assertNotContains(response, "Recorded Movement")
        self.assertNotContains(response, "Private weigh-in")
        self.assertNotContains(response, "Private meal")

    def test_progress_shows_all_saved_ai_plans_in_history(self):
        for day in range(10):
            SavedPlan.objects.create(
                user=self.user,
                plan_type="workout",
                date=timezone.localdate() - timedelta(days=day),
                payload={"level": "beginner", "workout": []},
            )
        self.client.force_login(self.user)
        response = self.client.get(reverse("progress"))
        self.assertEqual(len(response.context["saved_plans"]), 8)
        self.assertEqual(response.context["plan_history_page"].paginator.count, 10)
        self.assertContains(response, "Saved plan history")
        self.assertContains(response, "Page 1 of 2")
        second_page = self.client.get(reverse("progress"), {"plans_page": 2})
        self.assertEqual(len(second_page.context["saved_plans"]), 2)

    def test_progress_accepts_each_requested_date_range(self):
        self.client.force_login(self.user)
        for period in ("7d", "30d", "3m", "6m", "1y"):
            with self.subTest(period=period):
                response = self.client.get(reverse("progress"), {"period": period})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["period"], period)
        defaulted = self.client.get(reverse("progress"), {"period": "invalid"})
        self.assertEqual(defaulted.context["period"], "30d")

    def test_progress_without_records_shows_empty_charts_instead_of_fake_values(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("progress"), {"period": "7d"})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["calorie_chart"])
        self.assertIsNone(response.context["protein_chart"])
        self.assertNotContains(response, "Target and actual weight")
        self.assertNotContains(response, "Recorded Movement")
        self.assertContains(response, "No consumed food entries are recorded")

    @patch("core.views.get_exercises", return_value=[])
    def test_authenticated_pages_render(self, _get_exercises):
        self.client.force_login(self.user)
        paths = (
            "dashboard",
            "onboarding",
            "exercises",
            "ai_workout",
            "nutrition",
            "nutrition_log",
            "ai_meal_plan",
            "foods",
            "progress",
            "profile",
            "password_change",
            "password_reset",
        )
        for name in paths:
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/workouts/").status_code, 404)
        self.assertEqual(self.client.get("/workout/").status_code, 404)
        dashboard = self.client.get(reverse("dashboard")).content.decode()
        nav = dashboard.split('<nav class="main-nav"', 1)[1].split("</nav>", 1)[0]
        self.assertEqual(nav.count("<a "), 4)
        self.assertNotIn(">Workouts<", nav)
