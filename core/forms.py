from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.contrib.auth.forms import AuthenticationForm
from .models import Profile, ProgressRecord


class RegistrationForm(UserCreationForm):
    first_name = forms.CharField(label="Name", max_length=150)
    password1 = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="",
    )
    password2 = forms.CharField(
        label="Confirm password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="",
    )
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ("first_name", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].help_text = ""

    def save(self, commit=True):
        user = super().save(commit=False)
        user.first_name = self.cleaned_data["first_name"].strip()
        user.username = self.cleaned_data["email"].strip().casefold()
        user.email = self.cleaned_data["email"].strip()
        if commit:
            user.save()
        return user

    def clean_email(self):
        email = self.cleaned_data["email"]
        email = email.strip()
        if len(email) > 150:
            raise forms.ValidationError("Use an email address with at most 150 characters.")
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean_password2(self):
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("The passwords do not match.")
        return password2

class EmailLoginForm(AuthenticationForm):
    username = forms.EmailField(label="Email address", widget=forms.EmailInput(attrs={"autocomplete": "email"}))

    def clean_username(self):
        return self.cleaned_data["username"].strip().casefold()


class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = (
            "goal", "age", "calculation_sex", "height_cm", "current_weight_kg",
            "target_weight_kg", "activity_level", "dietary_preference",
        )
        labels = {
            "calculation_sex": "Gender formula coefficient",
            "height_cm": "Height (cm)",
            "current_weight_kg": "Current weight (kg)",
            "target_weight_kg": "Target weight (kg)",
        }
        help_texts = {
            "calculation_sex": "Used only for the standard energy estimate; choose the formula coefficient you want applied.",
            "age": "Energy estimates are provided only for adults.",
        }
        widgets = {
            "age": forms.NumberInput(attrs={"min": "13", "max": "120"}),
            "height_cm": forms.NumberInput(attrs={"step": "0.1", "min": "1"}),
            "current_weight_kg": forms.NumberInput(attrs={"step": "0.1", "min": "1"}),
            "target_weight_kg": forms.NumberInput(attrs={"step": "0.1", "min": "1"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = True


class ProgressRecordForm(forms.ModelForm):
    class Meta:
        model = ProgressRecord
        fields = ("date", "weight_kg", "waist_cm", "steps", "activity_minutes", "water_ml", "notes")
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "weight_kg": forms.NumberInput(attrs={"step": "0.1", "min": "1"}),
            "waist_cm": forms.NumberInput(attrs={"step": "0.1", "min": "1"}),
            "steps": forms.NumberInput(attrs={"min": "0", "max": "200000", "step": "1"}),
            "activity_minutes": forms.NumberInput(attrs={"min": "0", "max": "1440", "step": "1"}),
            "water_ml": forms.NumberInput(attrs={"min": "0", "max": "10000", "step": "100"}),
        }
        help_texts = {
            "weight_kg": "Optional. Use this for an actual weigh-in.",
            "steps": "Optional. Enter a manual step count; leave blank if you did not track it.",
            "activity_minutes": "Optional. Enter activity minutes you actually completed.",
        }
