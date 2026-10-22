---
# Fires on the first descent after someone edits the game's own data files (see ptg/integrity.py).
# Editing the files is allowed. It's just noticed. Re-sign after real edits:
#   uv run python -m ptg.integrity --sign
id: hackerman
title: Hackerman (⌐■_■)
when: run_start
if: tampered
once: profile
voice: exact
secret: yes
hint: Some secrets aren't in the dungeon. They're in its files.
sprite: sunglasses
---
The dungeon blinks. Somewhere beneath the stone its numbers have been rewritten, and not by its
architects. It knows. It's a little impressed. This descent will be remembered as modded.
[secret] [mark hackerman]
