# IDEAL UPGRADE

Что доведено в этой версии:

- Источники вынесены в `app/config/sources.yaml`.
- База источников сильно расширена, особенно по России / экономике / банкам / биржам / ЦБ / макроданным.
- Построение постов переведено с модели `1 новость = 1 пост` на модель `story cluster -> 1 post`.
- Один пост теперь может агрегировать несколько подтверждений по одной теме.
- В посте показываются:
  - тег
  - сильный заголовок
  - блок фактов
  - фокус / сущности
  - основной источник
  - дополнительные источники
  - число подтверждений
- Улучшен RSS ingest:
  - извлечение `media_content`
  - `media_thumbnail`
  - `enclosures`
  - HTML embedded `<img>` / `<video>`
  - очистка HTML из summary/title
- Улучшен article parsing:
  - fallback по `article p`, `main p`, `.entry-content p`
  - более длинный summary
  - более агрессивное извлечение lead media

Ключевые файлы:

- `app/config/sources.yaml`
- `app/sources/registry.py`
- `app/sources/rss_fetcher.py`
- `app/content/article_parser.py`
- `app/processing/story_cluster.py`
- `app/tasks/build_posts.py`
- `app/posting/formatter.py`

Ограничение текущей архитектуры:

- Для абсолютного максимума дальше нужен полноценный LLM rewrite / editorial layer:
  - headline rewrite
  - summary rewrite
  - why-it-matters block
  - market impact block
  - separate style profiles for `world` and `economy`

Но даже без этого проект теперь заметно ближе к сильному редакционному телеграм-продукту, чем к сырому RSS-боту.
