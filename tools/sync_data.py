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
    """Sync TCGdex cards-database: extract data/ → raw/data/."""
    print("\n═══ Syncing TCGdex ═══")

    if not clone_or_pull(TCGDEX_REPO, TCGDEX_CACHE, force):
        return False

    # TCGdex stores cards in data/<SetName>/<cardId>.json
    # But newer versions may use different structure. Check common patterns.
    tcgdex_data = TCGDEX_CACHE / "data"

    if not tcgdex_data.exists():
        print(f"  ERROR: 'data/' not found in TCGdex repo at {TCGDEX_CACHE}")
        print(f"  Contents: {list(TCGDEX_CACHE.iterdir())[:10]}")
        return False

    # Count and copy card files
    card_count = 0
    set_count = 0

    for set_dir in sorted(tcgdex_data.iterdir()):
        if not set_dir.is_dir():
            continue
        set_count += 1

        # Copy set metadata
        set_meta = {
            "id": set_dir.name,
            "cards": [],
        }

        for card_file in sorted(set_dir.glob("*.json")):
            card_count += 1
            dest = CARDS_DIR / card_file.name
            shutil.copy2(card_file, dest)
            set_meta["cards"].append(card_file.stem)

        # Save set metadata
        import json
        set_meta_path = SETS_DIR / f"{set_dir.name}.json"
        with open(set_meta_path, "w", encoding="utf-8") as f:
            json.dump(set_meta, f, ensure_ascii=False, indent=2)

    print(f"  Synced {card_count} cards from {set_count} sets")
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
