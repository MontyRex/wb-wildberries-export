from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from typing import Any, Iterable

import requests


@dataclass(frozen=True)
class SearchConfig:
    query: str
    page_size: int = 100
    max_pages: int = 50
    sleep_s: float = 0.15
    timeout_s: float = 20.0
    max_retries: int = 8


class WbClient:
    """
    Минимальный клиент WB на публичных endpoint'ах.
    """

    def __init__(self, *, timeout_s: float = 20.0, max_retries: int = 5) -> None:
        self._timeout_s = timeout_s
        self._max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json,text/plain,*/*",
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
                "Connection": "keep-alive",
            }
        )

    def _request_json(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                resp = self._session.get(url, params=params, timeout=self._timeout_s)
                # частые временные ответы: 429 (rate limit), 5xx (временная деградация)
                if resp.status_code in (429, 500, 502, 503, 504):
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        time.sleep(min(60.0, float(retry_after)))
                    else:
                        backoff = min(30.0, 0.75 * (2 ** (attempt - 1))) + random.random() * 0.5
                        time.sleep(backoff)
                    continue
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:  # noqa: BLE001 - здесь нужна общая защита сети/HTTP/JSON
                last_exc = exc
                # простая экспоненциальная пауза + jitter
                backoff = min(30.0, 0.75 * (2 ** (attempt - 1))) + random.random() * 0.5
                time.sleep(backoff)
        assert last_exc is not None
        raise last_exc

    def search_nmids(
        self,
        *,
        query: str,
        page: int,
        page_size: int,
        dest: int = -1257786,
    ) -> list[int]:
        """
        Возвращает nmId товаров со страницы выдачи.

        dest=-1257786 — "Россия" (часто используемый dest для ru).
        """
        # На практике v4 периодически возвращает пустые products,
        # поэтому используем v5 как основной.
        url_v5 = "https://search.wb.ru/exactmatch/ru/common/v5/search"
        params_v5 = {
            "appType": 1,
            "curr": "rub",
            "dest": dest,
            "query": query,
            "page": page,
            "resultset": "catalog",
            "sort": "popular",
            "spp": 30,
            "suppressSpellcheck": "false",
            "limit": page_size,
            # Эти параметры часто присутствуют в запросах фронта и повышают стабильность выдачи.
            "regions": "80,64,38,4,83,33,68,70,69,30,86,75,40,1,66,31,22,71",
            "stores": "117673,122258,122259,125238,125239,125240,132318,132320,132321,132322,138642,138643,158413,159402,159403,160934,168257,168258,168259,168260",
        }
        try:
            data = self._request_json(url_v5, params=params_v5)
        except Exception:
            # fallback на v4, если v5 временно недоступен
            url_v4 = "https://search.wb.ru/exactmatch/ru/common/v4/search"
            params_v4 = {
                "TestGroup": "no_test",
                "TestID": "no_test",
                "appType": 1,
                "curr": "rub",
                "dest": dest,
                "query": query,
                "page": page,
                "resultset": "catalog",
                "sort": "popular",
                "spp": 30,
                "suppressSpellcheck": "false",
                "pageSize": page_size,
            }
            data = self._request_json(url_v4, params=params_v4)
        # v4: {"data": {"products": [...]}}
        # v5: {"products": [...], "total": ...}
        products = (data.get("data") or {}).get("products") or data.get("products") or []
        nmids: list[int] = []
        for p in products:
            nm = p.get("id")
            if isinstance(nm, int):
                nmids.append(nm)
        return nmids

    def cards_detail(self, nmids: Iterable[int], *, dest: int = -1257786) -> list[dict[str, Any]]:
        """
        Возвращает "сырой" JSON карточек по nmId (можно батчами).
        """
        url = "https://card.wb.ru/cards/v1/detail"
        nm_str = ";".join(str(x) for x in nmids)
        params = {
            "appType": 1,
            "curr": "rub",
            "dest": dest,
            "spp": 30,
            "nm": nm_str,
        }
        # На части окружений этот endpoint возвращает 404 (отключён/переехал).
        # Тогда просто считаем, что enrichment недоступен.
        try:
            data = self._request_json(url, params=params)
        except requests.HTTPError as exc:
            resp = getattr(exc, "response", None)
            if resp is not None and getattr(resp, "status_code", None) == 404:
                return []
            raise
        products = (data.get("data") or {}).get("products") or []
        return [p for p in products if isinstance(p, dict)]


def wb_product_url(nmid: int) -> str:
    return f"https://www.wildberries.ru/catalog/{nmid}/detail.aspx"


def wb_seller_url(supplier_id: int) -> str:
    return f"https://www.wildberries.ru/seller/{supplier_id}"


def wb_image_urls(nmid: int, pics: int | None) -> list[str]:
    """
    Строит прямые ссылки на изображения (если известно количество).
    Формат (CDN): https://images.wbstatic.net/big/new/{vol}/{part}/{nmid}-1.jpg
    """
    if not pics or pics <= 0:
        return []
    vol = nmid // 100000
    part = nmid // 1000
    base = f"https://images.wbstatic.net/big/new/{vol}/{part}"
    return [f"{base}/{nmid}-{i}.jpg" for i in range(1, pics + 1)]


def extract_characteristics(product: dict[str, Any]) -> Any:
    """
    Сохраняем структуру характеристик как есть (обычно это список словарей).
    """
    for key in ("options", "properties", "characteristics"):
        if key in product:
            return product.get(key)
    # fallback: если это объект из поиска v5, соберём "минимальный" набор в той же структуре list[dict]
    fallback: list[dict[str, Any]] = []
    for k, label in (
        ("brand", "Бренд"),
        ("supplier", "Селлер"),
        ("supplierRating", "Рейтинг селлера"),
        ("weight", "Вес"),
        ("volume", "Объём"),
        ("colors", "Цвета"),
        ("entity", "Тип"),
        ("kindId", "kindId"),
        ("subjectId", "subjectId"),
    ):
        v = product.get(k)
        if v is None:
            continue
        if isinstance(v, (str, int, float)):
            fallback.append({"name": label, "value": str(v)})
        elif isinstance(v, list):
            fallback.append({"name": label, "values": [str(x) for x in v if x is not None]})
        elif isinstance(v, dict):
            fallback.append({"name": label, "value": v})
    return fallback


def characteristics_to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False)


def extract_sizes(product: dict[str, Any]) -> list[str]:
    sizes = product.get("sizes")
    if not isinstance(sizes, list):
        return []
    out: list[str] = []
    for s in sizes:
        if not isinstance(s, dict):
            continue
        name = s.get("name") or s.get("origName")
        if isinstance(name, str) and name.strip():
            out.append(name.strip())
    # dedupe while preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for x in out:
        if x in seen:
            continue
        seen.add(x)
        uniq.append(x)
    return uniq


def extract_stocks_total(product: dict[str, Any]) -> int:
    # В выдаче поиска есть totalQuantity — самый дешёвый и обычно корректный вариант.
    tq = product.get("totalQuantity")
    if isinstance(tq, int):
        return tq
    sizes = product.get("sizes")
    if not isinstance(sizes, list):
        return 0
    total = 0
    for s in sizes:
        if not isinstance(s, dict):
            continue
        stocks = s.get("stocks")
        if not isinstance(stocks, list):
            continue
        for st in stocks:
            if not isinstance(st, dict):
                continue
            qty = st.get("qty")
            if isinstance(qty, int):
                total += qty
    return total


def extract_country_of_origin(characteristics: Any) -> str | None:
    """
    Нужна для фильтра "страна производства Россия".
    В карточках WB это чаще всего в options/properties.
    """
    if not characteristics:
        return None

    def norm(s: str) -> str:
        return " ".join(s.lower().replace("ё", "е").split())

    keys = {
        norm("Страна производства"),
        norm("Страна-изготовитель"),
        norm("Страна изготовитель"),
        norm("Страна"),
    }

    # варианты структуры:
    # - list[{"name": "...", "value": "..."}]
    # - dict / list с вложенностью
    if isinstance(characteristics, list):
        for item in characteristics:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            value = item.get("value")
            if isinstance(name, str) and norm(name) in keys and isinstance(value, str):
                return value.strip()
            # иногда: {"name": "...", "values": ["..."]}
            values = item.get("values")
            if isinstance(name, str) and norm(name) in keys and isinstance(values, list) and values:
                v0 = values[0]
                if isinstance(v0, str):
                    return v0.strip()

    if isinstance(characteristics, dict):
        # Иногда в виде плоского dict: {"Страна производства": "Россия"}
        for k, v in characteristics.items():
            if isinstance(k, str) and norm(k) in keys:
                if isinstance(v, str):
                    return v.strip()
                if isinstance(v, list) and v and isinstance(v[0], str):
                    return v[0].strip()
    return None

