from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Iterable

from tqdm import tqdm

from wb_export.export_xlsx import write_xlsx
from wb_export.wb_api import (
    SearchConfig,
    WbClient,
    characteristics_to_json,
    extract_characteristics,
    extract_country_of_origin,
    extract_sizes,
    extract_stocks_total,
    wb_image_urls,
    wb_product_url,
    wb_seller_url,
)


def _chunks(items: list[int], size: int) -> Iterable[list[int]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _price_rub(product: dict[str, Any]) -> int | None:
    # card.wb.ru (если доступно) часто отдаёт priceU/salePriceU в "копейках * 100"
    for key in ("salePriceU", "priceU"):
        v = product.get(key)
        if isinstance(v, int) and v > 0:
            return int(round(v / 100))
    # search v5 отдаёт цену внутри sizes[].price.product/basic (тоже обычно /100)
    sizes = product.get("sizes")
    if isinstance(sizes, list) and sizes:
        s0 = sizes[0]
        if isinstance(s0, dict):
            price = s0.get("price")
            if isinstance(price, dict):
                for key in ("product", "basic"):
                    v = price.get(key)
                    if isinstance(v, int) and v > 0:
                        return int(round(v / 100))
    return None


def normalize_product(product: dict[str, Any]) -> dict[str, Any]:
    nmid = product.get("id")
    if not isinstance(nmid, int):
        nmid = product.get("nmId") if isinstance(product.get("nmId"), int) else None

    name = product.get("name") if isinstance(product.get("name"), str) else None
    description = product.get("description") if isinstance(product.get("description"), str) else None
    rating = product.get("rating")
    rating = float(rating) if isinstance(rating, (int, float)) else None
    reviews_count = product.get("feedbacks")
    reviews_count = int(reviews_count) if isinstance(reviews_count, int) else None

    supplier_id = product.get("supplierId")
    supplier_id = int(supplier_id) if isinstance(supplier_id, int) else None
    seller_name = product.get("supplier") if isinstance(product.get("supplier"), str) else None

    pics = product.get("pics")
    pics = int(pics) if isinstance(pics, int) else None

    characteristics = extract_characteristics(product)
    characteristics_json = characteristics_to_json(characteristics) if characteristics is not None else None

    sizes = extract_sizes(product)
    stocks_total = extract_stocks_total(product)

    row = {
        "product_url": wb_product_url(nmid) if isinstance(nmid, int) else None,
        "article": nmid,
        "name": name,
        "price": _price_rub(product),
        "description": description,
        "image_urls": ", ".join(wb_image_urls(nmid, pics)) if isinstance(nmid, int) else "",
        "characteristics_json": characteristics_json,
        "seller_name": seller_name,
        "seller_url": wb_seller_url(supplier_id) if isinstance(supplier_id, int) else None,
        "sizes": ", ".join(sizes),
        "stocks_total": stocks_total,
        "rating": rating,
        "reviews_count": reviews_count,
    }
    # для фильтрации добавим техническое поле (потом выкинем)
    row["_country"] = extract_country_of_origin(characteristics)
    return row


def filter_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def norm_country(v: str) -> str:
        return " ".join(v.lower().replace("ё", "е").split())

    for r in rows:
        rating = r.get("rating")
        price = r.get("price")
        country = r.get("_country")

        ok_rating = isinstance(rating, (int, float)) and float(rating) >= 4.5
        ok_price = isinstance(price, int) and price <= 10_000
        ok_country = isinstance(country, str) and norm_country(country) == norm_country("Россия")

        if ok_rating and ok_price and ok_country:
            out.append(r)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Wildberries: экспорт каталога в XLSX")
    p.add_argument("--query", default="пальто из натуральной шерсти", help="Поисковый запрос")
    p.add_argument("--max-pages", type=int, default=50, help="Максимум страниц поиска")
    p.add_argument("--page-size", type=int, default=100, help="Размер страницы поиска (обычно до 100)")
    p.add_argument("--sleep", type=float, default=0.15, help="Пауза между страницами поиска (сек)")
    p.add_argument("--batch-size", type=int, default=80, help="Сколько nmId запрашивать за раз в card detail")
    p.add_argument(
        "--enrich-cards",
        action="store_true",
        help="Пытаться подтянуть расширенные поля из card.wb.ru (может быть недоступно и тогда будет пропуск)",
    )
    p.add_argument("--out-dir", default="output", help="Папка для XLSX")
    args = p.parse_args(argv)

    cfg = SearchConfig(
        query=args.query,
        page_size=args.page_size,
        max_pages=args.max_pages,
        sleep_s=args.sleep,
    )

    client = WbClient(timeout_s=cfg.timeout_s, max_retries=cfg.max_retries)

    rows: list[dict[str, Any]] = []

    # Базовый набор данных берём из выдачи поиска (она сейчас самая стабильная).
    # Если включен enrich, попытаемся заменить/дополнить поля данными карточки.
    # Для простоты: делаем отдельные запросы карточек и мерджим по nmId.
    # (Если endpoint недоступен, cards_detail вернёт пусто.)
    search_products: list[dict[str, Any]] = []
    for page in range(1, cfg.max_pages + 1):
        # повторяем поиск еще раз, но уже забираем полные объекты из ответа через _request_json
        # чтобы получить seller/price/totalQuantity и т.д. (не только nmId)
        data = client._request_json(
            "https://search.wb.ru/exactmatch/ru/common/v5/search",
            params={
                "appType": 1,
                "curr": "rub",
                "dest": -1257786,
                "query": cfg.query,
                "page": page,
                "resultset": "catalog",
                "sort": "popular",
                "spp": 30,
                "suppressSpellcheck": "false",
                "limit": cfg.page_size,
                "regions": "80,64,38,4,83,33,68,70,69,30,86,75,40,1,66,31,22,71",
                "stores": "117673,122258,122259,125238,125239,125240,132318,132320,132321,132322,138642,138643,158413,159402,159403,160934,168257,168258,168259,168260",
            },
        )
        products = (data.get("products") or []) if isinstance(data, dict) else []
        if not products:
            break
        for p0 in products:
            if isinstance(p0, dict) and isinstance(p0.get("id"), int):
                search_products.append(p0)
        if cfg.sleep_s > 0:
            import time

            time.sleep(cfg.sleep_s)

    # unique by id
    seen2: set[int] = set()
    uniq_search_products: list[dict[str, Any]] = []
    for p0 in search_products:
        nmid = p0.get("id")
        if not isinstance(nmid, int) or nmid in seen2:
            continue
        seen2.add(nmid)
        uniq_search_products.append(p0)

    cards_by_id: dict[int, dict[str, Any]] = {}
    if args.enrich_cards:
        for batch in tqdm(list(_chunks([p0["id"] for p0 in uniq_search_products], args.batch_size)), desc="Enrich карточки", unit="batch"):
            for prod in client.cards_detail(batch):
                pid = prod.get("id")
                if isinstance(pid, int):
                    cards_by_id[pid] = prod

    for p0 in tqdm(uniq_search_products, desc="Нормализация", unit="item"):
        nmid = p0.get("id")
        if isinstance(nmid, int) and nmid in cards_by_id:
            merged = {**p0, **cards_by_id[nmid]}
            rows.append(normalize_product(merged))
        else:
            rows.append(normalize_product(p0))

    out_dir = Path(args.out_dir)
    full_path = out_dir / "catalog_full.xlsx"
    filtered_path = out_dir / "catalog_filtered.xlsx"

    # убираем техническое поле перед записью
    full_rows = [{k: v for k, v in r.items() if k != "_country"} for r in rows]
    write_xlsx(full_rows, full_path)

    filtered = filter_rows(rows)
    filtered_rows = [{k: v for k, v in r.items() if k != "_country"} for r in filtered]
    write_xlsx(filtered_rows, filtered_path)

    print(f"OK: {full_path} (rows={len(full_rows)})")
    print(f"OK: {filtered_path} (rows={len(filtered_rows)})")
    return 0

