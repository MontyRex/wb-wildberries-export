# Wildberries XLSX экспорт каталога

Тестовое: выгрузить каталог товаров Wildberries по поисковому запросу **«пальто из натуральной шерсти»** в XLSX и дополнительно сформировать отдельный XLSX-файл с фильтром:

- рейтинг **≥ 4.5**
- цена **≤ 10000**
- страна производства **Россия**

## Что делает скрипт

Скрипт:

1. Забирает из поиска Wildberries все товары по запросу.
2. Для каждого товара подтягивает данные карточки (описание, характеристики, размеры, остатки, рейтинг/отзывы, продавец и т.д.).
3. Сохраняет **полный каталог** в `output/catalog_full.xlsx`.
4. Сохраняет **выборку** в `output/catalog_filtered.xlsx`.

## Установка и запуск (Windows / PowerShell)

Перейдите в папку проекта:

```bash
cd "C:\Users\MontyRex\wb-wildberries-export"
```

Создайте виртуальное окружение и установите зависимости:

```bash
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -U pip
pip install -r requirements.txt
```

Запуск (по умолчанию используется нужный запрос):

```bash
py -m wb_export
```

Полезные параметры:

```bash
py -m wb_export --max-pages 50 --page-size 100 --sleep 0.3
```

Если в вашем окружении доступен endpoint карточек `card.wb.ru`, можно попробовать подтянуть расширенные поля (описание/характеристики/страна производства и т.п.):

```bash
py -m wb_export --enrich-cards
```

## Выходные файлы

- `output/catalog_full.xlsx` — полный каталог по запросу.
- `output/catalog_filtered.xlsx` — выборка по условиям тестового.

## Колонки в XLSX

- `product_url` — ссылка на товар
- `article` — артикул (nmId)
- `name` — название
- `price` — цена (руб.)
- `description` — описание
- `image_urls` — ссылки на изображения через запятую
- `characteristics_json` — все характеристики (JSON-строка, структура сохранена)
- `seller_name` — название селлера
- `seller_url` — ссылка на селлера
- `sizes` — размеры через запятую
- `stocks_total` — остатки по товару (число)
- `rating` — рейтинг
- `reviews_count` — количество отзывов

## Как залить на GitHub

1. Создайте репозиторий на GitHub.
2. В PowerShell:

```bash
cd "C:\Users\MontyRex\wb-wildberries-export"
git init
git add .
git commit -m "Initial: Wildberries каталог в XLSX"
git branch -M main
git remote add origin <URL_вашего_репозитория>
git push -u origin main
```

## Примечания

- Скрипт использует публичные HTTP-endpoint’ы, без браузера/selenium.
- Для стабильности: повтор запросов, обработка `429 Too Many Requests`, и пауза между страницами поиска.
- В некоторых сетях/регионах “полная карточка” может быть недоступна (endpoint’ы меняются/ограничиваются). В этом случае выгрузка всё равно будет построена по данным из поиска, но часть полей может быть пустой, а выборка по стране производства — меньше или пустая.

