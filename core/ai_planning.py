import json
import time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from django.conf import settings


class PlanningError(Exception):
    pass


_REQUEST_TIMEOUT_SECONDS = 25
_MAX_ATTEMPTS = 2


def _service_error_message(error, feature_name):
    if error.code == 429:
        return (
            f"Gemini's current request or usage limit was reached for {feature_name}. "
            "Please wait a moment and try again."
        )
    if error.code in (401, 403):
        return f"{feature_name} could not authenticate with Gemini. Check the API key configuration."
    if error.code == 400:
        return (
            f"Gemini could not process this {feature_name} request. "
            "Please try a shorter question or check the configured model."
        )
    if error.code >= 500:
        return f"Gemini is temporarily unavailable for {feature_name}. Please try again shortly."
    return f"Gemini rejected the {feature_name} request (HTTP {error.code}). Please try again."


def _request_json(url, api_key, payload, feature_name):
    request_body = json.dumps(payload).encode("utf-8")
    for attempt in range(_MAX_ATTEMPTS):
        request = Request(
            url,
            data=request_body,
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
            method="POST",
        )
        try:
            with urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
                response_text = response.read().decode("utf-8")
            return json.loads(response_text)
        except HTTPError as error:
            if error.code >= 500 and attempt + 1 < _MAX_ATTEMPTS:
                time.sleep(2 ** attempt)
                continue
            raise PlanningError(_service_error_message(error, feature_name)) from error
        except (OSError, TimeoutError) as error:
            if attempt + 1 < _MAX_ATTEMPTS:
                time.sleep(2 ** attempt)
                continue
            raise PlanningError(
                "Could not connect to Gemini. Check your internet connection and try again."
            ) from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PlanningError(
                f"Gemini returned an unreadable response for {feature_name}. Please try again."
            ) from error


def _response_text(result, feature_name):
    if not isinstance(result, dict):
        raise PlanningError(f"Gemini returned an unexpected response for {feature_name}. Please try again.")

    prompt_feedback = result.get("promptFeedback") or {}
    block_reason = prompt_feedback.get("blockReason") if isinstance(prompt_feedback, dict) else None
    if block_reason:
        raise PlanningError(
            f"Gemini could not answer that {feature_name} request. Please rephrase it and try again."
        )

    candidates = result.get("candidates")
    candidate = candidates[0] if isinstance(candidates, list) and candidates else None
    if not isinstance(candidate, dict):
        raise PlanningError(f"Gemini returned no reply for {feature_name}. Please try again.")

    finish_reason = candidate.get("finishReason")
    if finish_reason == "SAFETY":
        raise PlanningError(
            f"Gemini could not answer that {feature_name} request. Please rephrase it and try again."
        )
    if finish_reason == "MAX_TOKENS":
        raise PlanningError(f"Gemini's reply for {feature_name} was cut short. Please try a shorter request.")

    content = candidate.get("content") or {}
    parts = content.get("parts") if isinstance(content, dict) else None
    text_parts = [
        part["text"]
        for part in parts or []
        if isinstance(part, dict)
        and isinstance(part.get("text"), str)
        and part["text"].strip()
        and not part.get("thought")
    ]
    if not text_parts:
        raise PlanningError(f"Gemini returned an empty reply for {feature_name}. Please try again.")

    generated_text = "".join(text_parts).strip()
    if generated_text.startswith("```"):
        lines = generated_text.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            generated_text = "\n".join(lines[1:-1]).strip()
    return generated_text


def generate_plan(prompt, feature_name="AI planner"):
    """Ask Gemini for a JSON object used by a planner or the chat assistant."""
    api_key = getattr(settings, "GEMINI_API_KEY", "").strip()
    if not api_key:
        raise PlanningError(
            "GEMINI_API_KEY was not loaded. Confirm it is set in the project-root .env file, "
            "then restart the Django server and try again."
        )
    model = quote(getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash"), safe="")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.3,
            "maxOutputTokens": 2048,
        },
    }
    result = _request_json(url, api_key, payload, feature_name)
    generated_text = _response_text(result, feature_name)
    try:
        parsed = json.loads(generated_text)
    except json.JSONDecodeError as error:
        raise PlanningError(
            f"Gemini returned a reply in an unexpected format for {feature_name}. Please try again."
        ) from error
    if not isinstance(parsed, dict):
        raise PlanningError(f"Gemini returned an unexpected response for {feature_name}. Please try again.")
    return parsed
