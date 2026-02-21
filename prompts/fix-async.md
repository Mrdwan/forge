# Fix: Remove unnecessary async from Forge pipeline

## Problem

`execute_step` in `pipeline.py` is async because `update_memory` in `memory.py` uses `litellm.acompletion`. But all the Aider subprocess calls are synchronous and blocking. The bot wraps this in `run_in_executor` with a nested `asyncio.run()` which is fragile and unnecessary.

The bot only processes one step at a time. There's no benefit to async here.

## What to change

1. In `forge/memory.py`: Change `update_memory` from `async def` to `def`. Replace `litellm.acompletion` with `litellm.completion` (the synchronous version). Remove the `await` on the completion call.

2. In `forge/pipeline.py`: Change `execute_step` from `async def` to `def`. Change `finalize_step` from `async def` to `def`. Change `abandon_step` from `async def` to `def`. Remove all `await` keywords on calls to these functions and to `update_memory`.

3. In `forge/bot.py`: Remove the `run_in_executor` + `asyncio.run` wrapper in `_execute`. Instead, run `execute_step(self.cfg)` directly in a thread using `asyncio.to_thread()` (which is the clean way to run sync code from an async context). Same for `finalize_step` in `_commit`. Remove the `_execute_async` helper function entirely.

The pattern in bot.py should become:
```python
result = await asyncio.to_thread(execute_step, self.cfg)
```

and in _commit:
```python
await asyncio.to_thread(finalize_step, self.cfg, self.current_result)
```

4. Remove `import asyncio` from pipeline.py if no longer needed.

## Do not change

- The Telegram bot handlers must stay async (python-telegram-bot requires this)
- The Aider subprocess wrapper stays synchronous (it's correct as-is)
- Config, reviewers, and aider_client modules don't need changes
