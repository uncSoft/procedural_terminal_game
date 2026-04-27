# Procedural Terminal RPG

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

-   **Git Repository Setup:** Assisted in configuring Git user information, setting up `git-credential-manager` using `wincred`, and successfully pushing the project to a remote GitHub repository.
-   **`copy` Module Import Fix:** Resolved a `NameError` by adding `import copy` to `main.py`, which was necessary for `copy.deepcopy` functionality.
-   **Enhanced Combat System:**
    -   Corrected the argument passing for the `handle_combat` function.
    -   Significantly improved the LLM's ability to initiate and manage combat sequences by refining the `get_game_master_prompt` with explicit instructions for monster introduction (including emphasizing `monster_key` as a top-level JSON key).
    -   Introduced `format_game_state_for_llm` to provide a structured game state to the LLM, ensuring better context awareness.
    -   Made the LLM response parsing more robust in `get_llm_response` using regular expressions to handle varied LLM output formats and improved error logging for JSON decoding issues.
    -   Simplified combat-related prompts in `handle_player_action` as the full game state is now passed separately.
    -   Implemented "misses" and "critical hits" mechanics for both player and monster attacks within `handle_combat`, adding more dynamic outcomes to battles.
    -   Added detailed logging within `handle_combat` to track player and monster HP changes, aiding in debugging and verifying state updates.
-   **Game State Debugging Tool:** Implemented a feature to dump the current `game_state` to a `ui_dump.json` file by pressing `F1`, providing a snapshot for troubleshooting.
-   **Updated Monster ASCII Art:** Replaced placeholder ASCII art for Hobgoblin, Orc, Troll, and Ogre in `monsters.json` with more detailed and appropriate representations.

## 5. Current State

The core gameplay loop is functional and significantly enhanced. The player can start the game, encounter monsters (now more reliably introduced by the LLM), engage in dynamic combat with misses and critical hits, see updated player and monster HP, defeat monsters, and be awarded score. The game's interaction with the LLM is more robust, with improved JSON parsing and clearer instructions for the LLM. A debugging tool is available to dump the game state. The game is in a stable and playable state, with improved combat mechanics and LLM synchronization.

## 6. Future Considerations

-   The `monsters.json` file contains several monsters ("hobgoblin", "orc", "troll", "ogre") with placeholder ASCII art that needs to be updated.
-   The game could be expanded with more items, player abilities, or non-combat encounters.
-   The LLM prompts could be further refined to encourage more varied gameplay.
