# Telegram News Bot — v2 Upgrade

Полностью переработанный production-ready бот для автоматической агрегации и публикации новостей в двух Telegram-каналах: **World** и **Economy**.

---

## Что было улучшено (v1 → v2)

### Архитектура
| Модуль | До | После |
|---|---|---|
| Форматтер постов | Шаблонные метки ("Суть:", "Коротко:") | Живые абзацы, умные эмодзи, динамические хэштеги |
| Классификатор | Простой подсчёт кейвордов | Взвешенный scoring + `confidence` (0.0–1.0) |
| Дедупликация | URL + fuzzy title | URL + fuzzy + story cluster (token overlap) |
| Маршрутизация на модерацию | Всё или ничего | Только реально спорные/рисковые посты |
| LLM промпты | Краткие шаблоны | Детальные промпты, требующие живых абзацев без листингов |
| Медиа | Базовая загрузка | OG extraction, scoring, video support, fallback цепочка |
| Здоровье источников | Нет | Live HTTP probe, авто-отключение мёртвых фидов |
| Источники | ~30 без метаданных | 60+ с полной схемой (trust/priority/clusters/freshness) |
| Pipeline | Прерывается на ошибке | Каждый шаг изолирован, ошибки логируются без остановки |

---

## Структура проекта

```
app/
├── bot/
│   └── moderation_bot.py      # Approve/Reject callbacks
├── config/
│   ├── sources.yaml            # Полная база источников с метаданными
│   └── content_rules.py
├── core/
│   ├── config.py               # Settings (pydantic-settings + .env)
│   └── logger.py
├── db/
│   ├── init_db.py
│   ├── seed_channels.py
│   └── seed_sources.py         # Загрузка sources.yaml → DB
├── llm/
│   ├── client.py
│   └── rewrite.py              # Улучшенные промпты с живыми абзацами
├── media/
│   └── downloader.py           # OG extraction, scoring, video, fallback
├── models/
│   ├── news_item.py            # Расширена: routing_confidence, cluster_id, moderation_flags
│   ├── source.py               # Расширена: health_status, trust_score, clusters
│   ├── post.py
│   └── channel.py
├── posting/
│   ├── formatter.py            # Новый форматтер: эмодзи, хэштеги, живые абзацы
│   └── publisher.py
├── processing/
│   ├── classifier.py           # Weighted scoring + confidence + cross-channel logic
│   ├── deduplicator.py         # Exact + near-dup + story cluster
│   ├── moderation_router.py    # Централизованная логика модерации
│   └── quality_filter.py
├── sources/
│   ├── registry.py             # Загрузка sources.yaml, lookup helpers
│   └── rss_fetcher.py          # Image/video extraction из RSS
└── tasks/
    ├── pipeline.py             # Resilient pipeline, изолированные шаги
    ├── scheduler.py            # 15min pipeline + 6h health check + daily cleanup
    ├── check_sources_health.py # HTTP probe всех фидов
    ├── build_posts.py          # Создание постов с moderation routing
    ├── classify_news.py
    ├── deduplicate_news.py     # Multi-level dedup
    ├── enrich_article_summaries.py  # trafilatura + OG image
    ├── publish_posts.py        # text/photo/video posting
    ├── quality_check_news.py
    ├── rewrite_news.py
    └── send_to_moderation.py   # Только спорные посты → moderation chat
```

---

## Быстрый старт

### 1. Конфигурация

```bash
cp .env.example .env
# Заполни BOT_TOKEN, CHANNEL_WORLD_ID, CHANNEL_ECONOMY_ID
```

### 2. База данных

```bash
python -m app.db.init_db          # Создать таблицы
python -m app.db.seed_channels    # Создать каналы
python -m app.db.seed_sources     # Загрузить источники из sources.yaml
```

### 3. Запуск

```bash
python main.py
```

---

## Pipeline (порядок шагов)

```
fetch_rss → enrich → classify → rewrite → quality_check → dedup → build_posts → publish → moderation
```

Каждый шаг изолирован: ошибка в одном не блокирует следующие.

**Расписание:** каждые 15 минут (настраивается через `PIPELINE_INTERVAL_MINUTES`).

---

## Модерация

В moderation chat уходят только:
- низкая уверенность классификатора (`confidence < 0.55`)
- низкий `trust_score` источника
- маркеры слухов, шок-контента, фейков
- слабый тип источника (social, blog, unknown)

**Нормальные новости публикуются автоматически.** Модерация — исключение.

---

## Источники (sources.yaml)

60+ источников с полной схемой:
- Мировые: AP, BBC, Al Jazeera, FT, Bloomberg, WSJ, Guardian, NYT, DW
- Российские деловые: РБК, Коммерсантъ, Ведомости, Интерфакс, Banki.ru
- Официальные: ЦБ РФ, Минфин, ФНС, МОЕХ, Сбербанк, ВТБ
- ЦБ мировые: ECB, Fed, IMF, World Bank
- Нефть/газ: EIA, OPEC, Neftegaz.ru, OilPrice, S&P Commodities
- Санкции: OFAC (US Treasury), EU Council
- Геополитика: Politico Europe, Foreign Affairs, Kyiv Independent
- Азия: Nikkei, SCMP

---

## Диагностика источников

```bash
python -m app.tasks.check_sources_health
```

Выводит таблицу: статус / HTTP / время ответа / кол-во записей / свежесть.  
Автоматически отключает источники с ≥5 подряд неудачными проверками.

---

## Формат постов

**World:**
```
💥 Заголовок новости

Первый абзац — основная суть события.

Второй абзац — контекст и детали.

Почему важно: объяснение геополитического значения.

«Сильная цитата, если есть»

AP — World #война
```

**Economy:**
```
🏦 Заголовок новости

Первый абзац — что произошло.

Второй абзац — цифры и детали.

Влияние на рынки: конкретный рыночный эффект.

РБК #монетарнаяполитика
```

---

## Переменные окружения

| Переменная | Описание | Default |
|---|---|---|
| `BOT_TOKEN` | Telegram bot token | обязательно |
| `CHANNEL_WORLD_ID` | ID канала World | обязательно |
| `CHANNEL_ECONOMY_ID` | ID канала Economy | обязательно |
| `MODERATION_CHAT_ID` | ID чата модерации | опционально |
| `OPENAI_API_KEY` | API ключ LLM | опционально |
| `OPENAI_MODEL` | Модель | `gpt-4.1-mini` |
| `LLM_REWRITE_ENABLED` | Включить LLM rewrite | `true` |
| `PIPELINE_INTERVAL_MINUTES` | Интервал запуска | `15` |
| `MIN_QUALITY_SCORE` | Минимальный quality score | `4` |
| `AUTO_PUBLISH_CONFIDENCE_THRESHOLD` | Порог авто-публикации | `0.55` |
