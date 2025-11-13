
import curses
import requests
import json
import sys
import time
import os
import random
import textwrap
import copy
import re

# --- Combat Constants ---
CRIT_CHANCE = 15 # Percentage chance for a critical hit
MISS_CHANCE = 10 # Percentage chance for a miss
from datetime import datetime

# --- Logging ---
def log_to_file(filename, content):
    """Appends content to a specified log file with a timestamp."""
    try:
        with open(filename, 'a', encoding='utf-8') as f:
            f.write(f"--- {datetime.now()} ---\n")
            f.write(content)
            f.write("\n\n")
    except IOError as e:
        print(f"ERROR: Could not write to log file {filename}: {e}", file=sys.stderr)

def dump_game_state_to_file(game_state):
    """Dumps the current game_state to a JSON file for inspection."""
    dump_filename = "ui_dump.json"
    try:
        # Use a custom default function for json.dumps to handle non-serializable objects
        def default_serializer(obj):
            if isinstance(obj, set):
                return list(obj)
            raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

        with open(dump_filename, 'w', encoding='utf-8') as f:
            json.dump(game_state, f, indent=2, default=default_serializer)
        log_to_file("gamestate_log.txt", f"Game state dumped to {dump_filename}")
    except IOError as e:
        log_to_file("gamestate_log.txt", f"ERROR: Could not dump game state to file: {e}")
    except TypeError as e:
        log_to_file("gamestate_log.txt", f"ERROR: Game state contains non-serializable objects: {e}")

# --- Game Logic ---
def roll_dice(sides):
    """Rolls a dice with a given number of sides."""
    return random.randint(1, sides)

def handle_combat(player_stats, monster):
    """
    Handles a round of combat, calculating damage and XP, including misses and critical hits.
    Returns a string summarizing the combat round.
    """
    summary = []
    player_name = "You" # Assuming player's name for narrative

    log_to_file("gamestate_log.txt", f"COMBAT START - Player HP: {player_stats['hp']}, Monster HP: {monster['hp']}")

    # Player's turn
    player_roll = random.randint(1, 100)
    if player_roll <= MISS_CHANCE:
        summary.append(f"{player_name} attacked the {monster['name']} but missed!")
    else:
        player_damage = random.randint(2, player_stats['attack_dice'])
        log_to_file("gamestate_log.txt", f"Player attack: {player_name} rolled {player_roll}, base damage {player_damage}.")
        if player_roll >= 100 - CRIT_CHANCE: # Critical hit
            player_damage *= 2
            monster['hp'] -= player_damage
            summary.append(f"{player_name} critically hit the {monster['name']} for {player_damage} damage!")
        else:
            monster['hp'] -= player_damage
            summary.append(f"{player_name} hit the {monster['name']} for {player_damage} damage.")
        log_to_file("gamestate_log.txt", f"Monster HP after player attack: {monster['hp']}")

    if monster['hp'] <= 0:
        xp_gain = monster.get('max_hp', 10) # Use max_hp as base XP
        player_stats['xp'] += xp_gain
        summary.append(f"The {monster['name']} is defeated! {player_name} gained {xp_gain} score.")
    else:
        # Monster's turn (only if not defeated)
        monster_roll = random.randint(1, 100)
        if monster_roll <= MISS_CHANCE:
            summary.append(f"The {monster['name']} attacked {player_name} but missed!")
        else:
            monster_damage = random.randint(1, monster['attack_dice'])
            log_to_file("gamestate_log.txt", f"Monster attack: {monster['name']} rolled {monster_roll}, base damage {monster_damage}.")
            if monster_roll >= 100 - CRIT_CHANCE: # Critical hit
                monster_damage *= 2
                player_stats['hp'] -= monster_damage
                summary.append(f"The {monster['name']} critically hit {player_name} for {monster_damage} damage!")
            else:
                player_stats['hp'] -= monster_damage
                summary.append(f"The {monster['name']} hit {player_name} for {monster_damage} damage.")
        log_to_file("gamestate_log.txt", f"Player HP after monster attack: {player_stats['hp']}")

    log_to_file("gamestate_log.txt", f"COMBAT END - Player HP: {player_stats['hp']}, Monster HP: {monster['hp']}")
    return " ".join(summary)

def handle_player_action(action, game_state):
    """Processes the player's action, calling the LLM and updating the game state."""
    log_to_file("gamestate_log.txt", f"Player action: {action}")

    # Handle combat actions
    action_lower = action.lower()
    
    if game_state.get('current_monster'):
        # If in combat, assume most actions are attacks unless explicitly fleeing or using a non-attack item
        if "flee" in action_lower:
            # Handle fleeing (not implemented yet, but would go here)
            prompt = f"The player attempted to '{action}'. Narrate the attempt to flee. Provide choices for success/failure."
            response_json = get_llm_response(game_state, prompt)
        elif "use health potion" in action_lower:
            # Handle using health potion (not implemented yet, but would go here)
            # For now, let LLM narrate, but eventually client should handle
            prompt = f"The player attempted to '{action}'. Narrate the use of a health potion. Provide choices for next move."
            response_json = get_llm_response(game_state, prompt)
        else:
            # Default to attack if in combat and not fleeing/using specific item
            monster = game_state['current_monster']
            combat_summary = handle_combat(game_state['player_stats'], monster) # This updates HP

            # Check for monster death
            if monster['hp'] <= 0:
                xp_gain = monster['max_hp']
                monster_name = monster['name']
                game_state['player_stats']['xp'] += xp_gain
                game_state['current_monster'] = None
                
                prompt = f"The player has defeated the {monster_name}! {combat_summary}. Narrate this victory and describe the scene now that the threat is gone. Provide new choices for exploration."
                response_json = get_llm_response(game_state, prompt)
            else:
                # Monster is still alive, provide a detailed update to the LLM
                prompt = f"The player's action was to '{action}'. {combat_summary}. Narrate this moment in the battle and give the player choices for their next move (e.g., attack again, try to flee, use an item)."
                response_json = get_llm_response(game_state, prompt)
    else:
        # Not in combat, normal action
        response_json = get_llm_response(game_state, action)

    # Update game state from LLM response
    if "type" in response_json:
        game_state['current_event'] = response_json
        game_state['current_choices'] = response_json.get('choices', [])

        # If the LLM introduces a monster, create it in the game state
        if "monster_key" in response_json and game_state.get('current_monster') is None:
            monster_data = game_state['monster_db'].get(response_json["monster_key"])
            if monster_data:
                # Use deepcopy to ensure we don't modify the monster_db template
                game_state['current_monster'] = copy.deepcopy(monster_data)
                log_to_file("gamestate_log.txt", f"Monster '{response_json['monster_key']}' created.")
        # Process loot from LLM response
        if "loot" in response_json and isinstance(response_json["loot"], list):
            for item in response_json["loot"]:
                game_state['player_stats']['inventory'].append(item)
                log_to_file("gamestate_log.txt", f"Player received loot: {item}")
    else:
        # Handle cases where the LLM response is not structured as expected
        fallback_description = "An unexpected event occurred. The path forward is unclear."
        game_state['current_event'] = {'title': '???', 'description': response_json.get('description', fallback_description)}
        game_state['current_choices'] = []

    log_to_file("gamestate_log.txt", json.dumps(game_state, indent=2, default=lambda o: '<not serializable>'))
    return True

# --- LLM & Prompting ---
def get_game_master_prompt():
    return """
You are a JSON-only fantasy RPG Game Master. You MUST **ALWAYS** respond with a valid JSON object, and **ONLY** a JSON object. Do not include any conversational text outside the JSON.
The user's message will contain the current game state and a summary of the player's last action.
Your job is to narrate the result of that action in a compelling way.

**CRITICAL INSTRUCTIONS:**
1.  **Use the Game State:** The user will provide a `[GAME_STATE]` block containing a JSON object. Parse this JSON object to understand the current game state and use this data to inform your narration.
2.  **Narrate Combat:** For combat turns, the `[ACTION]` block will describe the mechanical results (damage dealt, etc.). Your `description` MUST be a creative narration of these events.
3.  **Introduce Monsters:** To introduce a new monster, you MUST include a `monster_key` as a TOP-LEVEL KEY in your JSON response. Available keys are: "goblin", "hobgoblin", "orc", "troll", "ogre". When the player enters a dangerous area or performs an action that should logically lead to combat, you MUST introduce a monster.
4.  **Ongoing Combat:** If a `current_monster` is present in the `[GAME_STATE]`, you are in combat. Narrate the ongoing battle, reflecting the damage dealt and received. Continue to provide combat-relevant choices (e.g., "Attack again", "Try to flee", "Use item"). Do NOT introduce a new `monster_key` if a monster is already present.
5.  **Combat Conclusion:** When a monster is defeated (its HP drops to 0 or below), the `[ACTION]` block will indicate this. Narrate the monster's defeat and the end of combat. Crucially, do NOT include a `monster_key` in your JSON response when a monster is defeated, as the game system will handle its removal. Provide choices for post-combat actions (e.g., "Loot the body", "Explore further"). If the player finds loot, include it as per instruction 6.
6.  **Loot:** When the player discovers items (e.g., after defeating a monster, searching a chest, finding a hidden stash), you MUST include a `loot` key as a TOP-LEVEL KEY in your JSON response. The value of `loot` MUST be a JSON array of strings, where each string is the name of an item. For example: `"loot": ["Gold Coin", "Rusty Sword"]`. The game system will automatically add these items to the player's inventory. **IMPORTANT:** If you include a `loot` array in your JSON response, DO NOT include choices such as "Pick up X" or "Take Y", as the items are automatically added. Instead, provide choices for subsequent actions (e.g., "Continue exploring", "Examine the area").

**EXAMPLE OF A COMPLETE JSON RESPONSE:**
```json
{
 "type": "narrative",
 "title": "Forest Clearing",
 "description": "You emerge into a small clearing, sunlight dappling through the leaves. A defeated goblin lies at your feet, and a shimmering potion catches your eye.",
 "choices": ["Examine the potion", "Continue deeper into the forest"],
 "monster_key": null,
 "loot": ["Healing Potion"]
}
```

EXAMPLE OF INTRODUCING A MONSTER IN COMBAT:
- USER MESSAGE:
[GAME_STATE]
Player: HP 20/20, Score: 0, Inventory: []
[ACTION]
Player action: Attack the shadowy figure.

- YOUR JSON RESPONSE:
```json
{
 "type": "narrative",
 "title": "Ambush!",
 "description": "As you lunge forward, the shadowy figure solidifies into a snarling goblin! It parries your attack and lunges back, its eyes glinting with malice.",
 "monster_key": "goblin",
 "choices": ["Attack the goblin", "Try to flee", "Use Health Potion"]
}
```

EXAMPLE OF NARRATING A COMBAT ACTION:
- USER MESSAGE:
[GAME_STATE]
Player: HP 15/20, Inv: []
Monster: Goblin, HP 4
[ACTION]
You hit the goblin for 6 damage. The goblin is defeated. You gain 10 score.

- YOUR JSON RESPONSE:
```json
{
 "type": "narrative",
 "title": "Victory!",
 "description": "With a final, desperate swing, you strike the goblin down. It collapses in a heap, and you feel a surge of accomplishment.",
 "choices": ["Search the body", "Venture deeper into the cave"]
}
```

EXAMPLE OF INTRODUCING A MONSTER:
- USER MESSAGE:
[GAME_STATE]
Player: HP 20/20, Inv: []
[ACTION]
Player action: Enter the spooky forest.

- YOUR JSON RESPONSE:
```json
{
 "type": "narrative",
 "title": "Ambush!",
 "description": "As you step over a gnarled root, a hulking shape detaches from the shadows, its tusks gleaming in the dim light. An orc blocks your path!",
 "monster_key": "orc",
 "choices": ["Attack the orc", "Stand your ground", "Try to flee"]
}
```
Your first task is to describe the starting area. The user will provide the first message.
3.  **Ongoing Combat:** If a `current_monster` is present in the `[GAME_STATE]`, you are in combat. Narrate the ongoing battle, reflecting the damage dealt and received. Continue to provide combat-relevant choices (e.g., "Attack again", "Try to flee", "Use item"). Do NOT introduce a new `monster_key` if a monster is already present.
4.  **Combat Conclusion:** When a monster is defeated (its HP drops to 0 or below), the `[ACTION]` block will indicate this. Narrate the monster's defeat and the end of combat. Crucially, do NOT include a `monster_key` in your JSON response when a monster is defeated, as the game system will handle its removal. Provide choices for post-combat actions (e.g., "Loot the body", "Explore further").
"""

def format_game_state_for_llm(game_state):
    """Formats the current game state into a JSON string for the LLM."""
    formatted_state = {
        "player_stats": {
            "hp": game_state['player_stats']['hp'],
            "max_hp": game_state['player_stats']['max_hp'],
            "xp": game_state['player_stats']['xp'],
            "level": game_state['player_stats']['level'],
            "inventory": game_state['player_stats']['inventory']
        },
        "current_location": game_state['current_event'].get('title', 'Unknown Location'),
        "current_choices": game_state['current_choices']
    }

    if game_state.get('current_monster'):
        formatted_state["current_monster"] = {
            "name": game_state['current_monster']['name'],
            "hp": game_state['current_monster']['hp'],
            "max_hp": game_state['current_monster']['max_hp'],
            "attack_dice": game_state['current_monster']['attack_dice']
        }
    
    # Wrap the JSON in the [GAME_STATE] tags as before
    return f"[GAME_STATE]\n{json.dumps(formatted_state, indent=2)}\n[/GAME_STATE]"

def get_llm_response(game_state, new_user_message=None, json_mode=True):
    if new_user_message:
        # For the main game, append to chat history
        if json_mode:
            formatted_state = format_game_state_for_llm(game_state)
            full_user_message = f"{formatted_state}\n[ACTION]\n{new_user_message}"
            game_state['chat_history'].append({'role': 'user', 'content': full_user_message})
            system_prompt = get_game_master_prompt()
            messages = [{'role': 'system', 'content': system_prompt}] + game_state['chat_history']
        # For the intro, create a temporary message list
        else:
            messages = [{'role': 'system', 'content': new_user_message}]

    payload = {"model": game_state['llm_config']['model'], "messages": messages, "max_tokens": 8000, "temperature": 0.9}
    
    log_to_file("llm_log.txt", f"REQUEST (json_mode={json_mode}):\n{json.dumps(payload, indent=2)}")

    fallback_json = {"type": "narrative", "title": "Error", "description": "The world shimmers... (LLM returned invalid JSON)", "choices": ["Continue..."]}

    try:
        response = requests.post(f"{game_state['llm_config']['url']}/v1/chat/completions", headers={"Content-Type": "application/json", "Authorization": f"Bearer {game_state['llm_config']['api_key']}"}, data=json.dumps(payload), timeout=45)
        response.raise_for_status()
        llm_message = response.json()['choices'][0]['message']['content']
        log_to_file("llm_log.txt", f"RAW RESPONSE:\n{llm_message}")
        
        if not json_mode:
            return llm_message

        # Use regex to find the JSON object, making it more robust to extra text
        json_match = re.search(r'```json\s*(\{.*\})\s*```', llm_message, re.DOTALL)
        if not json_match:
            json_match = re.search(r'(\{.*\})', llm_message, re.DOTALL)

        parsed_json = None
        # Attempt to find JSON object
        json_match = re.search(r'```json\s*(\{.*\})\s*```', llm_message, re.DOTALL)
        if not json_match:
            json_match = re.search(r'(\{.*\})', llm_message, re.DOTALL)

        if json_match:
            json_str = json_match.group(1)
            try:
                parsed_json = json.loads(json_str)
            except json.JSONDecodeError as e:
                log_to_file("llm_log.txt", f"JSON DECODE ERROR: {e}\nAttempted to parse:\n{json_str}")
                # Fallback to plain text parsing if JSON is malformed
                pass # parsed_json remains None

        if parsed_json:
            game_state['chat_history'].append({'role': 'assistant', 'content': parsed_json.get('description', '')})
            log_to_file("llm_log.txt", f"PARSED JSON:\n{json.dumps(parsed_json, indent=2)}")
            return parsed_json
        else:
            # Fallback: LLM did not return valid JSON, attempt to parse plain text
            log_to_file("llm_log.txt", f"NO VALID JSON OBJECT FOUND in LLM response. Attempting plain text parsing:\n{llm_message}")
            
            # Extract narrative (the whole message)
            narrative_description = llm_message.strip()
            
            # Extract choices using regex for numbered lists
            choices = []
            choice_matches = re.findall(r'^\s*(?:\d+\.|\-)\s*(.*)', llm_message, re.MULTILINE)
            for choice in choice_matches:
                choices.append(choice.strip())

            fallback_json = {
                "type": "narrative",
                "title": "Narrative Event", # Generic title
                "description": narrative_description,
                "choices": choices if choices else ["Continue..."] # Provide a default choice if none found
            }
            game_state['chat_history'].append({'role': 'assistant', 'content': fallback_json.get('description', '')})
            log_to_file("llm_log.txt", f"FALLBACK PARSED JSON (from plain text):\n{json.dumps(fallback_json, indent=2)}")
            return fallback_json

    except (requests.exceptions.RequestException, KeyError) as e:
        log_to_file("llm_log.txt", f"ERROR:\n{e}")
        if json_mode:
            fallback_json["description"] = f"The world shimmers... (Error: {e})"
            return fallback_json
        else:
            return f"The world shimmers... an error occurred: {e}"

def show_splash_screen(stdscr):
    """Displays the splash screen."""
    h, w = stdscr.getmaxyx()
    curses.curs_set(0)
    stdscr.clear()
    
    GREEN, RED, YELLOW, CYAN, WHITE = curses.color_pair(1), curses.color_pair(2), curses.color_pair(3), curses.color_pair(4), curses.color_pair(5)

    try:
        # Construct path relative to the script's location
        script_dir = os.path.dirname(__file__)
        splash_file_path = os.path.join(script_dir, 'splash.txt')
        with open(splash_file_path, 'r', encoding='utf-8') as f:
            splash_art = f.read()
    except (IOError, FileNotFoundError):
        splash_art = "Procedural Terminal Game"

    art_lines = splash_art.split('\n')
    art_height = len(art_lines)
    art_width = max(len(line) for line in art_lines) if art_lines else 0
    
    start_y = (h - art_height - 4) // 2
    start_x = (w - art_width) // 2

    for i, line in enumerate(art_lines):
        stdscr.addstr(start_y + i, start_x, line, CYAN)

    author_text = "A game by John and Gemini"
    title_text = "Procedural Terminal Game"
    stdscr.addstr(start_y + art_height + 1, (w - len(title_text)) // 2, title_text, YELLOW)
    stdscr.addstr(start_y + art_height + 2, (w - len(author_text)) // 2, author_text, YELLOW)
    
    prompt_text = "Press any key to continue..."
    stdscr.addstr(h - 2, (w - len(prompt_text)) // 2, prompt_text, WHITE)
    
    stdscr.refresh()
    stdscr.getch()

def show_intro_screen(stdscr, config):
    """Displays the comedic intro screen."""
    h, w = stdscr.getmaxyx()
    curses.curs_set(0)
    stdscr.clear()
    
    YELLOW, WHITE = curses.color_pair(3), curses.color_pair(5)

    stdscr.box()
    stdscr.addstr(1, (w - len("A Message From The Void")) // 2, "A Message From The Void", YELLOW)

    intro_prompt = "You are a slightly unhinged game narrator. Your task is to write a short, funny, and dramatic welcome message for a procedural text-based RPG. The key feature of the game is that the player can ignore the suggested choices and type whatever they want. Your message should encourage this creative freedom in a humorous way. Respond with a single paragraph of text, not JSON."
    
    # A temporary game_state is needed for the LLM call
    temp_game_state = {'llm_config': config}
    
    stdscr.addstr(3, 2, "The void whispers...", YELLOW)
    stdscr.refresh()

    intro_text = get_llm_response(temp_game_state, intro_prompt, json_mode=False)
    log_to_file("llm_log.txt", f"RAW INTRO TEXT:\n{intro_text}")
    
    sanitized_intro = sanitize_for_curses(intro_text)
    log_to_file("llm_log.txt", f"SANITIZED INTRO TEXT:\n{sanitized_intro}")

    wrapped_text = textwrap.wrap(sanitized_intro, w - 6)
    for i, line in enumerate(wrapped_text):
        if i + 3 < h - 5:
            stdscr.addstr(i + 3, 3, line, WHITE)

    instruction_y = min(len(wrapped_text) + 5, h - 5)
    stdscr.addstr(instruction_y, 3, "IMPORTANT:", YELLOW)
    stdscr.addstr(instruction_y + 1, 3, "If you don't like the choices, make one up and type it!", WHITE)
    stdscr.addstr(instruction_y + 2, 3, "The Game Master will react to whatever you do.", WHITE)

    prompt_text = "Press any key to begin your adventure..."
    stdscr.addstr(h - 2, (w - len(prompt_text)) // 2, prompt_text)
    
    stdscr.refresh()
    stdscr.getch()

# --- UI Rendering ---
def sanitize_for_curses(text):
    """Removes non-ASCII characters that would cause curses to crash."""
    return text.encode("ascii", "ignore").decode()

def sanitize_for_curses(text):
    """Removes non-ASCII characters that would cause curses to crash."""
    return text.encode("ascii", "ignore").decode()

# --- UI Rendering ---
def draw_ui(stdscr, win_art, win_stats, win_narrative, win_input, game_state, input_str, is_loading=False):
    h, w = stdscr.getmaxyx()
    stdscr.clear()
    for win in [win_art, win_stats, win_narrative, win_input]: win.clear()

    GREEN, RED, YELLOW, CYAN, WHITE = curses.color_pair(1), curses.color_pair(2), curses.color_pair(3), curses.color_pair(4), curses.color_pair(5)

    # Draw boxes and titles for all windows except the art window
    for win, title in [(win_stats, "Stats"), (win_narrative, "Narrative"), (win_input, "Input")]:
        win.box()
        stdscr.addstr(win.getbegyx()[0] - 1, win.getbegyx()[1], f" {title} ", YELLOW)
    win_art.box() # Draw art window box without a title

    # Art Window
    if game_state.get('current_monster'):
        art = game_state['current_monster'].get('ascii_art', '')
        # DO NOT SANITIZE ART - it's meant to be raw.
        for i, line in enumerate(art.splitlines()):
            if i < win_art.getmaxyx()[0] - 2:
                win_art.addstr(i + 1, 2, line, RED)

    # Stats Window
    player = game_state['player_stats']
    win_stats.addstr(1, 2, f"Player: {sanitize_for_curses(game_state['player_name'])}", GREEN)
    win_stats.addstr(2, 2, f"HP: {player['hp']}/{player['max_hp']} | Score: {player['xp']}", GREEN)
    inv_str = ", ".join(player['inventory']) if player['inventory'] else "Empty"
    win_stats.addstr(3, 2, f"Inventory: {sanitize_for_curses(inv_str)}", WHITE)
    if game_state.get('current_monster'):
        monster = game_state['current_monster']
        win_stats.addstr(5, 2, f"Monster: {sanitize_for_curses(monster.get('name', 'Unknown'))}", RED)
        win_stats.addstr(6, 2, f"HP: {monster.get('hp', '??')}", RED)

    # Narrative Window
    narrative_h, narrative_w = win_narrative.getmaxyx()
    usable_height = narrative_h - 2 #-2 for border
    
    event = game_state.get('current_event', {})
    win_narrative.addstr(1, 2, sanitize_for_curses(event.get('title', '...')), CYAN)
    
    choices = game_state.get('current_choices', [])
    num_choices = len(choices)
    
    # Dynamically allocate space
    # Reserve lines for choices + 1 blank line separator
    choice_space = num_choices + 1 
    max_desc_lines = usable_height - choice_space - 1 # -1 for title
    
    description_lines = textwrap.wrap(sanitize_for_curses(event.get('description', '')), narrative_w - 4)
    for i, line in enumerate(description_lines):
        if i < max_desc_lines:
            win_narrative.addstr(i + 2, 2, line, WHITE)
    
    choice_start_y = min(2 + max_desc_lines, usable_height - num_choices)
    for i, choice in enumerate(choices):
        if choice_start_y + i < narrative_h -1:
             win_narrative.addstr(choice_start_y + i, 3, f"{i+1}. {sanitize_for_curses(choice)}", YELLOW)

    # Input Window
    win_input.addstr(1, 2, f"> {sanitize_for_curses(input_str)}")

    # Loading Indicator
    if is_loading:
        loading_msg = "Awaiting response..."
        win_narrative.addstr(narrative_h - 2, narrative_w - len(loading_msg) - 2, loading_msg, YELLOW)

    for win in [stdscr, win_art, win_stats, win_narrative, win_input]: win.refresh()

def load_monsters():
    """Loads the monster database from monsters.json."""
    try:
        script_dir = os.path.dirname(__file__)
        monster_file_path = os.path.join(script_dir, 'monsters.json')
        with open(monster_file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError, FileNotFoundError):
        return {"error": {"name": "MissingNo.", "hp": 99, "attack_dice": 99, "xp": 0, "ascii_art": "???"}}

# --- Main Game Loop ---
def main_game_loop(stdscr, config):
    curses.curs_set(1)
    stdscr.nodelay(True) # Non-blocking getch
    
    # Initial window setup
    h, w = stdscr.getmaxyx()
    win_art = curses.newwin(h - 17, (w // 2) - 2, 1, (w // 2) + 1)
    win_stats = curses.newwin(h - 17, (w // 2) - 2, 1, 1)
    win_narrative = curses.newwin(12, w - 2, h - 15, 1)
    win_input = curses.newwin(3, w - 2, h - 3, 1)
    windows = [win_art, win_stats, win_narrative, win_input]

    game_state = {
        'player_name': config['name'], 'llm_config': config, 'chat_history': [],
        'player_stats': {'hp': 20, 'max_hp': 20, 'attack_dice': 6, 'xp': 0, 'level': 1, 'inventory': ["Health Potion"]},
        'current_event': {}, 'current_choices': [], 'current_monster': None,
        'monster_db': load_monsters()
    }

    # Initial world generation
    response_json = get_llm_response(game_state, "The adventure begins. Describe the starting area.")
    game_state.update({
        'current_event': response_json,
        'current_choices': response_json.get('choices', []),
    })
    if "monster_key" in response_json:
        monster_data = game_state['monster_db'].get(response_json["monster_key"])
        if monster_data:
            game_state['current_monster'] = copy.deepcopy(monster_data) # Now deepcopy

    log_to_file("gamestate_log.txt", json.dumps(game_state, indent=2, default=str)) # Log initial state

    input_str = ""
    needs_redraw = True
    while True:
        if needs_redraw:
            draw_ui(stdscr, win_art, win_stats, win_narrative, win_input, game_state, input_str)
            win_input.move(1, 3 + len(sanitize_for_curses(input_str)))
            needs_redraw = False

        key = stdscr.getch() # Use getch instead of getkey for resize handling

        if key != -1:
            needs_redraw = True
            if key == curses.KEY_RESIZE:
                check_size(stdscr)
                h, w = stdscr.getmaxyx()
                # Recreate windows with new dimensions
                win_art = curses.newwin(h - 17, (w // 2) - 2, 1, (w // 2) + 1)
                win_stats = curses.newwin(h - 17, (w // 2) - 2, 1, 1)
                win_narrative = curses.newwin(12, w - 2, h - 15, 1)
                win_input = curses.newwin(3, w - 2, h - 3, 1)
                windows = [win_art, win_stats, win_narrative, win_input]
                stdscr.clear() # Clear the whole screen to avoid artifacts
            
            elif key == curses.KEY_F1:
                dump_game_state_to_file(game_state)
                # Optionally, display a message to the user that the state was dumped
                # For now, just log it.
            elif key in (curses.KEY_ENTER, 10, 13):
                if input_str.lower() == "quit": break
                if not input_str: continue
                
                action_text = input_str
                if input_str.isdigit():
                    choice_index = int(input_str) - 1
                    if 0 <= choice_index < len(game_state['current_choices']):
                        action_text = game_state['current_choices'][choice_index]
                
                draw_ui(stdscr, win_art, win_stats, win_narrative, win_input, game_state, input_str, is_loading=True)
                handle_player_action(action_text, game_state)
                log_to_file("gamestate_log.txt", json.dumps(game_state, indent=2, default=str)) # Log state after action
                input_str = ""
            elif key in (curses.KEY_BACKSPACE, '\b', '\x7f'):
                input_str = input_str[:-1]
            else:
                try:
                    input_str += chr(key)
                except ValueError:
                    pass # Ignore non-character keys

        if game_state['player_stats']['hp'] <= 0:
            game_state['current_event'] = {"title": "You Died", "description": "Your adventure ends here.", "choices": []}
            draw_ui(stdscr, win_art, win_stats, win_narrative, win_input, game_state, "")
            time.sleep(5)
            break
        
        time.sleep(0.02)

# --- Config & Main ---
CONFIG_FILE = "config.json"
def get_default_config(): return {"name": "Adventurer", "url": "http://127.0.0.1:11434", "model": "llama3:8b", "api_key": "ollama"}
def load_config():
    if not os.path.exists(CONFIG_FILE): return get_default_config()
    try:
        with open(CONFIG_FILE, 'r') as f: config = json.load(f)
        defaults = get_default_config()
        for key, value in defaults.items():
            if key not in config: config[key] = value
        return config
    except (json.JSONDecodeError, IOError): return get_default_config()
def save_config(config):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4)
    except IOError:
        pass

def run_setup_screen(stdscr, defaults):
    try:
        curses.curs_set(1); stdscr.clear(); h, w = stdscr.getmaxyx()
        if h < 24 or w < 80: raise curses.error("Terminal too small.")
        prompts = [("Character Name", "name"), ("LLM Base URL", "url"), ("LLM Model Name", "model"), ("API Key", "api_key")]
        config = defaults.copy()
        y = 2; stdscr.addstr(y, 2, "--- Game Setup ---"); y += 2
        stdscr.addstr(y, 2, "Press Enter to accept the current value."); y += 2
        curses.echo()
        for prompt_text, config_key in prompts:
            default_value = defaults.get(config_key, "")
            prompt_str = f"{prompt_text} [{sanitize_for_curses(default_value)}]: "
            if len(prompt_str) >= w - 3: prompt_str = prompt_str[:w - 4] + "..."
            stdscr.addstr(y, 2, prompt_str); stdscr.refresh()
            user_input = stdscr.getstr(y, 2 + len(prompt_str)).decode('utf-8').strip()
            config[config_key] = user_input if user_input else default_value
            stdscr.addstr(y + 1, 2, " " * (w - 3)); stdscr.addstr(y + 1, 2, f"Set to: {sanitize_for_curses(config[config_key])}")
            y += 3
        curses.noecho(); stdscr.clear(); stdscr.addstr(2, 2, "Config saved..."); stdscr.refresh(); time.sleep(1.5)
        return config
    except curses.error:
        stdscr.clear(); stdscr.addstr(0, 0, "Terminal too small. Min size: 80x24."); stdscr.refresh(); time.sleep(4)
        return None

def check_size(stdscr):
    """Checks if terminal is large enough, otherwise waits."""
    MIN_H, MIN_W = 24, 80
    h, w = stdscr.getmaxyx()
    while h < MIN_H or w < MIN_W:
        stdscr.clear()
        msg = "Terminal too small!"
        msg2 = f"Please resize to at least {MIN_W}x{MIN_H} (current: {w}x{h})"
        stdscr.addstr(0, 0, msg)
        stdscr.addstr(1, 0, msg2)
        stdscr.refresh()
        key = stdscr.getch()
        if key == curses.KEY_RESIZE:
            h, w = stdscr.getmaxyx()

def main(stdscr):
    """Main function wrapped by curses."""
    # Initial terminal size check
    check_size(stdscr)

    for log_file in ["llm_log.txt", "gamestate_log.txt"]:
        try: os.remove(log_file)
        except OSError: pass

    try:
        curses.start_color(); curses.use_default_colors()
        for i, color in enumerate([curses.COLOR_GREEN, curses.COLOR_RED, curses.COLOR_YELLOW, curses.COLOR_CYAN, curses.COLOR_WHITE]):
            curses.init_pair(i + 1, color, -1)
        
        config = load_config()
        # Setup screen also needs size check
        check_size(stdscr)
        final_config = run_setup_screen(stdscr, config)
        
        if final_config:
            save_config(final_config)
            check_size(stdscr) # Check again after setup
            show_splash_screen(stdscr)
            check_size(stdscr) # And after splash
            show_intro_screen(stdscr, final_config)
            main_game_loop(stdscr, final_config)

    except Exception as e:
        curses.endwin()
        print(f"An unexpected error occurred: {e}")
        # traceback.print_exc() # Uncomment for debugging


if __name__ == "__main__":
    try: curses.wrapper(main)
    except curses.error as e: print(f"Error initializing curses: {e}")
    except KeyboardInterrupt: print("Game exited.")
