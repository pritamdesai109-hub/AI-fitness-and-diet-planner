from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .forms import EmailLoginForm


urlpatterns = [
    path("", views.home, name="home"),
    path("register/", views.register, name="register"),
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html", authentication_form=EmailLoginForm), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="registration/password_reset_form.html",
            email_template_name="registration/password_reset_email.txt",
            subject_template_name="registration/password_reset_subject.txt",
        ),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(template_name="registration/password_reset_done.html"),
        name="password_reset_done",
    ),
    path(
        "password-reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(template_name="registration/password_reset_confirm.html"),
        name="password_reset_confirm",
    ),
    path(
        "password-reset/complete/",
        auth_views.PasswordResetCompleteView.as_view(template_name="registration/password_reset_complete.html"),
        name="password_reset_complete",
    ),
    path(
        "password-change/",
        auth_views.PasswordChangeView.as_view(
            template_name="registration/password_change_form.html",
            success_url="/password-change/done/",
        ),
        name="password_change",
    ),
    path(
        "password-change/done/",
        auth_views.PasswordChangeDoneView.as_view(template_name="registration/password_change_done.html"),
        name="password_change_done",
    ),
    path("onboarding/", views.onboarding, name="onboarding"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("ai-assistant/", views.ai_chat, name="ai_chat"),
    path("exercises/", views.exercise_library, name="exercises"),
    path("exercises/ai-planner/", views.ai_workout, name="ai_workout"),
    path("plans/<int:plan_id>/items/<int:item_index>/toggle/", views.toggle_saved_plan_item, name="toggle_saved_plan_item"),
    path("exercises/<int:exercise_id>/", views.exercise_detail, name="exercise_detail"),
    path("nutrition/", views.food_library, name="nutrition"),
    path("nutrition/ai-planner/", views.ai_meal_plan, name="ai_meal_plan"),
    path("nutrition/tracker/", views.nutrition_log, name="nutrition_log"),
    path("nutrition/foods/", views.food_library, name="foods"),
    path("nutrition/foods/<slug:food_slug>/", views.food_detail, name="food_detail"),
    path("nutrition/foods/<slug:food_slug>/add/", views.add_food_to_log, name="add_food_to_log"),
    path("nutrition/entries/<int:entry_id>/toggle/", views.toggle_meal, name="toggle_meal"),
    path("nutrition/entries/<int:entry_id>/delete/", views.delete_meal, name="delete_meal"),
    path("progress/", views.progress, name="progress"),
    path("profile/", views.profile, name="profile"),
]
