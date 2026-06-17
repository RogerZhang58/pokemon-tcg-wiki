"""
Pokemon TCG Wiki utilities: path management, SQLite FTS5 helpers,
string processing, language detection.
"""

import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Optional

# ── Paths ──────────────────────────────────────────────────────────
PROJECT_ROOT = Path(os.environ.get(
    "POKEMON_TCG_ROOT",
    Path(__file__).resolve().parents[1]
))

TOOLS_DIR = PROJECT_ROOT / "tools"
RAW_DIR = PROJECT_ROOT / "raw"
DATA_DIR = RAW_DIR / "data"
CARDS_DIR = DATA_DIR / "cards"           # TCGdex raw cards (EN metadata)
CARDS_ZH_DIR = DATA_DIR / "cards_zh"      # Merged ZH cards
SETS_DIR = DATA_DIR / "sets"
ZH_MOD_DIR = RAW_DIR / "zh_mod"           # PTCG Live zh-mod data (read-only)
ZH_MOD_DB_DIR = ZH_MOD_DIR / "databases_zh-CN"
ZH_MOD_TEXT_DIR = ZH_MOD_DIR / "text_zh-CN"
LLM_TRANS_DIR = RAW_DIR / "llm_trans"     # LLM translation outputs
RULES_DIR = RAW_DIR / "rules"
BANNED_DIR = RAW_DIR / "banned"
WIKI_DIR = PROJECT_ROOT / "wiki"
CACHE_DIR = TOOLS_DIR / "cache"

# Ensure directories exist
for d in [DATA_DIR, CARDS_DIR, CARDS_ZH_DIR, SETS_DIR,
          ZH_MOD_DIR, ZH_MOD_DB_DIR, ZH_MOD_TEXT_DIR,
          LLM_TRANS_DIR, RULES_DIR, BANNED_DIR, CACHE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── Database ───────────────────────────────────────────────────────
DB_PATH = DATA_DIR / "pokemon_tcg.db"


def get_db() -> sqlite3.Connection:
    """Get SQLite connection with FTS5 enabled."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ── FTS5 Index Tables ──────────────────────────────────────────────

CARDS_FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS cards_fts USING fts5(
    name_zh, name_ja, name_en,
    types, supertype, subtypes,
    attack_names, attack_texts,
    ability_names, ability_texts,
    set_name, rarity, artist,
    content='cards', content_rowid='rowid'
);
"""

CARDS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS cards (
    id TEXT PRIMARY KEY,
    data_json TEXT NOT NULL
);
"""

RULES_FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS rules_fts USING fts5(
    title, content, lang, section,
    content='rules', content_rowid='rowid'
);
"""

RULES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    lang TEXT NOT NULL,
    section TEXT,
    file_path TEXT
);
"""


def init_db() -> sqlite3.Connection:
    """Initialize database with FTS5 tables."""
    conn = get_db()
    conn.execute(CARDS_TABLE_SQL)
    conn.execute(CARDS_FTS_SQL)
    conn.execute(RULES_TABLE_SQL)
    conn.execute(RULES_FTS_SQL)
    conn.commit()
    return conn


# ── String Helpers ─────────────────────────────────────────────────

def normalize_name(name: str) -> str:
    """Lowercase, strip, preserve CJK for fuzzy matching."""
    if not name:
        return ""
    lowered = name.strip()
    # Keep a-z, 0-9, CJK (中日韩), Katakana (30A0-30FF), Hiragana (3040-309F)
    return re.sub(r"[^a-z0-9\u4e00-\u9fff\u30a0-\u30ff\u3040-\u309f]", "", lowered)


def detect_language(text: str) -> str:
    """Detect language: 'zh', 'ja', 'en' based on character distribution."""
    if not text.strip():
        return "en"
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    kana = len(re.findall(r"[\u3040-\u309f\u30a0-\u30ff]", text))
    total = len(text.strip())
    if cjk / total > 0.3:
        return "zh"
    if kana / total > 0.1:
        return "ja"
    return "en"


def levenshtein(a: str, b: str) -> int:
    """Compute Levenshtein distance."""
    if len(a) < len(b):
        return levenshtein(b, a)
    if len(b) == 0:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(
                curr[-1] + 1,
                prev[j + 1] + 1,
                prev[j] + (0 if ca == cb else 1)
            ))
        prev = curr
    return prev[-1]


# ── Card ID Normalization ──────────────────────────────────────────

def normalize_card_id(card_id: str, target_format: str = "tcgdex") -> str:
    """Convert between card ID formats.

    PTCG Live: swsh3_25 (underscore)
    TCGdex:    swsh3-25 (hyphen)
    """
    if target_format == "tcgdex":
        return card_id.replace("_", "-")
    elif target_format == "ptcgl":
        return card_id.replace("-", "_")
    return card_id


def parse_card_id(card_id: str) -> dict:
    """Parse a card ID into components.

    Examples:
        swsh3-25  → {set: 'swsh3', number: '25', sub: None}
        sv4-5_196 → {set: 'sv4', number: '196', sub: '5'}
    """
    # Normalize to underscore first, then parse
    normalized = card_id.replace("-", "_")
    parts = normalized.split("_")
    result = {"set": parts[0], "number": None, "sub": None}
    if len(parts) >= 2:
        # Check if middle part is a sub-set indicator (numeric after set prefix)
        if len(parts) > 2 and parts[1].isdigit() and len(parts[1]) <= 2:
            result["sub"] = parts[1]
            result["number"] = parts[-1]
        else:
            result["number"] = parts[-1]
    return result


# ── Energy Types ───────────────────────────────────────────────────

ENERGY_TYPES = [
    "Grass", "Fire", "Water", "Lightning", "Psychic",
    "Fighting", "Darkness", "Metal", "Fairy", "Dragon", "Colorless"
]

ENERGY_ZH = {
    "Grass": "草",
    "Fire": "火",
    "Water": "水",
    "Lightning": "雷",
    "Psychic": "超",
    "Fighting": "斗",
    "Darkness": "恶",
    "Metal": "钢",
    "Fairy": "妖精",
    "Dragon": "龙",
    "Colorless": "无色",
}

# ── Special Conditions ─────────────────────────────────────────────

SPECIAL_CONDITIONS_ZH = {
    "Poisoned": "中毒",
    "Burned": "灼伤",
    "Asleep": "睡眠",
    "Paralyzed": "麻痹",
    "Confused": "混乱",
}

# ── Supertypes ─────────────────────────────────────────────────────

SUPERTYPES = ["Pokémon", "Trainer", "Energy"]
SUPERTYPES_ZH = {
    "Pokémon": "宝可梦",
    "Trainer": "训练家",
    "Energy": "能量",
}
