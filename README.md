# SF Auto-Poster 🤖

Автоматически публикует актуальный Salesforce-контент в нужные каналы Microsoft Teams.
Хостится полностью на GitHub — никаких серверов.

## Как это работает

```
RSS / YouTube / Trailhead
        ↓
   Fetcher (Python)          ← собирает контент
        ↓
   AI Filter (Gemini)        ← оценивает релевантность, отсекает старьё (>90 дней)
        ↓
   Router                    ← маппинг на нужный канал
        ↓
   Microsoft Teams Webhooks  ← публикует Adaptive Card
        ↓
   GitHub Pages Dashboard    ← трекинг всего запощенного
```

**GitHub Actions** запускает пайплайн по расписанию.
**GitHub Secrets** хранят все чувствительные данные.
**GitHub Pages** отдаёт дашборд.

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
| `YOUTUBE_API_KEY`                | console.cloud.google.com → YouTube Data API v3 |
| `TEAMS_WEBHOOK_CERTIFICATION`    | Teams → канал → … → Connectors → Incoming Webhook |
| `TEAMS_WEBHOOK_PLAYGROUND`       | аналогично                                   |
| `TEAMS_WEBHOOK_SALESFORCE_RSS`   | аналогично                                   |
| `TEAMS_WEBHOOK_NEED_HELP`        | аналогично                                   |
| `TEAMS_WEBHOOK_MEETUP_EVENTS`    | аналогично                                   |
| `TEAMS_WEBHOOK_TOPIC_OF_THE_DAY` | аналогично                                   |

> **Важно**: Webhooks без настроенного секрета просто пропускаются.
> Можно начать с одного канала и добавлять остальные по мере готовности.

### 3. Включить GitHub Pages

**Settings → Pages → Source: GitHub Actions**

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
  - cron: "0 8 * * 1,3,5"   # Пн/Ср/Пт в 10:00 Warsaw
  - cron: "0 7 * * *"        # Ежедневно для канала Events
```

---

## Локальный запуск (для разработки)

```bash
pip install -r requirements.txt

export GEMINI_API_KEY="AIza..."
export YOUTUBE_API_KEY="AIza..."
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
│   ├── fetcher.py            # сбор контента из RSS, YouTube
│   ├── filter.py             # AI-фильтрация через Claude API
│   └── poster.py             # постинг в Teams + лог
├── docs/
│   └── index.html            # GitHub Pages дашборд
├── data/
│   ├── post_log.json         # лог всех публикаций (коммитится ботом)
│   └── seen_ids.json         # дедупликация (коммитится ботом)
├── requirements.txt
└── README.md
```

---

## Добавить новый канал

1. Добавь канал в `src/fetcher.py` → `FEEDS` или `YOUTUBE_CHANNELS`
2. Добавь описание в `src/filter.py` → `CHANNEL_DESCRIPTIONS`
3. Добавь маппинг в `src/poster.py` → `CHANNEL_WEBHOOKS`
4. Добавь Secret в GitHub Settings
5. Добавь кнопку фильтра в `docs/index.html`

---

## Переменные окружения (никогда не в коде)

| Переменная                | Описание                          |
|---------------------------|-----------------------------------|
| `GEMINI_API_KEY`          | Gemini API для AI-фильтрации      |
| `YOUTUBE_API_KEY`         | YouTube Data API v3               |
| `TEAMS_WEBHOOK_*`         | Incoming Webhook URL для каждого канала |

Все хранятся в **GitHub Secrets** и передаются в Actions через `env:`.
