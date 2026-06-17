#!/usr/bin/env python3
"""Enrich zh-matched cards with full TCGdex details."""
import json, sys, time, urllib.request
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))
from utils import CARDS_DIR, ZH_MOD_DIR, normalize_card_id

API = "https://api.tcgdex.net/v2/en/cards"

def get(url):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "pokemon-tcg-wiki/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(1)

# Get zh-matched IDs directly
names_en = json.load(open(ZH_MOD_DIR / "names.json"))
names_zh = json.load(open(ZH_MOD_DIR / "databases_zh-CN/names.json"))
zh_ids = []
for h, ids in names_en.items():
    if h in names_zh:
        for cid in ids:
            zh_ids.append(normalize_card_id(cid, "tcgdex"))

print(f"zh-matched cards: {len(zh_ids)}")

count = ok = skip = err = 0
for cid in zh_ids:
    card_path = CARDS_DIR / f"{cid}.json"
    # Skip if already has full data
    if card_path.exists():
        with open(card_path) as f:
            existing = json.load(f)
        if existing.get("hp") is not None:
            skip += 1
            continue

    try:
        card = get(f"{API}/{cid}")
        with open(card_path, "w", encoding="utf-8") as f:
            json.dump(card, f, ensure_ascii=False)
        ok += 1
    except Exception as e:
        err += 1

    count += 1
    if count % 1000 == 0:
        print(f"  {count}/{len(zh_ids)} — ok:{ok} skip:{skip} err:{err}")

print(f"Done: {count} processed — ok:{ok} skip:{skip} err:{err}")
