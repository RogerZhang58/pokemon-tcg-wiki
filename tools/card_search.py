#!/usr/bin/env python3
"""
Card search with FTS5 full-text + structured filtering.

Supports:
  - Name search (zh/en/ja, fuzzy-tolerant)
  - Filter by supertype (Pokémon/Trainer/Energy)
  - Filter by types (Fire/Water/Grass/...)
  - Filter by set/series
  - Filter by format legality
  - Sort by relevance

Usage:
    python3 card_search.py "皮卡丘VMAX"
    python3 card_search.py --type Lightning --supertype Pokémon
    python3 card_search.py --set "Sword & Shield" --legal standard
    python3 card_search.py --json pikachu
"""

import argparse
import json
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

from utils import get_db, detect_language, normalize_name, levenshtein
from name_translator import NameTranslator


def search_cards(
    query: str = "",
    supertype: str = "",
    types: list[str] = None,
    subtype: str = "",
    set_name: str = "",
    legal_format: str = "",
    rarity: str = "",
    limit: int = 10,
    translator: NameTranslator = None,
) -> list[dict]:
    """Search cards with combined FTS5 + structured filters.

    Args:
        query: Name search query (zh/en/ja, fuzzy-tolerant)
        supertype: Filter by supertype (Pokémon/Trainer/Energy)
        types: Filter by energy types
        subtype: Filter by subtype (Basic/V/VMAX/Item/Supporter/...)
        set_name: Filter by set name
        legal_format: Filter by format legality (standard/expanded)
        rarity: Filter by rarity
        limit: Max results
        translator: NameTranslator instance for zh→en fallback

    Returns:
        List of card dicts with relevance metadata
    """
    conn = get_db()
    results = []

    # Step 1: FTS5 name search if query provided
    matched_ids = set()
    if query.strip():
        lang = detect_language(query)

        # Try exact match first via name_translator
        if translator:
            trans = translator.translate(query)
            for r in trans.get("results", []):
                if r.get("id"):
                    matched_ids.add(r["id"])

        # FTS5 search
        safe_query = query.replace("'", "''")
        try:
            cursor = conn.execute(
                """SELECT rowid FROM cards_fts
                   WHERE name_zh MATCH ? OR name_en MATCH ? OR name_ja MATCH ?
                   LIMIT ?""",
                (safe_query, safe_query, safe_query, limit * 3),
            )
            for row in cursor.fetchall():
                cursor2 = conn.execute(
                    "SELECT id FROM cards WHERE rowid = ?", (row[0],)
                )
                for r2 in cursor2.fetchall():
                    matched_ids.add(r2[0])
        except Exception:
            pass

    # Step 2: Build structured filter
    conditions = []
    params = []

    if matched_ids:
        placeholders = ",".join("?" * len(matched_ids))
        conditions.append(f"c.id IN ({placeholders})")
        params.extend(matched_ids)

    # Apply structured filters on JSON fields
    if supertype:
        conditions.append("json_extract(c.data_json, '$.supertype') = ?")
        params.append(supertype)

    if types:
        for t in types:
            conditions.append(
                "EXISTS (SELECT 1 FROM json_each(c.data_json, '$.types') "
                "WHERE value = ?)"
            )
            params.append(t)

    if subtype:
        conditions.append(
            "EXISTS (SELECT 1 FROM json_each(c.data_json, '$.subtypes') "
            "WHERE value = ?)"
        )
        params.append(subtype)

    if set_name:
        conditions.append(
            "(json_extract(c.data_json, '$.set.name') LIKE ? "
            "OR json_extract(c.data_json, '$.set.name.en') LIKE ? "
            "OR json_extract(c.data_json, '$.set.name.zh') LIKE ?)"
        )
        like_val = f"%{set_name}%"
        params.extend([like_val, like_val, like_val])

    if legal_format:
        conditions.append(
            f"json_extract(c.data_json, '$.legal.{legal_format}') = 'true'"
        )

    if rarity:
        conditions.append("json_extract(c.data_json, '$.rarity') LIKE ?")
        params.append(f"%{rarity}%")

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    sql = f"""
        SELECT c.id, c.data_json
        FROM cards c
        {where_clause}
        LIMIT ?
    """
    params.append(limit)

    cursor = conn.execute(sql, params)
    for row in cursor.fetchall():
        card = json.loads(row[1])

        # Calculate relevance score
        score = 0
        nm = card.get("name", {})
        if isinstance(nm, dict):
            card_name_zh = nm.get("zh", "")
            card_name_en = nm.get("en", "")
        else:
            card_name_zh = str(nm)
            card_name_en = ""

        if query.strip():
            normalized_q = normalize_name(query)
            normalized_zh = normalize_name(card_name_zh)
            normalized_en = normalize_name(card_name_en)

            if normalized_q == normalized_zh or normalized_q == normalized_en:
                score = 100
            elif normalized_q in normalized_zh or normalized_q in normalized_en:
                score = 80
            else:
                dist_zh = levenshtein(normalized_q, normalized_zh)
                dist_en = levenshtein(normalized_q, normalized_en)
                min_dist = min(dist_zh, dist_en)
                max_len = max(len(normalized_q), len(normalized_zh), len(normalized_en), 1)
                score = max(0, int((1 - min_dist / max_len) * 60))

        card["_relevance"] = score
        card["_id"] = row[0]
        results.append(card)

    conn.close()

    # Sort by relevance
    results.sort(key=lambda x: x["_relevance"], reverse=True)
    return results[:limit]


def format_card(card: dict, verbose: bool = False) -> str:
    """Format a single card for terminal output."""
    lines = []
    name = card.get("name", {})
    name_zh = name.get("zh", "") if isinstance(name, dict) else str(name)
    name_en = name.get("en", "") if isinstance(name, dict) else ""

    supertype = card.get("supertype", "")
    types_str = " ".join(card.get("types", []))
    hp = card.get("hp", "")
    subtypes = " ".join(card.get("subtypes", []))

    # Header
    header = f"{name_zh}"
    if name_en and name_en != name_zh:
        header += f" ({name_en})"
    lines.append(header)
    lines.append(f"  {supertype} {subtypes} | HP {hp} | {types_str}")

    # Attacks
    for atk in card.get("attacks", []):
        if not isinstance(atk, dict):
            continue
        an = atk.get("name", {})
        atk_name = an.get("zh", an.get("en", "?")) if isinstance(an, dict) else str(an)
        cost = " ".join(atk.get("cost", []))
        dmg = atk.get("damage", "")
        lines.append(f"  [{cost}] {atk_name}  {dmg}")

    # Weakness / Resistance / Retreat
    weak = ", ".join(
        f"{w.get('type', '?')} {w.get('value', '')}"
        for w in card.get("weaknesses", [])
    )
    resist = ", ".join(
        f"{r.get('type', '?')} {r.get('value', '')}"
        for r in card.get("resistances", [])
    )
    retreat = card.get("retreatCost", "?")

    lines.append(f"  弱点: {weak or '无'}  抗性: {resist or '无'}  撤退: {retreat}")

    # Legality
    legal = card.get("legal", {})
    fmt_info = []
    if legal.get("standard"):
        fmt_info.append("Standard ✅")
    else:
        fmt_info.append("Standard ❌")
    if legal.get("expanded"):
        fmt_info.append("Expanded ✅")
    else:
        fmt_info.append("Expanded ❌")
    lines.append(f"  {' | '.join(fmt_info)}")

    # Set & Rarity
    set_info = card.get("set", {})
    set_name = set_info.get("name", "")
    if isinstance(set_name, dict):
        set_name = set_name.get("zh", set_name.get("en", ""))
    lines.append(f"  {set_name} | {card.get('rarity', '')} | #{card.get('localId', '?')}")

    if verbose:
        # Show translation info
        trans = card.get("translation", {})
        lines.append(f"  翻译: 名称={trans.get('name','?')} 招式={trans.get('attacks','?')}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Search Pokemon TCG cards"
    )
    parser.add_argument("query", nargs="?", help="Card name search query")
    parser.add_argument("--type", "-t", action="append", dest="types",
                        help="Filter by energy type (can repeat)")
    parser.add_argument("--supertype", "-s", help="Pokémon/Trainer/Energy")
    parser.add_argument("--subtype", help="Basic/V/VMAX/Item/Supporter/...")
    parser.add_argument("--set", help="Set name filter")
    parser.add_argument("--legal", help="standard or expanded")
    parser.add_argument("--rarity", help="Rarity filter")
    parser.add_argument("--limit", "-n", type=int, default=10)
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    translator = NameTranslator()
    translator.load()

    results = search_cards(
        query=args.query or "",
        supertype=args.supertype,
        types=args.types,
        subtype=args.subtype,
        set_name=args.set,
        legal_format=args.legal,
        rarity=args.rarity,
        limit=args.limit,
        translator=translator,
    )

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        if not results:
            print("No cards found.")
            return
        print(f"Found {len(results)} cards:\n")
        for card in results:
            print(format_card(card, verbose=args.verbose))
            print()


if __name__ == "__main__":
    main()
