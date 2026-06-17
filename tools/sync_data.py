#!/usr/bin/env python3
"""
Sync upstream data sources: TCGdex + PTCG Live zh-mod.

Clones (or pulls) both repos with shallow depth, extracts only the
data directories we need. No git submodule — we own the copies.

Usage:
    python3 sync_data.py              # Full sync (clone or pull)
    python3 sync_data.py --tcgdex     # TCGdex only
    python3 sync_data.py --zhmod      # zh-mod only
    python3 sync_data.py --force      # Force re-clone (discard local changes)
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# Add tools dir to path for utils import
TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

from utils import RAW_DIR, DATA_DIR, CARDS_DIR, SETS_DIR, ZH_MOD_DIR

# ── Repo definitions ───────────────────────────────────────────────

TCGDEX_REPO = "https://github.com/tcgdex/cards-database.git"
TCGDEX_CACHE = RAW_DIR / ".cache" / "tcgdex"

ZHMOD_REPO = "https://github.com/Hill-98/ptcg-live-zh-mod.git"
ZHMOD_CACHE = RAW_DIR / ".cache" / "zhmod"


def run(cmd: list[str], cwd: Path = None) -> tuple[int, str, str]:
    """Run a command, return (exit_code, stdout, stderr)."""
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    return result.returncode, result.stdout, result.stderr


def clone_or_pull(repo_url: str, cache_dir: Path, force: bool = False) -> bool:
    """Clone a repo to cache_dir, or pull if it already exists."""
    if force and cache_dir.exists():
        print(f"  Removing {cache_dir} for force re-clone...")
        shutil.rmtree(cache_dir)

    if cache_dir.exists():
        print(f"  Pulling {cache_dir}...")
        code, out, err = run(["git", "pull", "--ff-only"], cwd=cache_dir)
        if code != 0:
            print(f"  Pull failed: {err}")
            return False
        print(f"  {out.strip()}")
        return True
    else:
        print(f"  Cloning {repo_url} → {cache_dir}...")
        cache_dir.parent.mkdir(parents=True, exist_ok=True)
        code, out, err = run([
            "git", "clone", "--depth", "1",
            "--filter=blob:none",
            repo_url, str(cache_dir),
        ])
        if code != 0:
            print(f"  Clone failed: {err}")
            return False
        print(f"  Clone complete")
        return True


def sync_tcgdex(force: bool = False) -> bool:
    """Sync TCGdex card data via REST API with pagination."""
    import json as _json
    import urllib.request
    import time

    print("\n═══ Syncing TCGdex (API, paginated) ═══")
    API_BASE = "https://api.tcgdex.net/v2/en"

    def api_get(url: str) -> dict | list:
        for attempt in range(3):
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "pokemon-tcg-wiki/1.0"}
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return _json.loads(resp.read().decode())
            except Exception as e:
                if attempt == 2:
                    raise
                time.sleep(1)

    ITEMS_PER_PAGE = 100
    page = 1
    card_count = 0
    set_cards = {}  # set_id → [card_ids]

    print("  Fetching cards (paginated, 100/page)...")
    while True:
        url = f"{API_BASE}/cards?pagination:page={page}&pagination:itemsPerPage={ITEMS_PER_PAGE}"
        cards = api_get(url)
        if not cards:
            break

        for card in cards:
            card_id = card.get("id", "")
            if not card_id:
                continue

            # Save card
            dest = CARDS_DIR / f"{card_id}.json"
            with open(dest, "w", encoding="utf-8") as f:
                _json.dump(card, f, ensure_ascii=False)
            card_count += 1

            # Track by set
            set_id = card.get("set", {}).get("id", "unknown") if isinstance(card.get("set"), dict) else "unknown"
            set_cards.setdefault(set_id, []).append(card_id)

        print(f"    Page {page}: {len(cards)} cards (total: {card_count})")
        if len(cards) < ITEMS_PER_PAGE:
            break
        page += 1
        time.sleep(0.3)

    # Get set metadata
    print(f"  {card_count} cards downloaded. Fetching set metadata...")
    sets = api_get(f"{API_BASE}/sets")
    for s in sets:
        set_id = s.get("id", "")
        if not set_id:
            continue
        set_meta = {
            "id": set_id,
            "name": s.get("name", ""),
            "logo": s.get("logo", ""),
            "symbol": s.get("symbol", ""),
            "cardCount": s.get("cardCount", {}),
            "cards": sorted(set_cards.get(set_id, [])),
        }
        meta_path = SETS_DIR / f"{set_id}.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            _json.dump(set_meta, f, ensure_ascii=False, indent=2)

    print(f"  Synced {card_count} cards from {len(sets)} sets")
    return True


def sync_zhmod(force: bool = False) -> bool:
    """Sync PTCG Live zh-mod: extract databases_zh-CN/ + dictionary.json + text_zh-CN/."""
    print("\n═══ Syncing PTCG Live zh-mod ═══")

    if not clone_or_pull(ZHMOD_REPO, ZHMOD_CACHE, force):
        return False

    # Copy databases_zh-CN/
    src_db = ZHMOD_CACHE / "databases_zh-CN"
    if src_db.exists():
        for f in src_db.glob("*.json"):
            shutil.copy2(f, ZH_MOD_DIR / "databases_zh-CN" / f.name)
        db_count = len(list(src_db.glob("*.json")))
        print(f"  Synced {db_count} database files")
    else:
        print(f"  WARNING: databases_zh-CN/ not found")

    # Copy dictionary.json (Pokemon names EN→ZH)
    dict_src = ZHMOD_CACHE / "dictionary.json"
    if dict_src.exists():
        shutil.copy2(dict_src, ZH_MOD_DIR / "dictionary.json")
        print(f"  Synced dictionary.json (Pokémon names)")
    else:
        print(f"  WARNING: dictionary.json not found")

    # Copy text_zh-CN/
    src_text = ZHMOD_CACHE / "text_zh-CN"
    if src_text.exists():
        for f in src_text.glob("*.json"):
            shutil.copy2(f, ZH_MOD_DIR / "text_zh-CN" / f.name)
        text_count = len(list(src_text.glob("*.json")))
        print(f"  Synced {text_count} text files")
    else:
        print(f"  WARNING: text_zh-CN/ not found")

    # Copy databases/ (EN originals for hash→cardID mapping)
    src_db_en = ZHMOD_CACHE / "databases"
    if src_db_en.exists():
        for f in src_db_en.glob("*.json"):
            dest = ZH_MOD_DIR / f.name
            if not dest.exists():
                shutil.copy2(f, dest)
        print(f"  Synced EN database files for hash mapping")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Sync TCGdex + PTCG Live zh-mod data"
    )
    parser.add_argument("--tcgdex", action="store_true", help="Sync TCGdex only")
    parser.add_argument("--zhmod", action="store_true", help="Sync zh-mod only")
    parser.add_argument(
        "--force", action="store_true",
        help="Force re-clone (discard local cache)"
    )
    args = parser.parse_args()

    # Default: sync both
    sync_all = not args.tcgdex and not args.zhmod

    success = True

    if sync_all or args.tcgdex:
        if not sync_tcgdex(args.force):
            success = False

    if sync_all or args.zhmod:
        if not sync_zhmod(args.force):
            success = False

    if success:
        print("\n═══ Sync complete ═══")
    else:
        print("\n═══ Sync completed with errors ═══")
        sys.exit(1)


if __name__ == "__main__":
    main()
