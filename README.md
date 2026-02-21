# Forge

Autonomous coding pipeline controlled via Telegram. You describe what to build in a roadmap, Forge figures out how to build it, reviews its own work, and waits for your approval before committing.

## How It Works

1. You write a `ROADMAP.md` with steps like `- [ ] Step 2.3: Build momentum composite scoring module`
2. You message `/next` on Telegram
3. Forge shows you the step and waits for "go"
4. A coding model (Sonnet / Gemini) reads your memory bank, figures out the implementation, writes code + tests
5. Pre-commit hooks run (ruff, mypy, pytest)
6. Junior reviewer (DeepSeek, with full codebase read access) checks for bugs and correctness
7. Senior reviewer (Sonnet, with full codebase read access) does deep review: security, design, integration
8. You get a summary on Telegram. Reply "commit" or "stop"

If anything fails, the pipeline loops: coder fixes → reviewer re-checks. If the junior loop exhausts, senior provides guidance. If everything fails, you get notified with details.

## Project Structure

```
src/
├── src/
│   ├── __init__.py
│   ├── __main__.py      # Entry point
│   ├── config.py        # Config loader
│   ├── bot.py           # Telegram bot interface
│   ├── pipeline.py      # Main orchestrator
│   ├── aider_client.py  # Aider subprocess wrapper
│   ├── memory.py        # Memory bank manager
│   └── reviewers.py     # Two-tier review system
├── config.yaml          # Pipeline configuration
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## Memory Bank

Forge maintains five files in your project's `memory/` directory:

| File | Purpose | Who reads it |
|------|---------|-------------|
| `ARCHITECTURE.md` | Current system design, components, schemas | Coder |
| `ROADMAP.md` | Step checklist | Pipeline (to find next step) |
| `DECISIONS.md` | Why things are the way they are | Coder |
| `PROGRESS.md` | Running log of completed work | Coder |
| `CHANGELOG.md` | Human-readable summary | You only |

After each successful step, a cheap model (DeepSeek) updates the relevant memory files based on what changed.

## Setup

### 1. Create a Telegram Bot

Message [@BotFather](https://t.me/BotFather) on Telegram:
- `/newbot` → name it whatever you want
- Save the bot token

Get your chat ID by messaging [@userinfobot](https://t.me/userinfobot).

### 2. Get API Keys

You need keys for whatever models you configure:
- **Anthropic** (for Sonnet): https://console.anthropic.com
- **DeepSeek**: https://platform.deepseek.com
- **Google** (for Gemini, if using): https://aistudio.google.com

### 3. Configure

Create a `.env` file:

```bash
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
ANTHROPIC_API_KEY=sk-ant-...
DEEPSEEK_API_KEY=sk-...
# GOOGLE_API_KEY=...  # if using Gemini
```

Edit `config.yaml` to point to your project and choose your models.

### 4. Prepare Your Project

Your project repo needs:
- A `memory/` directory (Forge creates templates on first run)
- A `memory/ROADMAP.md` with steps in checkbox format

Example ROADMAP.md:
```markdown
# Roadmap

## Phase 1: Core Infrastructure
- [ ] Step 1.1: Set up project skeleton with src/ and tests/ directories
- [ ] Step 1.2: Build data ingestion pipeline for Tiingo API
- [ ] Step 1.3: Implement database schema and storage layer

## Phase 2: Analysis
- [ ] Step 2.1: Build momentum indicators module
- [ ] Step 2.2: Build mean reversion signals
- [ ] Step 2.3: Build momentum composite scoring module
```

### 5. Deploy

**Local:**
```bash
pip install -r requirements.txt
python -m src
```

**Docker (Oracle Cloud ARM):**
```bash
docker compose up -d
```

## Telegram Commands

| Command | What it does |
|---------|-------------|
| `/next` | Show next unchecked step, ask for confirmation |
| `/status` | Show pipeline state, current step, models |
| `/skip` | Skip current step |
| `/reset` | Discard all uncommitted changes |

### During Execution

| Reply | When | What it does |
|-------|------|-------------|
| `go` | After `/next` shows a step | Start execution |
| `commit` | After step succeeds | Commit + update memory bank |
| `retry` | After step fails | Re-run the same step |
| `skip` | After step fails | Discard changes, move on |
| `stop` | Anytime | Discard all changes, go idle |

## CLI Usage

You can control Forge from your terminal with the same commands as Telegram:

```bash
python -m src status   # Show current state and next step
python -m src next     # Show next step, then run it interactively
python -m src skip     # Skip the current queued step
python -m src reset    # Discard all uncommitted changes
```

When `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set, the CLI will also
send status updates to your Telegram chat so you know what's happening even
when you triggered the run from the terminal.

**Interactive flow** for `python -m src next`:
1. The next roadmap step is displayed
2. Type `go` to start the pipeline, or `skip` to skip
3. On success, type `commit` to save or `stop` to discard
4. On failure, type `retry`, `skip`, or `stop`

## Docker Usage

The easiest way to interact with Forge locally is to use Docker.

**1. Running an interactive shell**
Open a shell inside the Docker container to manually run `python` commands, scripts, or use `pip`:

```bash
# Build the image first (only needed when you change requirements or Dockerfile)
docker compose build forge

# Open an interactive bash shell inside the container
docker compose run --rm forge bash
```

**2. Running your test suite**
Run all `pytest` unit tests with coverage using the dedicated profile:

```bash
docker compose --profile test up --build forge-test
```

> **Do not** run `pytest` directly on your host machine — the Docker test image ensures
> the correct Python version, dependencies, and complete environment isolation.

**3. Running a single one-off command**
Execute a single python command or script and have the container exit immediately afterwards:

```bash
docker compose run --rm forge python <your_script.py>
```

**4. Running the main application**
Start the main application as defined in the Dockerfile (`python -m src`):

```bash
docker compose up --build forge
```
*(Add `-d` to the end if you want it to run quietly in the background!)*

## Cost Estimates

Per step (assuming Sonnet coder, DeepSeek junior, Sonnet senior):

| Scenario | Cost |
|----------|------|
| Happy path (1 junior + 1 senior) | $0.50 - $2.00 |
| Unhappy path (3 junior loops + senior guidance + retry) | $1.50 - $4.00 |
| 40 steps realistic mix | $40 - $80 |

If using Gemini 3.1 Pro as coder (cheaper), costs drop significantly on the coder side.

## Configuration Reference

See `config.yaml` for all options. Key settings:

- `models.coder`: Primary coding model. Needs to be strong enough to figure out implementation from a one-line description.
- `models.coder_fallback`: Used if primary fails completely.
- `pipeline.max_hook_retries`: How many times to re-run coder when pre-commit hooks fail (default: 3).
- `pipeline.max_junior_retries`: Junior review loop limit (default: 3).
- `pipeline.max_senior_rounds`: Senior escalation rounds when junior loop exhausts (default: 2).
- `pipeline.aider_timeout`: Max seconds per Aider invocation (default: 900 = 15 min).
