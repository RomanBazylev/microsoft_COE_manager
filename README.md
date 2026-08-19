# SF Auto-Poster 🤖

Автоматически публикует актуальный Salesforce-контент в нужные каналы Microsoft Teams.
Хостится полностью на GitHub — никаких серверов.

## Как это работает

```
Official Releases / Salesforce RSS / Events / Q&A
        ↓
   Fetcher (Python)          ← собирает контент
        ↓
   Priority Filter           ← mandatory official updates bypass normal scoring
        ↓
   Router                    ← маппинг на нужный канал
        ↓
   Microsoft Teams Webhooks  ← публикует Adaptive Card
        ↓
   GitHub Pages Dashboard    ← трекинг всего запощенного
```

**GitHub Actions** запускает пайплайн по расписанию.
**GitHub Secrets** хранят все чувствительные данные.
**GitHub Pages** отдаёт дашборд, включая состояние каждого фида и последнего запуска.

---

## Быстрый старт

### 1. Fork / clone репозитория

```bash
git clone https://github.com/YOUR_ORG/sf-autoposter.git
cd sf-autoposter
```

### 2. Добавить GitHub Secrets

Перейди в **Settings → Secrets and variables → Actions → New repository secret**
и добавь следующие секреты:

| Secret name                      | Где взять                                    |
|----------------------------------|----------------------------------------------|
| `GEMINI_API_KEY`                 | console.cloud.google.com → AI Studio → API Keys |
| `TEAMS_WEBHOOK_CERTIFICATION`    | Teams → канал → … → Connectors → Incoming Webhook |
| `TEAMS_WEBHOOK_PLAYGROUND`       | аналогично                                   |
| `TEAMS_WEBHOOK_SALESFORCE_RSS`   | аналогично                                   |
| `TEAMS_WEBHOOK_NEED_HELP`        | аналогично                                   |
| `TEAMS_WEBHOOK_MEETUP_EVENTS`    | аналогично                                   |
| `TEAMS_WEBHOOK_TOPIC_OF_THE_DAY` | аналогично                                   |

> **Важно**: Webhooks без настроенного секрета просто пропускаются.
> Можно начать с одного канала и добавлять остальные по мере готовности.

### 3. Включить GitHub Pages

**Settings → Pages → Source: GitHub Actions**. Workflow deploys `docs/` after every run.

После первого запуска дашборд будет доступен по адресу:
`https://YOUR_ORG.github.io/sf-autoposter/`

### 4. Создать папку data/ и закоммитить пустые файлы

```bash
mkdir -p data
echo "[]" > data/post_log.json
echo "[]" > data/seen_ids.json
git add data/
git commit -m "init: empty data files"
git push
```

### 5. Запустить вручную для теста

**Actions → SF Auto-Poster → Run workflow**

---

## Расписание

Настраивается в `.github/workflows/autoposter.yml`:

```yaml
schedule:
  - cron: "0 8 * * 1-5"      # будни: все каналы
  - cron: "0 8 * * 0,6"      # выходные: только официальные источники
```

---

## Локальный запуск (для разработки)

```bash
pip install -r requirements.txt

export GEMINI_API_KEY="AIza..."
export TEAMS_WEBHOOK_CERTIFICATION="https://..."

python src/main.py
```

---

## Структура проекта

```
sf-autoposter/
├── .github/
│   └── workflows/
│       └── autoposter.yml    # CI/CD расписание + деплой Pages
├── src/
│   ├── main.py               # точка входа, оркестрация
│   ├── fetcher.py            # RSS + source metadata + health
│   ├── official_fetcher.py   # Salesforce Releases hub
│   ├── filter.py             # scoring, priority routing, delivered IDs
│   ├── artifacts.py          # dashboard JSON artifacts
│   └── poster.py             # постинг в Teams + лог
├── docs/
│   └── index.html            # GitHub Pages дашборд
├── data/
│   ├── post_log.json         # лог всех публикаций (коммитится ботом)
│   ├── seen_ids.json         # только успешно доставленные IDs
│   ├── feed_health.json      # здоровье источников
│   └── last_run.json         # итог последнего запуска
├── requirements.txt
└── README.md
```

---

## Добавить новый канал

1. Добавь канал в `src/fetcher.py` → `FEEDS`
2. Добавь ключевые слова и приоритет в `src/filter.py`
3. Добавь маппинг в `src/poster.py` → `CHANNEL_WEBHOOKS`
4. Добавь Secret в GitHub Settings
5. Добавь кнопку фильтра в `docs/index.html`

---

## Переменные окружения (никогда не в коде)

| Переменная                | Описание                          |
|---------------------------|-----------------------------------|
| `GEMINI_API_KEY`          | Gemini API для AI-фильтрации      |
| `TEAMS_WEBHOOK_*`         | Incoming Webhook URL для каждого канала |

Все хранятся в **GitHub Secrets** и передаются в Actions через `env:`.

## Гарантии доставки

- Official release/security items получают `must_post`, обходят relevance threshold и лимит curated-постов.
- URL-дубликаты выбираются по source/channel priority, а не по порядку фидов.
- `seen_ids.json` обновляется только после успешного ответа Teams. Failed и capped items повторяются.
- `DRY_RUN=true` не меняет delivery state или post log.
- Releases hub отслеживает новые ссылки и изменения названий ресурсов; RSS health публикуется на dashboard.
