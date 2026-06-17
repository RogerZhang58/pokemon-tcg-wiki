#!/usr/bin/env python3
"""
Full-text rule search with language filtering and snippet highlighting.

Searches:
  - raw/rules/{zh,en}/*.md — parsed rule documents
  - zh-mod text_zh-CN/ — game text translations (special conditions, energy, etc.)

Usage:
    python3 rule_search.py "弱点 计算"
    python3 rule_search.py --lang zh "特殊状态"
    python3 rule_search.py --lang en "weakness calculation"
    python3 rule_search.py --section "damage" poison
"""

import argparse
import json
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

from utils import get_db, detect_language


def search_rules(
    query: str,
    lang: str = "",
    section: str = "",
    limit: int = 10,
) -> list[dict]:
    """Search rules with FTS5.

    Args:
        query: Search query
        lang: Filter by language (zh/en/ja), auto-detect if empty
        section: Filter by section (e.g., 'damage', 'special_conditions')
        limit: Max results

    Returns:
        List of rule dicts with snippet and relevance
    """
    conn = get_db()

    if not lang:
        lang = detect_language(query)

    safe_query = query.replace("'", "''")

    conditions = ["rules_fts MATCH ?"]
    params = [safe_query]

    if lang:
        conditions.append("r.lang = ?")
        params.append(lang)

    if section:
        conditions.append("r.section LIKE ?")
        params.append(f"%{section}%")

    where = " AND ".join(conditions)

    sql = f"""
        SELECT r.id, r.title, r.content, r.lang, r.section, r.file_path,
               snippet(rules_fts, 2, '<mark>', '</mark>', '...', 40) as snippet
        FROM rules r
        JOIN rules_fts ON r.rowid = rules_fts.rowid
        WHERE {where}
        LIMIT ?
    """
    params.append(limit)

    results = []
    try:
        cursor = conn.execute(sql, params)
        for row in cursor.fetchall():
            results.append({
                "id": row[0],
                "title": row[1],
                "content": row[2],
                "lang": row[3],
                "section": row[4],
                "file_path": row[5],
                "snippet": row[6],
            })
    except Exception as e:
        # Fallback: search without snippet
        fallback_sql = f"""
            SELECT r.id, r.title, r.content, r.lang, r.section, r.file_path
            FROM rules r
            JOIN rules_fts ON r.rowid = rules_fts.rowid
            WHERE {where}
            LIMIT ?
        """
        cursor = conn.execute(fallback_sql, params)
        for row in cursor.fetchall():
            # Simple highlighting
            content = row[2]
            q_lower = query.lower()
            idx = content.lower().find(q_lower)
            if idx >= 0:
                start = max(0, idx - 60)
                end = min(len(content), idx + len(query) + 60)
                snippet = content[start:end]
                if start > 0:
                    snippet = "..." + snippet
                if end < len(content):
                    snippet += "..."
            else:
                snippet = content[:200]

            results.append({
                "id": row[0],
                "title": row[1],
                "content": row[2],
                "lang": row[3],
                "section": row[4],
                "file_path": row[5],
                "snippet": snippet,
            })

    conn.close()
    return results


def format_rule(rule: dict) -> str:
    """Format a single rule result for terminal output."""
    lines = []
    lines.append(f"[{rule['lang'].upper()}] {rule['title']}")
    lines.append(f"  Section: {rule['section']}")
    lines.append(f"  {rule['snippet']}")
    if rule.get("file_path"):
        lines.append(f"  Source: {rule['file_path']}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Search Pokemon TCG rules"
    )
    parser.add_argument("query", help="Rule search query")
    parser.add_argument("--lang", "-l", help="Filter by language (zh/en/ja)")
    parser.add_argument("--section", "-s", help="Filter by section")
    parser.add_argument("--limit", "-n", type=int, default=10)
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--full", action="store_true",
                        help="Show full content, not snippets")
    args = parser.parse_args()

    results = search_rules(
        query=args.query,
        lang=args.lang,
        section=args.section,
        limit=args.limit,
    )

    if args.json:
        output = []
        for r in results:
            out = dict(r)
            if not args.full:
                out.pop("content", None)  # Don't send full content in JSON mode
                out["content_preview"] = r["content"][:500]
            output.append(out)
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        if not results:
            print("No rules found.")
            return
        print(f"Found {len(results)} rules:\n")
        for rule in results:
            if args.full:
                print(f"[{rule['lang'].upper()}] {rule['title']}")
                print(f"  Section: {rule['section']}")
                print(f"  {rule['content'][:1000]}")
                print()
            else:
                print(format_rule(rule))
                print()


if __name__ == "__main__":
    main()
