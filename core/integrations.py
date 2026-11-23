import json
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.cache import cache

from .models import Exercise


class ExerciseAPIError(Exception):
    pass


class _DescriptionParser(HTMLParser):
    _BLOCK_TAGS = {"p", "div", "br", "li", "h1", "h2", "h3"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden_depth += 1
        elif not self.hidden_depth and tag in self._BLOCK_TAGS:
            self.parts.append("\n• " if tag == "li" else "\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden_depth:
            self.hidden_depth -= 1
        elif not self.hidden_depth and tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden_depth:
            self.parts.append(data)


def _plain_description(markup):
    parser = _DescriptionParser()
    parser.feed(markup or "")
    lines = (" ".join(part.split()) for part in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)


def _media_url(value):
    if not isinstance(value, str):
        return ""
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not (parsed.hostname == "wger.de" or parsed.hostname.endswith(".wger.de"))
    ):
        return ""
    return value


def _license_url(value):
    if not isinstance(value, str):
        return ""
    parsed = urlparse(value)
    if parsed.scheme == "https":
        return value
    if parsed.scheme == "http" and parsed.hostname == "creativecommons.org":
        return value.replace("http://", "https://", 1)
    return ""


def _wger_headers():
    headers = {"User-Agent": "AI-Fitness-Diet-Planner/1.0", "Accept": "application/json"}
    api_key = settings.WGER_API_KEY.strip()
    if api_key:
        headers["Authorization"] = f"Token {api_key}"
    return headers


def _wger_get(url, error_type, unavailable_message):
    request = Request(url, headers=_wger_headers())
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise error_type(unavailable_message) from error


def _english_translation(item):
    translations = item.get("translations") or []
    for translation in translations:
        if not isinstance(translation, dict):
            continue
        language = translation.get("language")
        if isinstance(language, dict):
            language = language.get("id")
        if str(language) == "2" and translation.get("name"):
            return translation
    return None


def _normalise_exercise(item):
    translation = _english_translation(item)
    if translation is None:
        return None

    images = item.get("images") or []
    main_image = next(
        (image for image in images if isinstance(image, dict) and image.get("is_main")),
        next((image for image in images if isinstance(image, dict)), {}),
    )
    videos = item.get("videos") or []
    usable_videos = [
        video for video in videos
        if isinstance(video, dict) and _media_url(video.get("video"))
    ]
    main_video = next(
        (
            video for video in usable_videos
            if str(video.get("codec") or "").casefold() == "h264"
            and video.get("video", "").casefold().endswith(".mp4")
        ),
        next(
            (video for video in usable_videos if video.get("is_main")),
            usable_videos[0] if usable_videos else {},
        ),
    )
    category = item.get("category") or {}
    license_data = item.get("license") or {}
    if not isinstance(category, dict):
        category = {}
    if not isinstance(license_data, dict):
        license_data = {}

    video_url = _media_url(main_video.get("video"))
    codec = str(main_video.get("codec") or "")
    image_url = _media_url(main_image.get("image"))
    return {
        "id": item.get("id"),
        "name": str(translation["name"]).strip(),
        "description": _plain_description(translation.get("description", "")),
        "category": str(category.get("name") or ""),
        "equipment": _names(item.get("equipment") or []),
        "muscles": _names(item.get("muscles") or []) or _names(item.get("muscles_secondary") or []),
        "image_url": image_url,
        "video_url": video_url,
        "video_codec": codec,
        "video_embeddable": bool(
            video_url and codec.casefold() == "h264" and video_url.casefold().endswith(".mp4")
        ),
        "license_name": str(license_data.get("short_name") or ""),
        "license_url": _license_url(license_data.get("url")),
    }


def _names(values):
    return ", ".join(
        str(value.get("name", value.get("translation", "")))
        for value in values
        if isinstance(value, dict) and value.get("name", value.get("translation"))
    )


def get_exercises(search=""):
    results = cache.get("wger_exercises_english_media_v2")
    if results is None:
        url = "https://wger.de/api/v2/exerciseinfo/?" + urlencode({"language": 2, "limit": 999})
        payload = _wger_get(
            url,
            ExerciseAPIError,
            "The exercise library is temporarily unavailable. Please try again later.",
        )
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            raise ExerciseAPIError("The exercise provider returned an unexpected response.")

        normalized = []
        for item in results:
            if not isinstance(item, dict):
                continue
            exercise = _normalise_exercise(item)
            if exercise is None:
                continue
            normalized.append(exercise)
            if exercise["id"] is not None:
                Exercise.objects.update_or_create(
                    external_id=exercise["id"],
                    defaults={
                        "name": exercise["name"],
                        "description": exercise["description"],
                        "category": exercise["category"],
                        "equipment": exercise["equipment"],
                        "muscles": exercise["muscles"],
                        "image_url": exercise["image_url"],
                        "video_url": exercise["video_url"],
                        "video_codec": exercise["video_codec"],
                        "video_embeddable": exercise["video_embeddable"],
                        "license_name": exercise["license_name"],
                        "license_url": exercise["license_url"],
                    },
                )
        results = normalized
        cache.set("wger_exercises_english_media_v2", results, 60 * 30)

    term = search.strip().casefold()
    if term:
        results = [
            item
            for item in results
            if term in item["name"].casefold()
            or term in item["category"].casefold()
            or term in item["equipment"].casefold()
            or term in item["muscles"].casefold()
            or term in item["description"].casefold()
        ]
    return results
