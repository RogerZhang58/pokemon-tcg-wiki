#!/usr/bin/env python3
"""
Trilingual name translator: Simplified Chinese ↔ Japanese ↔ English.

Data sources:
  1. zh-mod databases_zh-CN/names.json (hash → zh_name, 100% coverage)
  2. zh-mod dictionary.json (EN pokemon name → ZH pokemon name, 1008+ species)
  3. TCGdex cards (EN/JP names from card metadata)
  4. FTS5 index (for fallback search)

Usage:
    python3 name_translator.py "皮卡丘VMAX"        # zh → {en, ja}
    python3 name_translator.py "Pikachu VMAX"       # en → {zh, ja}
    python3 name_translator.py "ピカチュウVMAX"     # ja → {zh, en}
    python3 name_translator.py --interactive         # Interactive mode
"""

import argparse
import json
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

from utils import (
    CARDS_ZH_DIR, ZH_MOD_DIR, ZH_MOD_DB_DIR,
    get_db, detect_language, levenshtein, normalize_name,
)


class NameTranslator:
    """Trilingual Pokémon TCG name translator."""

    def __init__(self):
        self._zh_to_ids: dict[str, list[str]] = {}  # zh_name → [card_ids]
        self._en_to_ids: dict[str, list[str]] = {}  # en_name → [card_ids]
        self._ja_to_ids: dict[str, list[str]] = {}  # ja_name → [card_ids]
        self._id_to_names: dict[str, dict] = {}     # card_id → {zh, en, ja}
        self._pokemon_dict: dict[str, str] = {}      # EN species → ZH species
        self._loaded = False

    def load(self) -> None:
        """Load all translation data into memory."""
        if self._loaded:
            return

        # Load zh-mod names database
        names_zh_path = ZH_MOD_DB_DIR / "names.json"
        names_en_path = ZH_MOD_DIR / "names.json"

        if not names_zh_path.exists():
            print("WARNING: zh-mod databases not synced. Run sync_data.py --zhmod first.",
                  file=sys.stderr)

        # Build zh → card_ids mapping from zh-mod
        if names_en_path.exists() and names_zh_path.exists():
            with open(names_en_path, "r", encoding="utf-8") as f:
                names_en = json.load(f)
            with open(names_zh_path, "r", encoding="utf-8") as f:
                names_zh = json.load(f)

            for hash_val, zh_name in names_zh.items():
                if hash_val in names_en:
                    for card_id in names_en[hash_val]:
                        normalized = card_id.replace("_", "-")
                        if zh_name not in self._zh_to_ids:
                            self._zh_to_ids[zh_name] = []
                        self._zh_to_ids[zh_name].append(normalized)

        # Load from merged cards for EN/JA and full id→names
        for card_file in sorted(CARDS_ZH_DIR.glob("*.json")):
            try:
                with open(card_file, "r", encoding="utf-8") as f:
                    card = json.load(f)
            except (json.JSONDecodeError, IOError):
                continue

            card_id = card.get("id", card_file.stem)
            name = card.get("name", {})

            names_dict = {}
            if isinstance(name, dict):
                for lang in ["zh", "en", "ja"]:
                    n = name.get(lang, "")
                    names_dict[lang] = n
                    if n:
                        target = getattr(self, f"_{lang}_to_ids")
                        if n not in target:
                            target[n] = []
                        if card_id not in target[n]:
                            target[n].append(card_id)
            self._id_to_names[card_id] = names_dict

        # Load dictionary.json
        dict_path = ZH_MOD_DIR / "dictionary.json"
        if dict_path.exists():
            with open(dict_path, "r", encoding="utf-8") as f:
                self._pokemon_dict = json.load(f)

        self._loaded = True

    def translate(self, name: str) -> dict:
        """Translate a card name between zh/en/ja.

        Returns:
            {
                "input": name,
                "lang": "zh"|"en"|"ja",
                "results": [{"zh": ..., "en": ..., "ja": ..., "id": ...}, ...]
            }
        """
        self.load()
        lang = detect_language(name)
        normalized = normalize_name(name)

        result = {"input": name, "lang": lang, "results": []}

        # Direct lookup
        if lang == "zh":
            source_dict = self._zh_to_ids
        elif lang == "ja":
            source_dict = self._ja_to_ids
        else:
            source_dict = self._en_to_ids

        # Exact match
        if name in source_dict:
            for cid in source_dict[name]:
                names = self._id_to_names.get(cid, {})
                result["results"].append({
                    "zh": names.get("zh", ""),
                    "en": names.get("en", ""),
                    "ja": names.get("ja", ""),
                    "id": cid,
                    "match": "exact",
                })

        # Fuzzy match (Levenshtein)
        if not result["results"]:
            best_score = float("inf")
            best_name = ""
            for n in source_dict:
                score = levenshtein(normalized, normalize_name(n))
                if score < best_score and score < len(normalized) * 0.5:
                    best_score = score
                    best_name = n

            if best_name:
                for cid in source_dict[best_name]:
                    names = self._id_to_names.get(cid, {})
                    result["results"].append({
                        "zh": names.get("zh", ""),
                        "en": names.get("en", ""),
                        "ja": names.get("ja", ""),
                        "id": cid,
                        "match": f"fuzzy({best_score})",
                    })

        # Pokémon species dictionary lookup
        if not result["results"] and lang == "zh":
            # Try to find base species name
            for en_name, zh_name in self._pokemon_dict.items():
                if zh_name in name:
                    # Found a base species match — search by EN species
                    for en_card_name, card_ids in self._en_to_ids.items():
                        if en_name.lower() in en_card_name.lower():
                            for cid in card_ids:
                                names = self._id_to_names.get(cid, {})
                                result["results"].append({
                                    "zh": names.get("zh", ""),
                                    "en": names.get("en", ""),
                                    "ja": names.get("ja", ""),
                                    "id": cid,
                                    "match": "species",
                                })

        # FTS5 fallback
        if not result["results"]:
            try:
                conn = get_db()
                query = name.replace("'", "''")
                cursor = conn.execute(
                    "SELECT id, data_json FROM cards WHERE id IN "
                    "(SELECT rowid FROM cards_fts WHERE name_zh MATCH ? "
                    "UNION SELECT rowid FROM cards_fts WHERE name_en MATCH ? "
                    "UNION SELECT rowid FROM cards_fts WHERE name_ja MATCH ?) "
                    "LIMIT 5",
                    (query, query, query),
                )
                for row in cursor.fetchall():
                    card = json.loads(row[1])
                    nm = card.get("name", {})
                    result["results"].append({
                        "zh": nm.get("zh", "") if isinstance(nm, dict) else "",
                        "en": nm.get("en", "") if isinstance(nm, dict) else "",
                        "ja": nm.get("ja", "") if isinstance(nm, dict) else "",
                        "id": row[0],
                        "match": "fts5",
                    })
                conn.close()
            except Exception:
                pass

        return result


def main():
    parser = argparse.ArgumentParser(
        description="Trilingual Pokemon TCG name translator"
    )
    parser.add_argument("query", nargs="?", help="Card name to translate")
    parser.add_argument("--interactive", "-i", action="store_true",
                        help="Interactive mode")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON")
    args = parser.parse_args()

    translator = NameTranslator()

    if args.interactive:
        print("Pokemon TCG Name Translator — type 'quit' to exit")
        translator.load()
        print(f"  {len(translator._zh_to_ids)} zh names, "
              f"{len(translator._en_to_ids)} en names, "
              f"{len(translator._ja_to_ids)} ja names loaded")
        while True:
            try:
                query = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if query.lower() in ("quit", "exit", "q"):
                break
            if not query:
                continue
            result = translator.translate(query)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                _print_result(result)
    elif args.query:
        result = translator.translate(args.query)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            _print_result(result)
    else:
        parser.print_help()


def _print_result(result: dict):
    """Pretty-print a translation result."""
    print(f"Input: {result['input']} (detected: {result['lang']})")
    if not result["results"]:
        print("  No matches found.")
        return
    for r in result["results"]:
        print(f"  [{r['match']}] {r['zh']} / {r['en']} / {r['ja']}")
        print(f"         ID: {r['id']}")


if __name__ == "__main__":
    main()
