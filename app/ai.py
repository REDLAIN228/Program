from __future__ import annotations

import base64
from dataclasses import dataclass
import io
import os
from typing import Protocol
from urllib.parse import urlsplit

import httpx
from PIL import Image

from app.imaging import flatten


class ImageProvider(Protocol):
    def generate(self, prompt: str, reference: Image.Image | None = None) -> Image.Image: ...


@dataclass
class ProviderSettings:
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-image-1"


def read_key() -> str:
    value = os.environ.get("ANIME_DRAWER_API_KEY")
    if value:
        return value
    import keyring
    try:
        return keyring.get_password("AnimeDrawer", "image-provider") or ""
    except keyring.errors.KeyringError:
        return ""


def save_key(value: str):
    import keyring
    if value:
        keyring.set_password("AnimeDrawer", "image-provider", value)
    else:
        try:
            keyring.delete_password("AnimeDrawer", "image-provider")
        except keyring.errors.PasswordDeleteError:
            pass


class OpenAIImageProvider:
    """Images API: text generation or real multipart reference edit. No local AI claim."""

    def __init__(self, settings: ProviderSettings, key: str, transport=None):
        parsed = urlsplit(settings.base_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("AI API должен использовать HTTPS без ключа в URL")
        if parsed.query or parsed.fragment:
            raise ValueError("Базовый URL API не должен содержать query или fragment")
        if not key.strip():
            raise ValueError("Задайте API-ключ в настройках или ANIME_DRAWER_API_KEY")
        self.settings, self.key, self.transport = settings, key, transport

    def generate(self, prompt: str, reference: Image.Image | None = None) -> Image.Image:
        if not prompt.strip():
            raise ValueError("Введите описание изображения")
        data = {"model": self.settings.model, "prompt": prompt, "size": "1024x1024", "n": 1}
        root = self.settings.base_url.rstrip("/")
        try:
            with httpx.Client(timeout=httpx.Timeout(180, connect=15), transport=self.transport,
                              follow_redirects=False) as client:
                if reference is None:
                    response = client.post(root + "/images/generations", json=data,
                                           headers={"Authorization": f"Bearer {self.key}"})
                else:
                    file = io.BytesIO()
                    flatten(reference).resize((1024, 1024)).save(file, "PNG")
                    payload = {k: str(v) for k, v in data.items()}
                    response = client.post(root + "/images/edits", data=payload,
                                           files={"image": ("reference.png", file.getvalue(), "image/png")},
                                           headers={"Authorization": f"Bearer {self.key}"})
                if response.status_code >= 300:
                    # Do not log provider bodies: they may echo credentials or private input.
                    raise RuntimeError(f"AI API: HTTP {response.status_code}. Проверьте модель, доступ и баланс. "
                                       "Для Character провайдер должен поддерживать /images/edits.")
                body = response.json()
                item = body["data"][0]
                if item.get("b64_json"):
                    raw = base64.b64decode(item["b64_json"], validate=True)
                elif item.get("url"):
                    url = urlsplit(item["url"])
                    if url.scheme != "https" or not url.hostname or url.username or url.password:
                        raise ValueError("API вернул небезопасный URL изображения")
                    # Deliberately no Authorization header on storage/CDN requests.
                    with client.stream("GET", item["url"]) as result:
                        result.raise_for_status()
                        parts, count = [], 0
                        for part in result.iter_bytes():
                            count += len(part)
                            if count > 32_000_000:
                                raise ValueError("Ответ AI превышает 32 МБ")
                            parts.append(part)
                        raw = b"".join(parts)
                else:
                    raise ValueError("AI API не вернул изображение")
        except httpx.HTTPError as exc:
            raise RuntimeError("Сбой соединения с AI API. Проверьте сеть и адрес провайдера.") from exc
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("Несовместимый формат ответа Images API") from exc
        if len(raw) > 32_000_000:
            raise ValueError("Изображение AI превышает 32 МБ")
        with Image.open(io.BytesIO(raw)) as image:
            if image.width * image.height > 40_000_000:
                raise ValueError("Изображение AI слишком велико")
            return flatten(image)
