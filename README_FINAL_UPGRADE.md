# FINAL UPGRADE

## Что добавлено

### 1. Полноценный LLM rewrite layer
- добавлены `app/llm/client.py` и `app/llm/rewrite.py`
- поддержан OpenAI-compatible Responses API
- на вход берутся оригинальный title/text, категория и URL
- на выходе генерируются:
  - `title_ru`
  - `summary_ru`
  - `why_important_ru`
  - `market_impact_ru`
  - `quote_ru`

### 2. Раздельные стили world/economy
- для world: более новостной, жесткий и геополитический стиль
- для economy: более деловой и рынко-ориентированный стиль

### 3. Новые блоки в постах
Теперь в постах есть:
- Почему это важно
- Влияние на рынки
- ключевая цитата
- подтверждения и доп. источники

### 4. DB upgrade
В `news_items` добавлены поля:
- `why_important_ru`
- `market_impact_ru`
- `rewrite_status`
- `rewrite_model`

`app/db/init_db.py` теперь сам дотягивает эти поля через `ALTER TABLE`, если их нет.

### 5. Pipeline обновлен
Теперь основной пайплайн:
1. fetch RSS
2. enrich article
3. classify
4. rewrite via LLM/fallback
5. deduplicate
6. quality
7. build posts
8. moderation

### 6. Live RSS health-check
Добавлен `app/tasks/check_sources_health.py`

Примеры:
```bash
python -m app.tasks.check_sources_health
python -m app.tasks.check_sources_health --apply
```

Скрипт:
- проверяет все RSS
- считает entries
- пишет JSON/Markdown-отчет
- при `--apply` отключает мертвые фиды в БД

### 7. Предварительная чистка источников
Подозрительные/нестабильные RSS были заранее переведены в `is_active: false` в `sources.yaml`.
