#!/usr/bin/env python3
"""
Build SQLite FTS5 indices from merged card data and rule documents.

Creates:
  - cards_fts: full-text search over card names, types, attacks, abilities
  - rules_fts: full-text search over rule documents

Usage:
    python3 build_indices.py               # Build both indices
    python3 build_indices.py --cards-only   # Cards only
    python3 build_indices.py --rules-only   # Rules only
    python3 build_indices.py --rebuild      # Drop and rebuild all
"""

import argparse
import json
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

from utils import (
    CARDS_ZH_DIR, RULES_DIR, init_db, get_db,
    CARDS_TABLE_SQL, CARDS_FTS_SQL,
    RULES_TABLE_SQL, RULES_FTS_SQL,
)


def build_cards_index(rebuild: bool = False) -> int:
    """Build FTS5 index for all merged cards. Returns count."""
    print("Building cards FTS5 index...")

    conn = get_db()

    if rebuild:
        conn.execute("DROP TABLE IF EXISTS cards_fts")
        conn.execute("DROP TABLE IF EXISTS cards")

    conn.execute(CARDS_TABLE_SQL)
    conn.execute(CARDS_FTS_SQL)

    # Clear existing data
    conn.execute("DELETE FROM cards")
    conn.execute("DELETE FROM cards_fts")

    card_files = sorted(CARDS_ZH_DIR.glob("*.json"))
    if not card_files:
        print("  No card files found in cards_zh/. Run build_cards.py first.")
        conn.close()
        return 0

    count = 0
    for card_file in card_files:
        try:
            with open(card_file, "r", encoding="utf-8") as f:
                card = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"  Skipping {card_file.name}: {e}")
            continue

        card_id = card.get("id", card_file.stem)

        # Extract searchable fields
        name = card.get("name", {})
        name_zh = name.get("zh", "") if isinstance(name, dict) else ""
        name_ja = name.get("ja", "") if isinstance(name, dict) else ""
        name_en = name.get("en", "") if isinstance(name, dict) else str(name)

        types = " ".join(card.get("types", []))
        supertype = card.get("supertype", "")
        subtypes = " ".join(card.get("subtypes", []))

        attack_names = []
        attack_texts = []
        for atk in card.get("attacks", []):
            if isinstance(atk, dict):
                an = atk.get("name", {})
                if isinstance(an, dict):
                    zh = an.get("zh", "")
                    en = an.get("en", "")
                    attack_names.append(f"{zh} {en}".strip())
                else:
                    attack_names.append(str(an))
                at = atk.get("effect", {})
                if isinstance(at, dict):
                    zh = at.get("zh", "")
                    en = at.get("en", "")
                    attack_texts.append(f"{zh} {en}".strip())
                elif isinstance(at, str):
                    attack_texts.append(at)

        ability_names = []
        ability_texts = []
        for ab in card.get("abilities", []):
            if isinstance(ab, dict):
                an = ab.get("name", {})
                if isinstance(an, dict):
                    ability_names.append(f"{an.get('zh', '')} {an.get('en', '')}".strip())
                at = ab.get("text", {})
                if isinstance(at, dict):
                    ability_texts.append(f"{at.get('zh', '')} {at.get('en', '')}".strip())

        set_info = card.get("set", {})
        set_name = set_info.get("name", "")
        if isinstance(set_name, dict):
            set_name = f"{set_name.get('zh', '')} {set_name.get('en', '')}".strip()

        rarity = card.get("rarity", "")
        artist = card.get("artist", "")

        # Store full JSON
        data_json = json.dumps(card, ensure_ascii=False)

        conn.execute(
            "INSERT OR REPLACE INTO cards (id, data_json) VALUES (?, ?)",
            (card_id, data_json),
        )

        # Insert into FTS
        conn.execute(
            """INSERT INTO cards_fts (
                name_zh, name_ja, name_en,
                types, supertype, subtypes,
                attack_names, attack_texts,
                ability_names, ability_texts,
                set_name, rarity, artist
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                name_zh, name_ja, name_en,
                types, supertype, subtypes,
                " | ".join(attack_names), " | ".join(attack_texts),
                " | ".join(ability_names), " | ".join(ability_texts),
                set_name, rarity, artist,
            ),
        )

        count += 1
        if count % 1000 == 0:
            print(f"  Indexed {count} cards...")
            conn.commit()

    conn.commit()
    conn.close()
    print(f"  Cards index: {count} cards indexed")
    return count


def build_rules_index(rebuild: bool = False) -> int:
    """Build FTS5 index for rule documents. Returns count."""
    print("Building rules FTS5 index...")

    conn = get_db()

    if rebuild:
        conn.execute("DROP TABLE IF EXISTS rules_fts")
        conn.execute("DROP TABLE IF EXISTS rules")

    conn.execute(RULES_TABLE_SQL)
    conn.execute(RULES_FTS_SQL)

    # Clear existing
    conn.execute("DELETE FROM rules")
    conn.execute("DELETE FROM rules_fts")

    count = 0

    # Index markdown rule files
    for lang_dir in sorted(RULES_DIR.iterdir()):
        if not lang_dir.is_dir():
            continue
        lang = lang_dir.name

        for rule_file in sorted(lang_dir.glob("*.md")):
            try:
                with open(rule_file, "r", encoding="utf-8") as f:
                    content = f.read()
            except IOError:
                continue

            title = rule_file.stem.replace("-", " ").replace("_", " ").title()
            # Try to extract title from first H1
            for line in content.splitlines():
                if line.startswith("# "):
                    title = line[2:].strip()
                    break

            section = str(rule_file.relative_to(RULES_DIR))

            conn.execute(
                "INSERT INTO rules (title, content, lang, section, file_path) VALUES (?, ?, ?, ?, ?)",
                (title, content, lang, section, str(rule_file)),
            )

            conn.execute(
                "INSERT INTO rules_fts (title, content, lang, section) VALUES (?, ?, ?, ?)",
                (title, content, lang, section),
            )

            count += 1

    # Also index zh-mod game text
    from utils import ZH_MOD_TEXT_DIR
    for text_file in ZH_MOD_TEXT_DIR.glob("*.json"):
        try:
            with open(text_file, "r", encoding="utf-8") as f:
                text_data = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue

        # Create pseudo-rule documents from text entries
        for key, value in text_data.items():
            if not isinstance(value, str) or len(value) < 10:
                continue

            section = f"game_text/{text_file.stem}"
            # Categorize by key prefix
            if "condition" in key.lower() or "special" in key.lower():
                section = "game_text/special_conditions"
            elif "energy" in key.lower():
                section = "game_text/energy"
            elif "rule" in key.lower():
                section = "game_text/rules"

            conn.execute(
                "INSERT INTO rules (title, content, lang, section, file_path) VALUES (?, ?, ?, ?, ?)",
                (key, value, "zh", section, str(text_file)),
            )
            conn.execute(
                "INSERT INTO rules_fts (title, content, lang, section) VALUES (?, ?, ?, ?)",
                (key, value, "zh", section),
            )
            count += 1

    conn.commit()
    conn.close()
    print(f"  Rules index: {count} entries indexed")
    return count


def main():
    parser = argparse.ArgumentParser(
        description="Build FTS5 indices for Pokemon TCG Wiki"
    )
    parser.add_argument("--cards-only", action="store_true")
    parser.add_argument("--rules-only", action="store_true")
    parser.add_argument("--rebuild", action="store_true",
                        help="Drop and rebuild all indices")
    args = parser.parse_args()

    all_mode = not args.cards_only and not args.rules_only

    if all_mode or args.cards_only:
        build_cards_index(rebuild=args.rebuild)

    if all_mode or args.rules_only:
        build_rules_index(rebuild=args.rebuild)

    print("\n═══ Index build complete ═══")


if __name__ == "__main__":
    main()
