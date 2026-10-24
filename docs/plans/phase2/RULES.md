# Rules for every build agent (breaking these harms the owner)

> Written for the parallel build agents of 2026-10-24. The worktree and no-commit rules below belonged to that build;
> now the work is done in the main checkout, one workstream at a time, committing as it goes. The rest still holds
> (scratch scripts isolate PTG_HOME, offline only, re-sign data, match the surrounding code).

- WORK ONLY IN YOUR WORKTREE (the path in your prompt). Use absolute paths under it for every Read/Edit/Write. Never
  edit the main checkout /Users/johnt/Developer/procedural_terminal_game (you may READ its docs/plans/phase2/layout_spike.py).
- NO git commit, NO git push, NO branch switching, NO `git stash`, NO `git reset`/`checkout` of files you didn't change.
  `git add -A` (staging) is used to mark finished work, as your prompt says.
- Python: `cd <worktree> && uv run --frozen python ...` and `uv run --frozen pytest ...`. NEVER `uv sync` (the
  worktree's .venv is already synced with the extras). macOS has no `timeout` command; the full suite takes ~4 min:
  run it with `uv run --frozen pytest -q -x -p no:cacheprovider` in the background or with a long tool timeout.
- Any scratch script that imports ptg MUST set os.environ["PTG_HOME"] = tempfile.mkdtemp() and PTG_SOUND=0 first, and
  live under the scratch folder in your prompt, not in the repo. Never touch ~/.ptg. Offline only
  (Config(backend="offline") or a fake LLM); never contact LM Studio or Anthropic.
- After changing anything in src/ptg/data/ (TOML, sprites, story), re-sign: `uv run --frozen python -m ptg.integrity --sign`.
- Match the code around you: its comment density, naming, docstrings in the game's plain voice ("what it is / does"),
  120-column lines, no new dependencies. Read README.md for the design. Keep the engine/narrator split: the engine
  owns the facts, the model only words.
- Every fix gets a regression test where one is practical; update tests that encoded old behaviour. Leave the whole
  suite passing (tests/). If something can't be done, say so plainly in your report — don't fake it.
- Kids made many monsters/items in the Maker; their silliness is intentional. Copyright-safe content only.
