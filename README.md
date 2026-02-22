# Forge

Autonomous coding pipeline controlled via Telegram. You describe what to build in a roadmap, Forge figures out how to build it, reviews its own work, and waits for your approval before committing.

## How It Works

1. You write a `ROADMAP.md` with steps like `- [ ] Step 2.3: Build momentum composite scoring module`
2. You message `/next` on Telegram
3. Forge shows you the step and waits for "go"
4. A coding model (via LiteLLM, supporting any Anthropic, OpenAI, Google, or DeepSeek model) reads your memory bank, figures out the implementation, writes code + tests
5. Pre-commit hooks run (ruff, mypy, pytest)
6. Junior reviewer (DeepSeek, with full codebase read access) checks for bugs and correctness
7. Senior reviewer (Sonnet, with full codebase read access) does deep review: security, design, integration
8. You get a summary on Telegram. Reply "commit" or "stop"

If anything fails, the pipeline loops: coder fixes → reviewer re-checks. If the junior loop exhausts, senior provides guidance. If everything fails, you get notified with details.

## Project Structure

├── src/
│   ├── __init__.py
│   ├── __main__.py      # Entry point
│   ├── config.py        # Config loader
│   ├── prompts.py       # Prompt loading utility
│   ├── bot.py           # Telegram bot interface
│   ├── pipeline.py      # Main orchestrator
│   ├── aider_client.py  # Aider subprocess wrapper
│   ├── memory.py        # Memory bank manager
│   └── reviewers.py     # Two-tier review system
├── prompts/             # Agent Markdown Prompts
│   ├── coder.md
│   ├── junior_reviewer.md
│   ├── senior_guidance.md
│   ├── senior_reviewer.md
│   └── memory_updater.md
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
| `ROADMAP.md` | Step checklist (includes change notes) | Coder + Pipeline |
| `DECISIONS.md` | Why things are the way they are | Coder |

After each successful step, a cheap model (DeepSeek) updates the relevant memory files based on what changed.

## Prompt Customization

All the raw prompts given to the internal AI agents (such as the coder, junior reviewer, and senior reviewer) live in the `prompts/` directory as pure Markdown files.

You are encouraged to tweak these templates!
If you want the reviewer to look for specific patterns or the coder to adopt a specific communication style, simply edit the corresponding `.md` file in `prompts/`. No Python code changes are required.

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
FORGE_PROJECT_PATH=/absolute/path/to/your/project/on/host

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
- [x] Step 1.1: Set up project skeleton with src/ and tests/ directories
  > Added src/ layout, pyproject.toml, ruff + mypy hooks
- [x] Step 1.2: Build data ingestion pipeline for Tiingo API
  > Switched from httpx to aiohttp for streaming support
- [ ] Step 1.3: Implement database schema and storage layer

## Phase 2: Analysis
- [ ] Step 2.1: Build momentum indicators module
- [ ] Step 2.2: Build mean reversion signals
- [ ] Step 2.3: Build momentum composite scoring module
```

### 5. Build & Run

```bash
# First-time build (or after changing requirements / Dockerfile)
./forge build

# Start the bot in the background
./forge up

# Stop the bot
./forge down
```

## CLI Usage

The `forge` script wraps Docker so you never need to think about containers. All commands run inside Docker automatically.

| Command | What it does |
|---------|-------------|
| `./forge status` | Show pipeline state and next step |
| `./forge next` | Show next step, run it interactively |
| `./forge skip` | Skip the current step |
| `./forge reset` | Discard all uncommitted changes |
| `./forge test` | Run the full test suite with coverage |
| `./forge shell` | Open a bash shell inside the container |
| `./forge build` | Build / rebuild the Docker image |
| `./forge up` | Start the bot in the background |
| `./forge down` | Stop the bot |
| `./forge logs` | Tail the running bot logs |

> **Tip:** Add the project directory to your `PATH` to use `forge` from anywhere:
> ```bash
> export PATH="$PATH:/path/to/forge"
> ```

**Interactive flow** for `./forge next`:
1. The next roadmap step is displayed
2. Type `go` to start the pipeline, or `skip` to skip
3. On success, type `commit` to save or `stop` to discard
4. On code validation failure (e.g., hooks, tests), type `retry`, `skip`, or `stop`
5. On a fatal pipeline error (e.g., missing API key, aider crash), the pipeline immediately aborts and resets changes without asking.

When `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set, the CLI will also
send status updates to your Telegram chat.

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
| `retry` | After code validation fails | Re-run the same step |
| `skip` | After code validation fails | Discard code changes, move on |
| `stop` | Anytime | Discard all changes, go idle |

*(Note: If a fatal pipeline error occurs, such as a missing API key, the pipeline automatically aborts without prompting.)*

## Cost Estimates

Per step (assuming Sonnet coder, DeepSeek junior, Sonnet senior):

| Scenario | Cost |
|----------|------|
| Happy path (1 junior + 1 senior) | $0.50 - $2.00 |
| Unhappy path (3 junior loops + senior guidance + retry) | $1.50 - $4.00 |
| 40 steps realistic mix | $40 - $80 |

If using Gemini 3.1 Pro as coder (cheaper), costs drop significantly on the coder side.

## Configuration Reference

See `config.yaml` for all options. You can override any setting using `FORGE_*` environment variables in your `.env` file (e.g., `FORGE_MODEL_CODER=anthropic/claude-3-7-sonnet-20250219`).

**Models (LiteLLM Format)**
Because Forge uses **LiteLLM**, you are never locked into old models. When a new model is released, you don't need to wait for a code update—just change the `<provider>/<model-name>` string in your `.env` file to use it immediately.

- `models.coder`: Primary coding model. Needs to be strong enough to figure out implementation from a one-line description.
- `models.coder_fallback`: Used if primary fails completely.
- `pipeline.max_hook_retries`: How many times to re-run coder when pre-commit hooks fail (default: 3).
- `pipeline.max_junior_retries`: Junior review loop limit (default: 3).
- `pipeline.max_senior_rounds`: Senior escalation rounds when junior loop exhausts (default: 2).
- `pipeline.aider_timeout`: Max seconds per Aider invocation (default: 900 = 15 min).
