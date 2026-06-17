#!/usr/bin/env python3
"""Fast card enrichment: fetch full TCGdex details for zh-matched cards."""
import json, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))
from utils import CARDS_DIR, ZH_MOD_DIR, normalize_card_id

API = "https://api.tcgdex.net/v2/en/cards"

def get(cid):
    for attempt in range(2):
        try:
            url = f"{API}/{cid}"
            req = urllib.request.Request(url, headers={"User-Agent": "ptcg-wiki/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode())
        except:
            time.sleep(0.5)

# Build zh-matched IDs
names_en = json.load(open(ZH_MOD_DIR / "names.json"))
names_zh = json.load(open(ZH_MOD_DIR / "databases_zh-CN/names.json"))
zh_ids = set()
for h, ids in names_en.items():
    if h in names_zh:
        for cid in ids:
            zh_ids.add(normalize_card_id(cid, "tcgdex"))

print(f"zh-matched: {len(zh_ids)} IDs")

# Fetch all — overwrite existing files (summary → full)
def fetch_and_save(cid):
    card = get(cid)
    if card:
        with open(CARDS_DIR / f"{cid}.json", "w", encoding="utf-8") as f:
            json.dump(card, f, ensure_ascii=False)
        return True
    return False

ok = err = 0
todo = sorted(zh_ids)
with ThreadPoolExecutor(max_workers=8) as ex:
    futs = {ex.submit(fetch_and_save, cid): cid for cid in todo}
    for i, f in enumerate(as_completed(futs)):
        if f.result():
            ok += 1
        else:
            err += 1
        if (i + 1) % 1000 == 0:
            print(f"  {i+1}/{len(todo)} ok={ok} err={err}")

print(f"Done: ok={ok} err={err}")
