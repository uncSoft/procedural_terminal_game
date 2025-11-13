# Project Summary: Procedural Terminal RPG

This document summarizes the development status of the procedural terminal-based RPG as of 2025-11-13.

## 1. Project Overview

The project is a terminal-based RPG written in Python. It uses the `curses` library to create a multi-window graphical interface in the terminal. A state-aware Large Language Model (LLM) acts as the game master, providing narrative descriptions and responding to player actions, while the Python client manages all game mechanics and state.

## 2. Core Technologies & Files

-   **Language:** Python 3.9
-   **UI:** `curses` library for terminal UI.
-   **LLM Interaction:** `requests` library to call an OpenAI-compatible API.
-   **Main Files:**
    -   `main.py`: The core application logic, including the game loop, UI drawing, and state management.
    -   `monsters.json`: A client-side JSON database containing stats and ASCII art for all monsters.
    -   `config.json`: Stores user configuration like player name and LLM API details.
    -   `splash.txt`: Contains the ASCII art for the game's splash screen.
    -   `gamestate_log.txt` / `llm_log.txt`: Log files used for debugging.

## 3. Architecture & Key Logic

The game operates on a main loop (`main_game_loop`) that processes user input, updates the game state, and redraws the UI.

-   **State Management:** The entire game's state is held in a single Python dictionary called `game_state`. This object is passed to most functions.
-   **UI (`draw_ui`):** The screen is divided into four `curses` windows:
    1.  **Art Window:** Displays ASCII art of the current monster.
    2.  **Stats Window:** Shows player and monster HP, player score, and inventory.
    3.  **Narrative Window:** Displays the LLM's descriptions and story text.
    4.  **Input Window:** Where the user types their actions.
-   **Combat Mechanics (`handle_combat`):** All mechanical aspects of combat are handled exclusively by the Python client in this function. It calculates player and monster damage, and updates their HP in the `game_state`. This function is the source of truth for combat outcomes.
-   **LLM Synchronization (`handle_player_action`):** This is the most critical function for game flow.
    -   When the player attacks, the client first calls `handle_combat` to determine the mechanical outcome.
    -   The client then checks if the monster's HP is <= 0.
    -   **If the monster is defeated:** The client awards the score, removes the monster from the `game_state`, and sends a specific "victory" prompt to the LLM.
    -   **If the monster survives:** The client sends a detailed prompt to the LLM that includes the mechanical results (e.g., "You did 5 damage, the monster has 10 HP left.").
    -   This ensures the LLM's narration is always synchronized with the client-side game state.

## 4. Recent Accomplishments (Current Session)

-   **Combat System Overhaul:** Fixed a major bug where player attacks did no damage and monster HP did not decrease. All combat mechanics are now functional.
-   **Score (XP) System Fixed:** The player is now correctly awarded a "Score" value equal to the monster's `max_hp` upon defeating it.
-   **ASCII Art Fixed:** Resolved a bug that prevented multi-line ASCII art from `monsters.json` from being displayed. The fix involved changing `art.split('\n')` to the more robust `art.splitlines()` in the `draw_ui` function.
-   **LLM State Synchronization:** Fixed a critical bug where the LLM would prematurely narrate a monster's death. The system now provides the LLM with the mechanical results of each combat turn, ensuring the narrative and the game state are always aligned.
-   **Robust Testing:** Implemented a temporary `test_combat.py` script to reliably test and verify the combat and scoring logic without needing to run the full interactive game.
-   **Pathing Fixes:** Corrected file path issues for loading `monsters.json` and `splash.txt`, making the game runnable from any directory.

## 5. Current State

The core gameplay loop is functional. The player can start the game, encounter a monster spawned by the LLM, engage in combat with functional mechanics, see the monster's ASCII art, defeat the monster, and be awarded the correct score. The game is in a stable and playable state.

## 6. Future Considerations

-   The `monsters.json` file contains several monsters ("hobgoblin", "orc", "troll", "ogre") with placeholder ASCII art that needs to be updated.
-   The game could be expanded with more items, player abilities, or non-combat encounters.
-   The LLM prompts could be further refined to encourage more varied gameplay.
