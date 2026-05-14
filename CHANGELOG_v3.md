# 📋 Инструкция по обновлению Telegram News Bot (v3)

## Что изменилось

### 🔥 Основные исправления

| Проблема | Решение |
|----------|---------|
| Постились старые новости (ставка ЦБ 21% вместо 15,5%) | Добавлен фильтр свежести: новости старше **36 часов** не обрабатываются |
| Технические страницы ЦБ РФ попадали в ленту | Фильтр по URL: `/pffl`, `/dirrepo`, `/UniDbQuery`, `/File/90134` |
| При запуске бот ждал 15 минут до первого пуска | Пайплайн теперь стартует **немедленно** при запуске |
| Дедупликация не работала (0/500) | Исправлен запрос — теперь учитывает окно 48 часов |
| Блок «Почему важно» — однотипный и бесполезный | **Убран**. Summary стал насыщеннее (4 предложения) |

---

### 🎨 Новое форматирование постов

**Brief | World** (мировые новости):
```
💥 ЗАГОЛОВОК ЗАГЛАВНЫМИ БУКВАМИ

4 предложения: факт → детали → реакция → что дальше.

«Цитата, если есть»

— Сообщает Коммерсантъ @kommersant | #война
```

**Brief | Economy** (экономика):
```
🏦 Заголовок с цифрами

4 предложения: факт с цифрами → детали → тренд → смысл.

📌 Что это значит: рыночный эффект

«Цитата»

По данным Ведомости @vedomosti | #монетарка
```

---

### ⚖️ Соответствие законодательству РФ

Добавлена автоматическая маркировка при упоминании:
- **Иностранные агенты** (`*`) — Медуза, ТВ Дождь, Медиазона и др. (ФЗ №255-ФЗ)
- **Нежелательные организации** (`†`) — USAID, NED, фонд Сороса и др.
- **Запрещённые организации** (`‡`) — ИГИЛ, Аль-Каида, Азов и др.

Сноски автоматически добавляются в конец поста.

---

### 🔧 Технические улучшения

- Telegram-ручки источников: `@kommersant`, `@rian_ru`, `@vedomosti` и др.
- Кнопка **«📰 Читать полностью»** у всех постов (была «Открыть источник»)
- LLM промпты переписаны: убрано `why_important_ru`, стиль под каждый канал

---

## 🚀 Инструкция по установке

### 1. Скопировать изменённые файлы

Замените следующие файлы в вашем проекте:

```
app/posting/formatter.py          ← новый стиль постов
app/posting/publisher.py          ← кнопка «Читать полностью»
app/llm/rewrite.py                ← новые промпты, убрано «Почему важно»
app/tasks/rewrite_news.py         ← фильтр свежести 36ч
app/tasks/build_posts.py          ← фильтр 24ч + фильтр URL ЦБ
app/tasks/deduplicate_news.py     ← исправлен запрос
app/tasks/scheduler.py            ← старт при запуске
app/processing/classifier.py     ← фильтр технических URL ЦБ
app/processing/quality_filter.py  ← фильтр URL ЦБ
app/processing/legal_compliance.py ← НОВЫЙ: маркировка иноагентов
scripts/reset_db.py               ← НОВЫЙ: управление БД
```

---

### 2. Очистка базы данных (ОБЯЗАТЕЛЬНО перед первым запуском)

Нужно очистить устаревшие данные ЦБ и старые новости:

```bash
cd /путь/к/проекту
source venv/bin/activate

# Показать текущее состояние БД
python scripts/reset_db.py --status

# Удалить технические страницы ЦБ РФ (ставка 21% и т.п.)
python scripts/reset_db.py --clear-cbr

# Отфильтровать новости старше 36 часов
python scripts/reset_db.py --clear-stale --hours 36

# Сбросить застрявшие в retry/error → pending (для свежих новостей)
python scripts/reset_db.py --reset-pending
```

**Если хотите начать полностью с нуля** (все старые посты тоже удалятся):
```bash
python scripts/reset_db.py --clear-all
# Введите 'yes' для подтверждения
```

---

### 3. Обновить реестр иноагентов

Файл: `app/processing/legal_compliance.py`

Реестр Минюста обновляется каждую пятницу. Следите за обновлениями:
- https://minjust.gov.ru/ru/pages/reestr-inostryannykh-agentov/

Для добавления нового иноагента — добавьте строку в `INOAGENTS`:
```python
INOAGENTS = [
    ...
    (["название издания", "альтернативное название"], "Название*"),
    ...
]
```

---

### 4. Запустить бота

```bash
cd /путь/к/проекту
source venv/bin/activate
python main.py
```

Бот сразу запустит первый пайплайн (не нужно ждать 15 минут).

---

## 🗃️ Полезные команды для работы с БД

```bash
# Показать статистику
python scripts/reset_db.py --status

# Если застряли в очереди — сбросить
python scripts/reset_db.py --reset-pending

# Отфильтровать старые новости вручную
python scripts/reset_db.py --clear-stale --hours 48

# Очистить только технические данные ЦБ
python scripts/reset_db.py --clear-cbr
```

### Прямые SQL-команды (если нужно)

```sql
-- Статус очереди
SELECT status, rewrite_status, COUNT(*) 
FROM news_items 
GROUP BY status, rewrite_status 
ORDER BY count DESC;

-- Удалить конкретный URL из БД
DELETE FROM news_items WHERE original_url LIKE '%cbr.ru%';

-- Сбросить все ошибки переписи за последние 24ч
UPDATE news_items 
SET rewrite_status = 'pending' 
WHERE rewrite_status IN ('retry', 'error') 
  AND fetched_at >= NOW() - INTERVAL '24 hours';

-- Посмотреть последние опубликованные посты
SELECT ni.title_ru, p.published_at, c.name 
FROM posts p
JOIN news_items ni ON p.news_id = ni.id
JOIN channels c ON p.channel_id = c.id
WHERE p.status = 'published'
ORDER BY p.published_at DESC
LIMIT 20;
```

---

## ⚠️ Что нужно сделать вручную

1. **Добавить Telegram-ручки источников** в `app/posting/formatter.py` в словарь `_SOURCE_TG_MAP`, если у ваших источников есть Telegram-каналы, которых там нет.

2. **Обновить список иноагентов** при необходимости в `app/processing/legal_compliance.py`. Список актуален на март 2026 года.

3. **Обновить ключевую ставку** в промптах — LLM получит актуальные данные из источников, если они там есть. Но для надёжности можно добавить системный контекст в `app/llm/rewrite.py`:
   ```python
   # В начале ECONOMY_SYSTEM добавьте:
   "Текущая ключевая ставка ЦБ РФ: 15,5% (март 2026)."
   ```

---

## 📊 Архитектура пайплайна (как работает)

```
RSS Fetch (источники)
    ↓
Enrich (полный текст + изображение)
    ↓
Classify (world / economy / discard)
    ↓ 
Rewrite LLM — только свежие (<36ч)
    ↓
Quality Check (score ≥ 4)
    ↓
Deduplicate (48ч окно)
    ↓
Build Posts — только свежие (<24ч), фильтр URL ЦБ
    ↓
Publish Posts → Telegram
```

Каждые **15 минут**. При старте — сразу.
