# AI Fitness & Diet Planner

A server-rendered fitness and nutrition planner built with Django. It combines a private fitness profile, daily estimates, an exercise library, AI-assisted workout and meal suggestions, a local Indian food catalog, a planned-versus-consumed meal tracker, and progress history.

## Features

- Email-and-password registration and sign-in; profile setup follows account creation.
- Daily calorie and macro estimates, activity-based step target, water estimate, BMI indicator, and manual daily check-ins.
- Exercise library with search, filters, demonstrations, instructions, and an AI session planner that links to existing exercise guides.
- Bundled multilingual food catalog with portion calculations, food details, and AI meal suggestions restricted to local catalog foods.
- Generated meal and workout plans are saved in full plan history; workout steps can be checked off, and AI meal entries are marked followed as they are eaten in the food tracker.
- Daily AI suggestions receive recent plan and consumption history to reduce repeats. Meal planning restricts main meals to prepared catalog dishes, applies diet-preference checks, and avoids combining unrelated foods.
- Manual food logging and separate planned and consumed entries; planned food is excluded from intake totals until marked consumed.
- Private daily progress records for weight, steps, active minutes, water, and notes, with editing and nutrition charts.
- Password reset/change flows using Django authentication.
- A reference-inspired dashboard and food-catalog layout with a persistent light/dark theme switch.

## Local setup

Python 3.12 or newer is required.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

If `.env` already exists, keep it and add only any missing settings; do not overwrite existing local credentials. Set `DJANGO_SECRET_KEY` to a local random value and keep `.env` private. Development defaults to SQLite.

Apply the project migrations and start Django:

```powershell
python manage.py migrate
python manage.py check
python manage.py runserver
```

Open http://127.0.0.1:8000. Existing databases should be upgraded with `migrate`; do not reset or flush a database to install this version.
The theme switch saves its preference in the current browser, so light or dark mode follows the user between pages.

The local food dataset is bundled at `static\data\fitforge_indian_foods.json`, with images under `static\files\`. If the food library is empty, import or refresh its catalog using:

```powershell
python manage.py import_foods
```

The import command is idempotent and updates matching catalog entries.

## Gemini Developer API

AI workout and meal planning use the Gemini Developer API from Django on the server. Create an API key in [Google AI Studio](https://aistudio.google.com/apikey), then set it only in the local `.env`:

```text
GEMINI_API_KEY=your-local-key
```

The default model is `gemini-3.5-flash-lite`, which is currently listed with free-tier input/output on Google's pricing page. Change it with `GEMINI_MODEL` if you have access to another supported model:

```text
GEMINI_MODEL=gemini-3.5-flash-lite
```

Model availability, free-tier eligibility, and request quotas can change. Google may apply usage limits, and free-tier data-use terms may allow submitted content to be used to improve Google products. Do not send sensitive information in prompts. Review the current [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing), [models](https://ai.google.dev/gemini-api/docs/models), and [terms](https://ai.google.dev/gemini-api/terms) before enabling the feature. A free tier is neither unlimited nor guaranteed. Missing keys, quota limits, provider errors, and invalid AI responses are handled in the planner interface.

The API key is read from the Django environment and sent only in a server-to-server request; it is not included in rendered HTML or browser JavaScript. Never commit `.env` or paste an API key into an issue or chat.

Django reads `.env` when the server starts. Restart `python manage.py runserver` after adding or changing `GEMINI_API_KEY`; the planner reports when the running process has not loaded the key. The workout planner asks only for beginner or advanced experience, and validates every suggested exercise against locally stored guides that are visible in the exercise library.

## Estimates and privacy

Calorie and macro targets use Mifflin–St Jeor estimates for adults with a complete profile. The water target is a rough 35 ml-per-kg estimate; step and active-minute values are suggested goals. BMI is a screening indicator. None are medical advice or measured calorie burn. Food catalog values are labeled estimates and may be provisional or recipe-dependent.

Progress and meal records are filtered by the authenticated user. Manual step, active-minute, and water values are not automatically measured. Planned meals remain separate from consumed totals until explicitly marked consumed.

For production, set `DJANGO_DEBUG=0`, configure a strong `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, a production database and email backend, and serve behind HTTPS.
