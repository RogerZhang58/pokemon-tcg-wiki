#!/usr/bin/env python3
"""
Merge TCGdex card metadata with PTCG Live zh-mod Chinese translations.

Process:
  1. Read TCGdex raw cards from raw/data/cards/
  2. Read zh-mod databases (hash → zh_name, hash → zh_attacks)
  3. Match cards by normalised card ID
  4. Write merged Chinese cards to raw/data/cards_zh/

Usage:
    python3 build_cards.py               # Full merge
    python3 build_cards.py --dry-run      # Show stats only
    python3 build_cards.py --llm-trans    # Also run LLM translation fallback
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

from utils import (
    CARDS_DIR, CARDS_ZH_DIR, ZH_MOD_DIR, ZH_MOD_DB_DIR,
    LLM_TRANS_DIR, normalize_card_id, ENERGY_ZH, SUPERTYPES_ZH,
)


def load_zhmod_names() -> dict:
    """Load zh-mod names database: hash → Chinese name.

    zh-mod format:
      databases/names.json:     hash → [card_id, card_id, ...]
      databases_zh-CN/names.json: hash → "中文卡名"
    """
    names_en_path = ZH_MOD_DIR / "names.json"
    names_zh_path = ZH_MOD_DB_DIR / "names.json"

    if not names_zh_path.exists():
        print(f"  WARNING: {names_zh_path} not found, run sync_data.py --zhmod first")
        return {}

    names_en = {}
    if names_en_path.exists():
        with open(names_en_path, "r", encoding="utf-8") as f:
            names_en = json.load(f)

    with open(names_zh_path, "r", encoding="utf-8") as f:
        names_zh = json.load(f)

    # Build: card_id → zh_name
    card_to_zh = {}
    for hash_val, zh_name in names_zh.items():
        if hash_val in names_en:
            for card_id in names_en[hash_val]:
                normalized = normalize_card_id(card_id, "tcgdex")
                card_to_zh[normalized] = zh_name

    print(f"  Loaded {len(card_to_zh)} card ID → zh_name mappings")
    return card_to_zh


def load_zhmod_attacks() -> dict[str, dict]:
    """Load zh-mod attack translations: hash → {name_zh, text_zh}.

    Returns dict of card_hash → {name: zh_name, text: zh_text}
    """
    result = defaultdict(dict)

    # Attack names: hash → [card_ids]
    attks_en_path = ZH_MOD_DIR / "attks-name.json"
    attks_zh_path = ZH_MOD_DB_DIR / "attks-name.json"
    attks_text_en_path = ZH_MOD_DIR / "attks-text.json"
    attks_text_zh_path = ZH_MOD_DB_DIR / "attks-text.json"

    # Hash → zh attack name
    hash_to_name_zh = {}
    if attks_zh_path.exists():
        with open(attks_zh_path, "r", encoding="utf-8") as f:
            for hash_val, zh_name in json.load(f).items():
                hash_to_name_zh[hash_val] = zh_name

    # Hash → zh attack text
    hash_to_text_zh = {}
    if attks_text_zh_path.exists():
        with open(attks_text_zh_path, "r", encoding="utf-8") as f:
            for hash_val, zh_text in json.load(f).items():
                hash_to_text_zh[hash_val] = zh_text

    # Hash → [card_ids] for name
    if attks_en_path.exists():
        with open(attks_en_path, "r", encoding="utf-8") as f:
            for hash_val, card_ids in json.load(f).items():
                zh_name = hash_to_name_zh.get(hash_val)
                if zh_name:
                    for cid in card_ids:
                        normalized = normalize_card_id(cid, "tcgdex")
                        result[normalized][f"an_{hash_val[:8]}"] = zh_name

    # Hash → [card_ids] for text
    if attks_text_en_path.exists():
        with open(attks_text_en_path, "r", encoding="utf-8") as f:
            for hash_val, card_ids in json.load(f).items():
                zh_text = hash_to_text_zh.get(hash_val)
                if zh_text:
                    for cid in card_ids:
                        normalized = normalize_card_id(cid, "tcgdex")
                        result[normalized][f"at_{hash_val[:8]}"] = zh_text

    return dict(result)


def load_dictionary() -> dict[str, str]:
    """Load dictionary.json: EN pokemon name → ZH pokemon name."""
    dict_path = ZH_MOD_DIR / "dictionary.json"
    if not dict_path.exists():
        return {}
    with open(dict_path, "r", encoding="utf-8") as f:
        return json.load(f)


def merge_card_zh(
    card_data: dict,
    zh_name: str,
    zh_attacks: dict,
    pokemon_dict: dict[str, str],
) -> dict:
    """Merge a single card's metadata with Chinese translations.

    Returns the card data with zh translations injected into name,
    attacks, and adding translation metadata.
    """
    card = dict(card_data)  # shallow copy

    # ── Name ──
    name_obj = card.get("name", {})
    if isinstance(name_obj, dict):
        name_obj["zh"] = zh_name
    else:
        # If name is a plain string (some TCGdex versions), wrap it
        name_obj = {"en": str(name_obj), "zh": zh_name}
    card["name"] = name_obj

    # ── Pokémon species name from dictionary ──
    if pokemon_dict and zh_name:
        # Try to find the base species name in the zh_name
        for en_name, zh_poke in pokemon_dict.items():
            if en_name.lower() in zh_name.lower():
                # Store base species separately
                card.setdefault("species", {})
                card["species"]["zh"] = zh_poke
                card["species"]["en"] = en_name
                break

    # ── Attacks ──
    attacks = card.get("attacks", [])
    zh_covered = 0
    zh_total = 0

    for attack in attacks:
        if not isinstance(attack, dict):
            continue

        att_name_en = attack.get("name", "")
        att_effect_en = attack.get("effect", "")

        # Try to match zh_attacks by hash entries
        # zh_attacks keys are prefixed like "an_<hash8>" or "at_<hash8>"
        # We match by the English name/effect stored in the card
        atk_name = attack.get("name", "")
        if isinstance(atk_name, str):
            attack["name"] = {"en": atk_name}

        atk_effect = attack.get("effect", "")
        if isinstance(atk_effect, str):
            attack["effect"] = {"en": atk_effect}

        zh_total += 2  # name + effect to translate

        # Find matching zh translation from zh_attacks
        for zh_key, zh_val in zh_attacks.items():
            if zh_key.startswith("an_") and zh_val:
                # Attack name translation
                if "name" in attack and isinstance(attack["name"], dict):
                    attack["name"]["zh"] = zh_val
                    zh_covered += 1
                    break
            elif zh_key.startswith("at_") and zh_val:
                # Attack text translation
                if "effect" in attack and isinstance(attack["effect"], dict):
                    attack["effect"]["zh"] = zh_val
                    zh_covered += 1
                    break

    # ── Translation metadata ──
    name_source = "zh-mod" if zh_name else "llm"
    attack_source = "zh-mod" if zh_covered == zh_total else (
        "mixed" if zh_covered > 0 else "llm"
    )

    card["translation"] = {
        "name": name_source,
        "attacks": attack_source,
    }

    # ── Legal source ──
    card["legal_source"] = "intl"

    # ── Energy type zh labels ──
    if "types" in card:
        card["types_zh"] = [ENERGY_ZH.get(t, t) for t in card["types"]]

    if "weaknesses" in card:
        for w in card["weaknesses"]:
            if isinstance(w, dict) and "type" in w:
                w["type_zh"] = ENERGY_ZH.get(w["type"], w["type"])

    if "resistances" in card:
        for r in card["resistances"]:
            if isinstance(r, dict) and "type" in r:
                r["type_zh"] = ENERGY_ZH.get(r["type"], r["type"])

    return card


def run_merge(dry_run: bool = False) -> dict:
    """Run the full merge process. Returns stats dict."""
    stats = {
        "tcgdex_cards": 0,
        "zh_matched": 0,
        "zh_unmatched": 0,
        "written": 0,
    }

    # Load zh-mod data
    print("Loading zh-mod translations...")
    card_to_zh = load_zhmod_names()
    zh_attacks = load_zhmod_attacks()
    pokemon_dict = load_dictionary()

    print(f"  Attack translations: {len(zh_attacks)} cards have attack data")

    # Scan TCGdex cards
    print("Scanning TCGdex cards...")
    card_files = sorted(CARDS_DIR.glob("*.json"))
    stats["tcgdex_cards"] = len(card_files)
    print(f"  Found {len(card_files)} card files")

    if dry_run:
        print(f"\n[Dry run] Would merge {len(card_files)} cards")
        matched = sum(1 for cf in card_files if cf.stem in card_to_zh)
        print(f"  With zh names: {matched} ({matched/len(card_files)*100:.1f}%)")
        print(f"  Attack coverage: {len(zh_attacks)} cards")
        return stats

    # Process each card
    print("Merging cards...")
    CARDS_ZH_DIR.mkdir(parents=True, exist_ok=True)

    for card_file in card_files:
        card_id = card_file.stem

        with open(card_file, "r", encoding="utf-8") as f:
            card_data = json.load(f)

        zh_name = card_to_zh.get(card_id, "")
        card_attacks = zh_attacks.get(card_id, {})

        if zh_name:
            stats["zh_matched"] += 1
        else:
            stats["zh_unmatched"] += 1

        merged = merge_card_zh(card_data, zh_name, card_attacks, pokemon_dict)

        # Write merged card
        out_path = CARDS_ZH_DIR / f"{card_id}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)

        stats["written"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Merge TCGdex metadata + zh-mod translations"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show stats without writing files"
    )
    parser.add_argument(
        "--llm-trans", action="store_true",
        help="Run LLM translation for untranslated attacks (not yet implemented)"
    )
    args = parser.parse_args()

    stats = run_merge(dry_run=args.dry_run)

    print(f"\n═══ Merge stats ═══")
    print(f"  TCGdex cards:     {stats['tcgdex_cards']}")
    print(f"  ZH name matched:  {stats['zh_matched']}")
    print(f"  ZH name missing:  {stats['zh_unmatched']}")
    if not args.dry_run:
        print(f"  Written to:       {CARDS_ZH_DIR}")
        print(f"  Files written:    {stats['written']}")

    if stats["tcgdex_cards"] > 0:
        coverage = stats["zh_matched"] / stats["tcgdex_cards"] * 100
        print(f"  Name coverage:    {coverage:.1f}%")


if __name__ == "__main__":
    main()
