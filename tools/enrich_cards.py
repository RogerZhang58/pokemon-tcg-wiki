#!/usr/bin/env python3
"""Enrich cards with full TCGdex details for zh-matched cards only.

Reads existing card summaries from raw/data/cards/, fetches full details
from api.tcgdex.net for cards that have zh-mod translations (~7k cards).
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))
from utils import CARDS_DIR, CARDS_ZH_DIR, ZH_MOD_DIR, normalize_card_id

API = "https://api.tcgdex.net/v2/en/cards"

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "pokemon-tcg-wiki/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

# Load zh-matched card IDs
names_en = json.load(open(ZH_MOD_DIR / "names.json"))
names_zh = json.load(open(ZH_MOD_DIR / "databases_zh-CN/names.json"))
zh_matched = set()
for h, ids in names_en.items():
    if h in names_zh:
        for cid in ids:
            zh_matched.add(normalize_card_id(cid, "tcgdex"))

print(f"zh-matched card IDs: {len(zh_matched)}")

# Check which ones already have full data (have hp field)
need_fetch = []
already_full = 0
missing_file = 0

for cid in sorted(zh_matched):
    card_path = CARDS_DIR / f"{cid}.json"
    if not card_path.exists():
        missing_file += 1
        need_fetch.append(cid)
        continue
    with open(card_path, "r") as f:
        card = json.load(f)
    if card.get("hp") is not None and card.get("types") is not None:
        already_full += 1
    else:
        need_fetch.append(cid)

print(f"Already full: {already_full}")
print(f"Missing file: {missing_file}")
print(f"Need fetch:   {len(need_fetch)}")

if not need_fetch:
    print("All cards already have full data!")
    sys.exit(0)

count = 0
for cid in need_fetch:
    try:
        card = get(f"{API}/{cid}")
        with open(CARDS_DIR / f"{cid}.json", "w", encoding="utf-8") as f:
            json.dump(card, f, ensure_ascii=False)
        count += 1
        if count % 500 == 0:
            print(f"  Fetched {count}/{len(need_fetch)}...")
        time.sleep(0.1)
    except Exception as e:
        print(f"  Error {cid}: {e}")
        time.sleep(1)

print(f"Done: {count} cards enriched")
