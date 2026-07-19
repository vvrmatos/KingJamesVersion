"""Bible trivia — endless KJV study run with top-5 scores.

Functional curses game. Palette matches vim gruvbox dark/medium.
"""

from __future__ import annotations

import curses
import json
import os
import random
import textwrap
import time
from pathlib import Path

from questions import BANK

# ---------------------------------------------------------------------------
# Gruvbox dark / medium (cterm indices from ~/.vim/colors/gruvbox.vim)
# ---------------------------------------------------------------------------
GB_BG = 235
GB_FG = 223
GB_GRAY = 245
GB_RED = 167
GB_GREEN = 142
GB_YELLOW = 214
GB_BLUE = 109
GB_PURPLE = 175
GB_AQUA = 108
GB_ORANGE = 208

P_NORMAL, P_TITLE, P_SELECT, P_OK, P_BAD, P_DIM, P_ORANGE, P_FRAME = range(1, 9)
P_AQUA, P_PURPLE, P_CUR, P_SAFE, P_BG = range(9, 14)

DIFF_LABELS = ("Easy", "Medium", "Hard", "Mixed")
# Mixed = random from all tiers; points still follow each question's own tier
POINTS_PER_TIER = (1, 2, 3, 2)
TOP_N = 5
NAME_LEN = 4
SCORES_PATH = Path(os.environ.get("BIBLE_TRIVIA_SCORES", Path.home() / ".bible_trivia_scores.json"))
CONFIG_PATH = Path(os.environ.get("BIBLE_TRIVIA_CONFIG", Path.home() / ".bible_trivia_config.json"))

DEFAULT_CONFIG = {
    "lifeline": True,
    "flash": True,
    "default_name": "P 1",
}

# Arcade letter grid: 4 rows × 7 (last row has DEL / END)
LETTER_GRID = (
    ("A", "B", "C", "D", "E", "F", "G"),
    ("H", "I", "J", "K", "L", "M", "N"),
    ("O", "P", "Q", "R", "S", "T", "U"),
    ("V", "W", "X", "Y", "Z", "DEL", "END"),
)

def pool_for_mode(bank, mode):
    """Indices eligible for a difficulty mode. Mixed = entire bank."""
    if mode == 3:  # Mixed
        return list(range(len(bank)))
    return [i for i, q in enumerate(bank) if q[6] == mode]


def draw_question(bank, used, mode):
    """Pick a random unused question for the mode; reshuffle when exhausted."""
    eligible = pool_for_mode(bank, mode)
    pool = [i for i in eligible if i not in used]
    if not pool:
        used.clear()
        pool = list(eligible)
    return random.choice(pool)


def shuffle_options(q):
    """Return a copy of the question with A–D order randomized."""
    prompt, options, answer, ref, verse, category, tier = q
    opts = list(options)
    correct = opts[answer]
    random.shuffle(opts)
    return (prompt, tuple(opts), opts.index(correct), ref, verse, category, tier)


def q_tier(bank, i):
    return bank[i][6]


# ---------------------------------------------------------------------------
# Scores
# ---------------------------------------------------------------------------

def load_scores():
    try:
        data = json.loads(SCORES_PATH.read_text())
        if isinstance(data, list):
            return [(e["name"], int(e["score"]), e.get("diff", "")) for e in data]
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        pass
    return []


def save_scores(entries):
    payload = [{"name": n, "score": s, "diff": d} for n, s, d in entries[:TOP_N]]
    try:
        SCORES_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    except OSError:
        pass


def record_score(name, score, diff):
    entries = load_scores()
    entries.append((name, score, diff))
    entries.sort(key=lambda e: e[1], reverse=True)
    entries = entries[:TOP_N]
    save_scores(entries)
    return entries


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        data = json.loads(CONFIG_PATH.read_text())
        if isinstance(data, dict):
            for k in DEFAULT_CONFIG:
                if k in data:
                    cfg[k] = data[k]
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return cfg


def save_config(cfg):
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Color / draw
# ---------------------------------------------------------------------------

def init_colors():
    curses.start_color()
    try:
        curses.use_default_colors()
    except curses.error:
        pass
    curses.init_pair(P_NORMAL, GB_FG, GB_BG)
    curses.init_pair(P_TITLE, GB_YELLOW, GB_BG)
    curses.init_pair(P_SELECT, GB_BG, GB_YELLOW)
    curses.init_pair(P_OK, GB_GREEN, GB_BG)
    curses.init_pair(P_BAD, GB_RED, GB_BG)
    curses.init_pair(P_DIM, GB_GRAY, GB_BG)
    curses.init_pair(P_ORANGE, GB_ORANGE, GB_BG)
    curses.init_pair(P_FRAME, GB_BLUE, GB_BG)
    curses.init_pair(P_AQUA, GB_AQUA, GB_BG)
    curses.init_pair(P_PURPLE, GB_PURPLE, GB_BG)
    curses.init_pair(P_CUR, GB_BG, GB_ORANGE)
    curses.init_pair(P_SAFE, GB_AQUA, GB_BG)
    curses.init_pair(P_BG, GB_FG, GB_BG)


def pair(n):
    return curses.color_pair(n)


def setup(stdscr):
    curses.curs_set(0)
    stdscr.keypad(True)
    stdscr.timeout(-1)
    if curses.has_colors():
        init_colors()
        try:
            stdscr.bkgd(" ", pair(P_BG))
        except curses.error:
            pass
    stdscr.clear()
    stdscr.refresh()


def add(stdscr, y, x, text, attr=0):
    h, w = stdscr.getmaxyx()
    if y < 0 or y >= h or x >= w or x < 0:
        return
    try:
        stdscr.addstr(y, x, text[: max(0, w - x - 1)], attr)
    except curses.error:
        pass


def center(stdscr, y, text, attr=0):
    _, w = stdscr.getmaxyx()
    add(stdscr, y, max(0, (w - len(text)) // 2), text, attr)


def paint_bg(stdscr):
    stdscr.erase()
    try:
        stdscr.bkgd(" ", pair(P_BG))
    except curses.error:
        pass


def draw_frame(stdscr, top, left, height, width, title=""):
    attr = pair(P_FRAME)
    bottom = top + height - 1
    right = left + width - 1
    try:
        for x in range(left + 1, right):
            stdscr.addch(top, x, curses.ACS_HLINE, attr)
            stdscr.addch(bottom, x, curses.ACS_HLINE, attr)
        for y in range(top + 1, bottom):
            stdscr.addch(y, left, curses.ACS_VLINE, attr)
            stdscr.addch(y, right, curses.ACS_VLINE, attr)
        stdscr.addch(top, left, curses.ACS_ULCORNER, attr)
        stdscr.addch(top, right, curses.ACS_URCORNER, attr)
        stdscr.addch(bottom, left, curses.ACS_LLCORNER, attr)
        stdscr.addch(bottom, right, curses.ACS_LRCORNER, attr)
        if title:
            add(stdscr, top, left + 2, f" {title} ", pair(P_ORANGE) | curses.A_BOLD)
    except curses.error:
        pass


def layout(stdscr):
    return stdscr.getmaxyx()


def wrap_lines(text, width):
    return textwrap.wrap(text, width=max(10, width)) or [""]


# ---------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------

def draw_sidebar(stdscr, top, left, score, streak, mode, q_tier):
    add(stdscr, top, left, " RUN ", pair(P_ORANGE) | curses.A_BOLD)
    add(stdscr, top + 2, left, f"Score  {score}", pair(P_TITLE) | curses.A_BOLD)
    add(stdscr, top + 3, left, f"Streak {streak}", pair(P_AQUA))
    add(stdscr, top + 5, left, "Mode", pair(P_DIM))
    add(stdscr, top + 6, left, f"▸ {DIFF_LABELS[mode]}", pair(P_CUR) | curses.A_BOLD)
    if mode == 3:
        add(stdscr, top + 8, left, f"This Q: {DIFF_LABELS[q_tier]}", pair(P_AQUA))
        add(stdscr, top + 9, left, f"+{POINTS_PER_TIER[q_tier]} pts", pair(P_DIM))
    else:
        add(stdscr, top + 8, left, f"+{POINTS_PER_TIER[mode]} pts", pair(P_DIM))


def draw_top5(stdscr, y, scores=None):
    scores = scores if scores is not None else load_scores()
    center(stdscr, y, "TOP 5", pair(P_ORANGE) | curses.A_BOLD)
    if not scores:
        center(stdscr, y + 1, "(no scores yet)", pair(P_DIM))
        return
    for i, (name, score, diff) in enumerate(scores[:TOP_N]):
        line = f"{i + 1}. {name:<4}  {score:>4}   {diff}"
        center(stdscr, y + 1 + i, line, pair(P_NORMAL))


def title_screen(stdscr):
    options = ("Play", "Study desk", "Configs", "Quit")
    selected = 0
    while True:
        paint_bg(stdscr)
        h, _w = layout(stdscr)
        center(stdscr, 2, "BIBLE  TRIVIA", pair(P_TITLE) | curses.A_BOLD)
        center(stdscr, 3, "Endless run — pick difficulty, random questions", pair(P_DIM))
        draw_top5(stdscr, 5)
        base = 12
        for i, opt in enumerate(options):
            attr = pair(P_SELECT) | curses.A_BOLD if i == selected else pair(P_NORMAL)
            center(stdscr, base + i, f"  {opt}  ", attr)
        center(stdscr, h - 2, "↑↓ Enter  ·  R refs in-run  ·  S stop & save", pair(P_DIM))
        stdscr.refresh()
        key = stdscr.getch()
        if key in (curses.KEY_UP, ord("k")):
            selected = (selected - 1) % len(options)
        elif key in (curses.KEY_DOWN, ord("j")):
            selected = (selected + 1) % len(options)
        elif key in (curses.KEY_ENTER, 10, 13):
            return options[selected]
        elif key in (27, ord("q")):
            return "Quit"


def difficulty_screen(stdscr):
    """Choose Easy / Medium / Hard / Mixed. Returns mode index, or None if cancel."""
    selected = 0
    hints = (
        "Familiar passages · 1 pt each",
        "Deeper study · 2 pts each",
        "Harder texts · 3 pts each",
        "Random from all tiers · pts by question",
    )
    while True:
        paint_bg(stdscr)
        h, _w = layout(stdscr)
        center(stdscr, h // 2 - 6, "DIFFICULTY", pair(P_TITLE) | curses.A_BOLD)
        center(stdscr, h // 2 - 5, "Questions are drawn at random", pair(P_DIM))
        for i, label in enumerate(DIFF_LABELS):
            attr = pair(P_SELECT) | curses.A_BOLD if i == selected else pair(P_NORMAL)
            center(stdscr, h // 2 - 2 + i, f"  {label}  ", attr)
        center(stdscr, h // 2 + 4, hints[selected], pair(P_AQUA))
        center(stdscr, h - 2, "↑↓ Enter  ·  q back", pair(P_DIM))
        stdscr.refresh()
        key = stdscr.getch()
        if key in (curses.KEY_UP, ord("k")):
            selected = (selected - 1) % len(DIFF_LABELS)
        elif key in (curses.KEY_DOWN, ord("j")):
            selected = (selected + 1) % len(DIFF_LABELS)
        elif key in (curses.KEY_ENTER, 10, 13):
            return selected
        elif key in (27, ord("q")):
            return None


def configs_screen(stdscr, cfg):
    """Toggle settings. Penultimate title option. Mutates and saves cfg."""
    items = (
        ("lifeline", "50/50 lifeline"),
        ("flash", "Correct flash"),
        ("clear_scores", "Clear top 5 scores"),
        ("back", "Back"),
    )
    selected = 0
    note = ""
    while True:
        paint_bg(stdscr)
        h, _w = layout(stdscr)
        center(stdscr, 3, "CONFIGS", pair(P_TITLE) | curses.A_BOLD)
        center(stdscr, 4, "Enter toggles  ·  q back", pair(P_DIM))
        for i, (key, label) in enumerate(items):
            if key in ("clear_scores", "back"):
                value = ""
            else:
                value = "ON " if cfg.get(key) else "OFF"
            line = f"{label:<22} {value}"
            attr = pair(P_SELECT) | curses.A_BOLD if i == selected else pair(P_NORMAL)
            center(stdscr, 7 + i, f"  {line}  ", attr)
        if note:
            center(stdscr, 14, note, pair(P_AQUA))
        center(stdscr, h - 2, f"saved → {CONFIG_PATH.name}", pair(P_DIM))
        stdscr.refresh()
        key = stdscr.getch()
        if key in (curses.KEY_UP, ord("k")):
            selected = (selected - 1) % len(items)
            note = ""
        elif key in (curses.KEY_DOWN, ord("j")):
            selected = (selected + 1) % len(items)
            note = ""
        elif key in (curses.KEY_ENTER, 10, 13, ord(" ")):
            item_key = items[selected][0]
            if item_key == "back":
                save_config(cfg)
                return
            if item_key == "clear_scores":
                save_scores([])
                note = "Top 5 cleared"
            else:
                cfg[item_key] = not bool(cfg.get(item_key))
                save_config(cfg)
                note = f"{items[selected][1]} → {'ON' if cfg[item_key] else 'OFF'}"
        elif key in (27, ord("q")):
            save_config(cfg)
            return


def study_desk(stdscr, log, subtitle="Study desk — references from this run"):
    if not log:
        log = [(
            "—",
            "No references yet",
            "Answer or miss to collect study refs here.",
            "",
        )]
    idx = 0
    while True:
        paint_bg(stdscr)
        h, w = layout(stdscr)
        box_w = min(76, w - 4)
        box_h = min(20, h - 2)
        top = max(0, (h - box_h) // 2)
        left = max(0, (w - box_w) // 2)
        draw_frame(stdscr, top, left, box_h, box_w, "STUDY DESK")
        center(stdscr, top + 1, subtitle, pair(P_DIM))
        ref, prompt, verse, note = log[idx]
        add(stdscr, top + 3, left + 2, f"[{idx + 1}/{len(log)}]  {ref}", pair(P_ORANGE) | curses.A_BOLD)
        py = top + 5
        for line in wrap_lines(prompt, box_w - 4)[:2]:
            add(stdscr, py, left + 2, line, pair(P_TITLE))
            py += 1
        py += 1
        for line in wrap_lines(verse, box_w - 4)[:8]:
            add(stdscr, py, left + 2, line, pair(P_NORMAL))
            py += 1
        if note:
            py += 1
            for line in wrap_lines(note, box_w - 4)[:2]:
                add(stdscr, py, left + 2, line, pair(P_AQUA))
                py += 1
        center(stdscr, top + box_h - 2, "← → browse   q return", pair(P_DIM))
        stdscr.refresh()
        key = stdscr.getch()
        if key in (curses.KEY_LEFT, ord("h")):
            idx = (idx - 1) % len(log)
        elif key in (curses.KEY_RIGHT, ord("l")):
            idx = (idx + 1) % len(log)
        elif key in (27, ord("q"), 10, 13):
            return


def show_miss(stdscr, q, score, log):
    prompt, options, answer, ref, verse, category, _tier = q
    paint_bg(stdscr)
    h, w = layout(stdscr)
    box_w = min(76, w - 4)
    box_h = min(18, h - 2)
    top = max(0, (h - box_h) // 2)
    left = max(0, (w - box_w) // 2)
    draw_frame(stdscr, top, left, box_h, box_w, "MISS")
    center(stdscr, top + 2, "Incorrect", pair(P_BAD) | curses.A_BOLD)
    center(stdscr, top + 3, f"Score this run: {score}", pair(P_AQUA))
    add(stdscr, top + 5, left + 2, f"Answer: {options[answer]}", pair(P_OK))
    add(stdscr, top + 6, left + 2, f"Read: {ref}  ({category})", pair(P_ORANGE) | curses.A_BOLD)
    py = top + 8
    for line in wrap_lines(verse, box_w - 4)[:6]:
        add(stdscr, py, left + 2, line, pair(P_NORMAL))
        py += 1
    center(stdscr, top + box_h - 2, "Enter name entry  ·  R study desk", pair(P_DIM))
    stdscr.refresh()
    while True:
        key = stdscr.getch()
        if key == ord("r"):
            study_desk(stdscr, log, "Study after a miss — q returns here")
            # redraw
            paint_bg(stdscr)
            draw_frame(stdscr, top, left, box_h, box_w, "MISS")
            center(stdscr, top + 2, "Incorrect", pair(P_BAD) | curses.A_BOLD)
            center(stdscr, top + 3, f"Score this run: {score}", pair(P_AQUA))
            add(stdscr, top + 5, left + 2, f"Answer: {options[answer]}", pair(P_OK))
            add(stdscr, top + 6, left + 2, f"Read: {ref}  ({category})", pair(P_ORANGE) | curses.A_BOLD)
            py = top + 8
            for line in wrap_lines(verse, box_w - 4)[:6]:
                add(stdscr, py, left + 2, line, pair(P_NORMAL))
                py += 1
            center(stdscr, top + box_h - 2, "Enter name entry  ·  R study desk", pair(P_DIM))
            stdscr.refresh()
        elif key in (10, 13, 27, ord("q")):
            return


def name_entry(stdscr, score, diff_label, default_name="P 1"):
    """Arcade A–Z grid. Empty + END → default_name. Returns final name."""
    chars = []
    row = col = 0
    while True:
        paint_bg(stdscr)
        h, w = layout(stdscr)
        center(stdscr, 2, "PLAYER 1", pair(P_AQUA) | curses.A_BOLD)
        center(stdscr, 3, "WINNER" if score > 0 else "RUN OVER", pair(P_TITLE) | curses.A_BOLD)
        center(stdscr, 5, f"SCORE  {score}    {diff_label}", pair(P_ORANGE))

        grid_top = 7
        cell_w = 5
        grid_w = 7 * cell_w
        grid_left = max(0, (w - grid_w) // 2)
        for r, row_cells in enumerate(LETTER_GRID):
            for c, cell in enumerate(row_cells):
                x = grid_left + c * cell_w
                y = grid_top + r * 2
                label = f"{cell:^3}"
                if r == row and c == col:
                    add(stdscr, y, x, f"[{label.strip():^3}]", pair(P_CUR) | curses.A_BOLD)
                else:
                    add(stdscr, y, x, f" {label.strip():^3} ", pair(P_NORMAL))

        # name slots
        slots = []
        for i in range(NAME_LEN):
            slots.append(chars[i] if i < len(chars) else "_")
        center(stdscr, grid_top + 10, "  ".join(slots), pair(P_TITLE) | curses.A_BOLD)
        center(stdscr, grid_top + 12, f"↑↓←→ move  Enter pick  ·  empty END → {default_name}", pair(P_DIM))
        stdscr.refresh()

        key = stdscr.getch()
        if key == curses.KEY_UP:
            row = (row - 1) % 4
        elif key == curses.KEY_DOWN:
            row = (row + 1) % 4
        elif key == curses.KEY_LEFT:
            col = (col - 1) % 7
        elif key == curses.KEY_RIGHT:
            col = (col + 1) % 7
        elif key in (curses.KEY_ENTER, 10, 13, ord(" ")):
            cell = LETTER_GRID[row][col]
            if cell == "DEL":
                if chars:
                    chars.pop()
            elif cell == "END":
                name = "".join(chars).strip()
                return name if name else default_name
            elif len(chars) < NAME_LEN:
                chars.append(cell)
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            if chars:
                chars.pop()
        elif ord("a") <= key <= ord("z") or ord("A") <= key <= ord("Z"):
            if len(chars) < NAME_LEN:
                chars.append(chr(key).upper())
        elif key == 27:
            return default_name


def fifty_fifty(options, answer):
    wrong = [i for i in range(len(options)) if i != answer]
    kill = set(random.sample(wrong, 2))
    return [i for i in range(len(options)) if i not in kill]


def ask_one(stdscr, qnum, score, streak, mode, q, log, lifeline_left):
    prompt, options, answer, ref, verse, category, q_tier = q
    selected = 0
    visible = list(range(4))
    while True:
        paint_bg(stdscr)
        h, w = layout(stdscr)
        main_w = min(58, w - 18)
        main_h = min(18, h - 2)
        top = max(1, (h - main_h) // 2)
        left = 2
        draw_frame(stdscr, top, left, main_h, main_w, f"Q{qnum}  {category}")
        draw_sidebar(stdscr, top, left + main_w + 2, score, streak, mode, q_tier)

        pts = POINTS_PER_TIER[q_tier]
        add(stdscr, top + 1, left + 2, f"{DIFF_LABELS[q_tier]}  ·  +{pts}", pair(P_TITLE) | curses.A_BOLD)
        py = top + 3
        for line in wrap_lines(prompt, main_w - 4)[:4]:
            add(stdscr, py, left + 2, line, pair(P_NORMAL))
            py += 1
        py += 1
        labels = "ABCD"
        for vi, oi in enumerate(visible):
            line = (f"{labels[oi]}) " + options[oi])[: main_w - 6]
            attr = pair(P_SELECT) | curses.A_BOLD if oi == selected else pair(P_NORMAL)
            mark = "▸ " if oi == selected else "  "
            add(stdscr, py + vi, left + 3, mark + line, attr)

        help_bits = ["↑↓/A-D", "Enter", "S stop", "R refs"]
        if lifeline_left:
            help_bits.insert(2, "F 50/50")
        center(stdscr, top + main_h - 1, " · ".join(help_bits), pair(P_DIM))
        stdscr.refresh()

        key = stdscr.getch()
        if key in (curses.KEY_UP, ord("k")):
            pos = visible.index(selected) if selected in visible else 0
            selected = visible[(pos - 1) % len(visible)]
        elif key in (curses.KEY_DOWN, ord("j")):
            pos = visible.index(selected) if selected in visible else 0
            selected = visible[(pos + 1) % len(visible)]
        elif key in (ord("a"), ord("A"), ord("1")) and 0 in visible:
            selected = 0
        elif key in (ord("b"), ord("B"), ord("2")) and 1 in visible:
            selected = 1
        elif key in (ord("c"), ord("C"), ord("3")) and 2 in visible:
            selected = 2
        elif key in (ord("d"), ord("D"), ord("4")) and 3 in visible:
            selected = 3
        elif key in (curses.KEY_ENTER, 10, 13):
            return ("ok" if selected == answer else "miss"), lifeline_left
        elif key in (ord("s"), ord("S")):
            return "stop", lifeline_left
        elif key in (ord("r"), ord("R")):
            study_desk(stdscr, log)
        elif key in (ord("f"), ord("F")) and lifeline_left and len(visible) == 4:
            visible = fifty_fifty(options, answer)
            if selected not in visible:
                selected = visible[0]
            lifeline_left = False
        elif key in (27, ord("q")):
            return "quit", lifeline_left


def finish_run(stdscr, score, mode, log, reason, cfg):
    """Name entry → save top 5 → show board. reason: miss|stop|quit."""
    if reason == "quit" and score == 0:
        return
    diff = DIFF_LABELS[mode]
    default_name = str(cfg.get("default_name") or "P 1")
    name = name_entry(stdscr, score, diff, default_name)
    entries = record_score(name, score, diff)
    paint_bg(stdscr)
    h, _w = layout(stdscr)
    center(stdscr, 3, f"{name}  ·  {score} pts", pair(P_TITLE) | curses.A_BOLD)
    draw_top5(stdscr, 6, entries)
    center(stdscr, h - 3, "Enter title  ·  R study desk", pair(P_DIM))
    stdscr.refresh()
    while True:
        key = stdscr.getch()
        if key == ord("r"):
            study_desk(stdscr, log)
            paint_bg(stdscr)
            center(stdscr, 3, f"{name}  ·  {score} pts", pair(P_TITLE) | curses.A_BOLD)
            draw_top5(stdscr, 6, entries)
            center(stdscr, h - 3, "Enter title  ·  R study desk", pair(P_DIM))
            stdscr.refresh()
        elif key in (10, 13, 27, ord("q")):
            return


def play_run(stdscr, session_log, cfg, mode):
    used = set()
    score = 0
    streak = 0
    lifeline = bool(cfg.get("lifeline", True))
    qnum = 0

    while True:
        qi = draw_question(BANK, used, mode)
        used.add(qi)
        q = shuffle_options(BANK[qi])
        prompt, _opts, _ans, ref, verse, category, q_tier = q
        qnum += 1

        status, lifeline = ask_one(stdscr, qnum, score, streak, mode, q, session_log, lifeline)

        if status == "quit":
            finish_run(stdscr, score, mode, session_log, "quit", cfg)
            return
        if status == "stop":
            finish_run(stdscr, score, mode, session_log, "stop", cfg)
            return
        if status == "miss":
            session_log.append((ref, prompt, verse, f"Missed · {category} · score {score}"))
            show_miss(stdscr, q, score, session_log)
            finish_run(stdscr, score, mode, session_log, "miss", cfg)
            return

        # correct — keep going forever
        gained = POINTS_PER_TIER[q_tier]
        score += gained
        streak += 1
        session_log.append((ref, prompt, verse, f"Correct · {category} · +{gained} (total {score})"))
        if cfg.get("flash", True):
            paint_bg(stdscr)
            center(stdscr, layout(stdscr)[0] // 2 - 1, "CORRECT", pair(P_OK) | curses.A_BOLD)
            center(stdscr, layout(stdscr)[0] // 2 + 1, f"+{gained}   score {score}", pair(P_AQUA))
            stdscr.refresh()
            time.sleep(0.4)


def game_loop(stdscr):
    setup(stdscr)
    session_log = []
    cfg = load_config()
    while True:
        choice = title_screen(stdscr)
        if choice == "Quit":
            return
        if choice == "Study desk":
            study_desk(stdscr, session_log)
            continue
        if choice == "Configs":
            configs_screen(stdscr, cfg)
            continue
        mode = difficulty_screen(stdscr)
        if mode is None:
            continue
        play_run(stdscr, session_log, cfg, mode)


def main():
    random.seed()
    curses.wrapper(game_loop)


if __name__ == "__main__":
    main()
