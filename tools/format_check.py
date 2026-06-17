#!/usr/bin/env python3
"""
Format legality and banned card checker.

Checks:
  - Whether a card is legal in Standard / Expanded
  - Current banned/restricted card list
  - Card legality history

Data sources:
  - TCGdex card.legal field (international format)
  - raw/banned/ (manually maintained ban lists)

Usage:
    python3 format_check.py --card swsh3-25
    python3 format_check.py --card "皮卡丘VMAX"
    python3 format_check.py --list standard
    python3 format_check.py --check-deck decklist.txt
"""

import argparse
import json
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

from utils import get_db, BANNED_DIR, normalize_card_id
from name_translator import NameTranslator


def load_banned_lists() -> dict[str, list[str]]:
    """Load banned card lists from raw/banned/.

    Returns: {"standard": [card_id, ...], "expanded": [card_id, ...]}
    """
    banned = {"standard": [], "expanded": []}

    for fmt in ["standard", "expanded"]:
        path = BANNED_DIR / f"{fmt}.json"
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    banned[fmt] = data
                elif isinstance(data, dict) and "banned" in data:
                    banned[fmt] = data["banned"]
            except (json.JSONDecodeError, IOError):
                pass

    return banned


def check_card_legality(
    card_id: str,
    translator: NameTranslator = None,
) -> dict:
    """Check a card's format legality.

    Args:
        card_id: TCGdex card ID or card name
        translator: NameTranslator for name→ID lookup

    Returns:
        {
            "card_id": str,
            "card_name": {"zh": str, "en": str},
            "legal": {"standard": bool, "expanded": bool},
            "banned": {"standard": bool, "expanded": bool},
            "regulation_mark": str,
        }
    """
    # Resolve name to ID if needed
    resolved_id = card_id
    if not card_id.count("-") and not card_id.replace("_", "").replace("-", "").isalnum():
        # Likely a name, not an ID
        if translator:
            trans = translator.translate(card_id)
            if trans.get("results"):
                resolved_id = trans["results"][0].get("id", card_id)

    normalized = normalize_card_id(resolved_id, "tcgdex")
    conn = get_db()

    # Try JSON extraction first
    cursor = conn.execute(
        "SELECT data_json FROM cards WHERE id = ?", (normalized,)
    )
    row = cursor.fetchone()

    if not row:
        # Try FTS5 search
        try:
            safe = card_id.replace("'", "''")
            cursor = conn.execute(
                "SELECT c.data_json FROM cards c "
                "JOIN cards_fts f ON c.rowid = f.rowid "
                "WHERE cards_fts MATCH ? LIMIT 1",
                (safe,),
            )
            row = cursor.fetchone()
        except Exception:
            row = None

    conn.close()

    if not row:
        return {
            "card_id": card_id,
            "card_name": {},
            "error": "Card not found",
        }

    card = json.loads(row[0])
    name = card.get("name", {})
    legal = card.get("legal", {})
    banned = load_banned_lists()

    result = {
        "card_id": card.get("id", card_id),
        "card_name": name if isinstance(name, dict) else {"en": str(name)},
        "legal": {
            "standard": legal.get("standard", False),
            "expanded": legal.get("expanded", False),
        },
        "banned": {
            "standard": card.get("id", "") in banned.get("standard", []),
            "expanded": card.get("id", "") in banned.get("expanded", []),
        },
        "regulation_mark": card.get("regulationMark", ""),
        "legal_source": card.get("legal_source", "intl"),
    }

    return result


def list_format_cards(
    fmt: str,
    banned_only: bool = False,
    translator: NameTranslator = None,
) -> list[dict]:
    """List all cards in a format, optionally filtered to banned only."""
    conn = get_db()
    banned = load_banned_lists()

    if banned_only:
        card_ids = banned.get(fmt, [])
        results = []
        for cid in card_ids:
            cursor = conn.execute(
                "SELECT data_json FROM cards WHERE id = ?", (cid,)
            )
            row = cursor.fetchone()
            if row:
                card = json.loads(row[0])
                results.append({
                    "id": cid,
                    "name": card.get("name", {}),
                    "banned": True,
                })
        conn.close()
        return results

    # Query cards where legal.{fmt} = true
    try:
        cursor = conn.execute(
            f"SELECT id, data_json FROM cards "
            f"WHERE json_extract(data_json, '$.legal.{fmt}') = 'true' "
            f"ORDER BY id LIMIT 500"
        )
        results = []
        for row in cursor.fetchall():
            card = json.loads(row[1])
            results.append({
                "id": row[0],
                "name": card.get("name", {}),
                "banned": row[0] in banned.get(fmt, []),
            })
        conn.close()
        return results
    except Exception:
        conn.close()
        return []


def format_result(result: dict) -> str:
    """Format a legality check result for terminal output."""
    if "error" in result:
        return f"Error: {result['error']}"

    lines = []
    name = result.get("card_name", {})
    name_str = name.get("zh", name.get("en", "Unknown")) if isinstance(name, dict) else str(name)
    lines.append(f"卡牌: {name_str}")
    lines.append(f"ID: {result['card_id']}")

    legal = result.get("legal", {})
    banned = result.get("banned", {})

    for fmt in ["standard", "expanded"]:
        status = "✅ 合法"
        if banned.get(fmt):
            status = "🚫 禁用"
        elif not legal.get(fmt):
            status = "❌ 不合法（轮替/未收录）"
        lines.append(f"  {fmt.capitalize()}: {status}")

    if result.get("regulation_mark"):
        lines.append(f"  环境标记: {result['regulation_mark']}")

    if result.get("legal_source") == "intl":
        lines.append(f"  ⚠️ 数据源: 国际版（非简中赛制）")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Check Pokemon TCG card format legality"
    )
    parser.add_argument("--card", "-c", help="Card ID or name to check")
    parser.add_argument("--list", "-l", choices=["standard", "expanded"],
                        help="List cards in a format")
    parser.add_argument("--banned", action="store_true",
                        help="Show only banned cards (with --list)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    translator = NameTranslator()
    translator.load()

    if args.card:
        result = check_card_legality(args.card, translator)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(format_result(result))

    elif args.list:
        results = list_format_cards(args.list, args.banned, translator)
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            if args.banned:
                print(f"Banned cards in {args.list.capitalize()}:\n")
            else:
                print(f"Cards legal in {args.list.capitalize()} (first 500):\n")

            for r in results:
                name = r.get("name", {})
                name_str = name.get("zh", name.get("en", "?")) if isinstance(name, dict) else str(name)
                ban_tag = " 🚫BANNED" if r.get("banned") else ""
                print(f"  {name_str} ({r['id']}){ban_tag}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
