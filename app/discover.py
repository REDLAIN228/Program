"""Official Wikimedia Commons search with attribution and bounded caching."""
from dataclasses import asdict, dataclass
from html import unescape
from html.parser import HTMLParser
import hashlib
import io
import json
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit

import httpx
from PIL import Image

from app.storage import write_json

API = "https://commons.wikimedia.org/w/api.php"
TOPICS = ("Anime character", "Roblox avatar", "Pixel art", "Minimalist art", "Portrait painting",
          "Fantasy illustration", "Dark landscape", "Cute animal drawing")


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
    def handle_data(self, data):
        self.parts.append(data)


def plain(value):
    parser = _PlainText()
    parser.feed(str(value or ""))
    return unescape(" ".join(parser.parts)).strip()[:1600]


@dataclass
class DiscoveryImage:
    page_id: int
    title: str
    thumbnail: str
    original: str
    page: str
    author: str
    license: str
    license_url: str
    width: int
    height: int
    source: str = "Wikimedia Commons"


def _url(url, hosts):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in hosts or parsed.username or parsed.password:
        raise ValueError("Источник вернул неподдерживаемый адрес изображения")
    return url


class CommonsClient:
    _request_lock = threading.Lock()
    _last_request = 0.

    def __init__(self, root, transport=None):
        self.root = Path(root)/"discover"
        self.root.mkdir(parents=True, exist_ok=True)
        self.transport = transport

    def _client(self):
        return httpx.Client(timeout=httpx.Timeout(25, connect=10), follow_redirects=False,
                            transport=self.transport,
                            headers={"User-Agent": "REDLAIN-DRAW-ENGINE/3.0 (desktop Commons art browser)",
                                     "Accept": "application/json,image/*"})

    def search(self, query, offset=0, cancel=None):
        query = query.strip()[:180]
        if not query:
            return [], False
        if not isinstance(offset, int) or not 0 <= offset <= 120:
            raise ValueError("Некорректная страница поиска")
        digest = hashlib.sha256(f"{query}\0{offset}".encode()).hexdigest()
        cache = self.root/(digest+".json")
        if cache.exists() and time.time()-cache.stat().st_mtime < 12*3600:
            return [DiscoveryImage(**row) for row in json.loads(cache.read_text("utf-8"))["results"]], True
        params = dict(action="query", format="json", generator="search", gsrsearch=query+" filetype:bitmap",
                      gsrnamespace=6, gsrlimit=12, gsroffset=offset, prop="imageinfo|info", inprop="url",
                      iiprop="url|size|mime|extmetadata", iiurlwidth=300, maxlag=5)
        try:
            with self._request_lock:
                remaining = max(0, 1.-(time.monotonic()-self._last_request))
                if remaining:
                    if cancel is not None and cancel.wait(remaining):
                        raise InterruptedError("Поиск отменён")
                    elif cancel is None:
                        time.sleep(remaining)
                if cancel is not None and cancel.is_set():
                    raise InterruptedError("Поиск отменён")
                type(self)._last_request = time.monotonic()
                with self._client() as client:
                    response = client.get(API, params=params)
                    response.raise_for_status()
                    body = response.json()
            if body.get("error"):
                raise RuntimeError("Wikimedia временно ограничила запросы. Повторите поиск позже.")
            rows = []
            for page in body.get("query", {}).get("pages", {}).values():
                info = page.get("imageinfo", [{}])[0]
                if info.get("mime") not in ("image/jpeg", "image/png", "image/webp"):
                    continue
                metadata = info.get("extmetadata", {})
                value = lambda key: plain(metadata.get(key, {}).get("value", ""))
                try:
                    original = _url(info["url"], {"upload.wikimedia.org"})
                    thumbnail = _url(info.get("thumburl", original), {"upload.wikimedia.org"})
                    source = _url(page.get("fullurl", info.get("descriptionurl", "")), {"commons.wikimedia.org"})
                except (ValueError, KeyError):
                    continue
                rows.append(DiscoveryImage(int(page["pageid"]), plain(page["title"]).removeprefix("File:"),
                            thumbnail, original, source, value("Artist") or "Автор не указан",
                            value("LicenseShortName") or "Проверьте условия на странице источника",
                            value("LicenseUrl"), int(info.get("width", 0)), int(info.get("height", 0))))
            write_json(cache, dict(query=query, results=[asdict(row) for row in rows]))
            return rows, False
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            if cache.exists():
                return [DiscoveryImage(**row) for row in json.loads(cache.read_text("utf-8"))["results"]], True
            raise RuntimeError("Нет доступа к Wikimedia Commons. Проверьте интернет; избранное и кеш остаются доступны.") from exc

    def download(self, item, thumbnail=False, cancel=None):
        url = _url(item.thumbnail if thumbnail else item.original, {"upload.wikimedia.org"})
        digest = hashlib.sha256(url.encode()).hexdigest()
        path = self.root/(digest+".png")
        if path.exists():
            with Image.open(path) as image:
                return image.convert("RGB").copy(), path
        if thumbnail:
            original_digest = hashlib.sha256(item.original.encode()).hexdigest()
            original_cache = self.root/(original_digest+".png")
            if original_cache.exists():
                with Image.open(original_cache) as source:
                    image = source.convert("RGB").copy()
                    image.thumbnail((300, 300))
                    return image, original_cache
        limit = 4_000_000 if thumbnail else 32_000_000
        try:
            with self._client() as client, client.stream("GET", url) as response:
                response.raise_for_status()
                if int(response.headers.get("content-length", 0)) > limit:
                    raise ValueError("Изображение слишком велико для загрузки")
                chunks, count = [], 0
                for chunk in response.iter_bytes():
                    if cancel is not None and cancel.is_set():
                        raise InterruptedError("Загрузка отменена")
                    count += len(chunk)
                    if count > limit:
                        raise ValueError("Изображение превышает допустимый размер")
                    chunks.append(chunk)
            with Image.open(io.BytesIO(b"".join(chunks))) as source:
                if source.width*source.height > 40_000_000:
                    raise ValueError("Изображение превышает 40 Мп")
                from app.imaging import flatten
                image = flatten(source)
            import os
            import tempfile
            fd, temp = tempfile.mkstemp(dir=self.root, suffix=".png")
            os.close(fd)
            try:
                image.save(temp, "PNG")
                os.replace(temp, path)
            finally:
                if os.path.exists(temp): os.unlink(temp)
            return image, path
        except httpx.HTTPError as exc:
            raise RuntimeError("Не удалось загрузить изображение. Проверьте соединение и страницу источника.") from exc

    def favorites(self):
        path = self.root/"favorites.json"
        return [DiscoveryImage(**row) for row in json.loads(path.read_text("utf-8"))] if path.exists() else []

    def favorite(self, item):
        items = [row for row in self.favorites() if row.page_id != item.page_id]
        items.insert(0, item)
        write_json(self.root/"favorites.json", [asdict(row) for row in items[:200]])


def difficulty(image, canvas_size=(534, 530), widths=(1, 2, 4, 8, 16, 32), palette=None, cancel=None):
    from app.planner import PlanOptions, build_plan
    plan, _ = build_plan(image, PlanOptions(canvas_size, engine="Human 3.0", human_mode="BALANCED", style="Custom",
                                           time_limit=None, brush_widths=tuple(widths), palette=palette,
                                           detect_faces=False), cancel=cancel)
    strokes = len(plan.strokes)
    return dict(colors=len(plan.palette), strokes=strokes, estimated_seconds=plan.estimated_seconds,
                shape_complexity="Высокая" if strokes > 1500 else "Средняя" if strokes > 300 else "Низкая",
                recommended_mode="FAST" if strokes > 2500 else "BALANCED" if strokes > 500 else "MASTERPIECE",
                note="Оценка плана BALANCED; задержки вашего игрового профиля изменят время")
