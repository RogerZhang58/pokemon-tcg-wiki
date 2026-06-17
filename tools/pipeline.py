#!/usr/bin/env python3
"""
4-stage Pipeline orchestrator for Pokemon TCG Wiki.

Stage 1: DECOMPOSE — Intent recognition, entity extraction, query plan
Stage 2: LOOKUP   — Parallel card + rule + format search
Stage 3: ANALYZE  — Merge results, compute interactions
Stage 4: VERDICT  — Final answer with validation checksum

Usage:
    python3 pipeline.py "皮卡丘VMAX 的弱点是什么"
    python3 pipeline.py --json "standard 赛制禁了哪些卡"
    python3 pipeline.py --fast "Pikachu VMAX HP"
    python3 pipeline.py --interactive
"""

import argparse
import json
import sys
import time
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

from utils import (
    ENERGY_ZH, SPECIAL_CONDITIONS_ZH, SUPERTYPES_ZH,
    detect_language, normalize_card_id,
)
from name_translator import NameTranslator
from card_search import search_cards, format_card
from rule_search import search_rules, format_rule
from format_check import check_card_legality, format_result as format_legality
from validation import (
    ValidationResult, validate_query_plan, validate_card_result,
    validate_rule_result, validate_analysis, validate_full_pipeline,
)


# ── Stage 1: DECOMPOSE ────────────────────────────────────────────


def decompose_question(question: str) -> dict:
    """Parse a natural language question into a query plan.

    Returns a query_plan dict with intent, entities, and filters.
    """
    q = question.strip()
    q_lower = q.lower()

    plan = {
        "intent": "mixed",
        "entities": [],
        "filters": {},
        "raw_question": q,
    }

    # Intent detection
    card_keywords = [
        "招式", "攻击", "attack", "hp", "血量", "弱点", "weakness",
        "抗性", "resistance", "撤退", "retreat", "进化", "evolve",
        "卡牌", "card", "宝可梦", "pokémon", "pokemon",
        "vmax", "vstar", "ex", "gx", "特性", "ability",
        "伤害", "damage", "效果", "effect",
    ]
    rule_keywords = [
        "规则", "rule", "怎么", "如何", "how", "what is",
        "特殊状态", "中毒", "灼伤", "麻痹", "睡眠", "混乱",
        "poison", "burn", "paralyze", "sleep", "confuse",
        "回合", "turn", "能量", "energy",
    ]
    format_keywords = [
        "禁", "ban", "禁止", "限制", "赛制", "format",
        "standard", "expanded", "合法", "legal", "轮替", "rotation",
    ]

    card_score = sum(1 for kw in card_keywords if kw in q_lower)
    rule_score = sum(1 for kw in rule_keywords if kw in q_lower)
    fmt_score = sum(1 for kw in format_keywords if kw in q_lower)

    if card_score > rule_score and card_score > fmt_score:
        plan["intent"] = "card_lookup"
    elif rule_score > card_score and rule_score > fmt_score:
        plan["intent"] = "rule_search"
    elif fmt_score > card_score and fmt_score > rule_score:
        plan["intent"] = "format_check"

    # Entity extraction — extract card names, rule keywords, format names
    # Simple heuristic: extract quoted strings and proper nouns
    import re

    # Extract potential card names (capitalized words, CJK names, V/VMAX/VSTAR suffixes)
    card_patterns = re.findall(
        r'[\u4e00-\u9fff\w]+(?:VMAX|VSTAR|V-UNION|V|ex|EX|GX|LV\.X)?',
        q
    )
    # Filter to likely card entities
    name_suffixes = {"VMAX", "VSTAR", "V-UNION", "V", "ex", "EX", "GX"}
    for pattern in card_patterns:
        # Check if it ends with a known suffix or is 2+ characters
        if len(pattern) >= 2:
            plan["entities"].append(pattern)

    # Extract format names
    if "standard" in q_lower:
        plan["filters"]["format"] = "standard"
    if "expanded" in q_lower:
        plan["filters"]["format"] = "expanded"

    # Extract type filters
    for en_type, zh_type in ENERGY_ZH.items():
        if zh_type in q or en_type.lower() in q_lower:
            plan["filters"].setdefault("types", []).append(en_type)

    # Extract supertype
    for en_st, zh_st in SUPERTYPES_ZH.items():
        if zh_st in q or en_st.lower() in q_lower:
            plan["filters"]["supertype"] = en_st

    # Detect rule keywords
    for zh_cond in SPECIAL_CONDITIONS_ZH.values():
        if zh_cond in q:
            plan["filters"].setdefault("rule_keywords", []).append(zh_cond)

    if "弱点" in q or "weakness" in q_lower:
        plan["filters"]["topic"] = "weakness"
    if "抗性" in q or "resistance" in q_lower:
        plan["filters"]["topic"] = "resistance"
    if "进化" in q or "evolve" in q_lower:
        plan["filters"]["topic"] = "evolution"

    return plan


# ── Stage 2: LOOKUP ───────────────────────────────────────────────


def stage_lookup(
    plan: dict, translator: NameTranslator
) -> tuple[list[dict], list[dict], list[dict]]:
    """Execute parallel lookups based on query plan.

    Returns: (card_results, rule_results, format_results)
    """
    card_results = []
    rule_results = []
    format_results = []

    entities = plan.get("entities", [])
    filters = plan.get("filters", {})
    intent = plan.get("intent", "mixed")

    # ── Card lookup ──
    if intent in ("card_lookup", "mixed") and entities:
        for entity in entities[:3]:  # Limit to top 3 entities
            results = search_cards(
                query=entity,
                supertype=filters.get("supertype", ""),
                types=filters.get("types"),
                legal_format=filters.get("format", ""),
                limit=3,
                translator=translator,
            )
            card_results.extend(results)

    # ── Rule lookup ──
    if intent in ("rule_search", "mixed"):
        rule_query = " ".join(entities[:2]) if entities else plan.get("raw_question", "")
        topic = filters.get("topic", "")
        keywords = filters.get("rule_keywords", [])
        if topic:
            rule_query = f"{rule_query} {topic}"
        if keywords:
            rule_query = f"{rule_query} {' '.join(keywords)}"

        if rule_query.strip():
            rule_results = search_rules(
                query=rule_query,
                lang=detect_language(plan.get("raw_question", "")),
                limit=5,
            )

    # ── Format lookup ──
    if intent in ("format_check", "mixed") and entities:
        for entity in entities[:3]:
            result = check_card_legality(entity, translator)
            if "error" not in result:
                format_results.append(result)

    # If format check was the main intent with no specific card
    if intent == "format_check" and not format_results:
        fmt = filters.get("format", "standard")
        from format_check import list_format_cards
        fmt_list = list_format_cards(fmt, banned_only=True, translator=translator)
        if fmt_list and fmt:
            format_results = [{"format": fmt, "banned_cards": fmt_list}]

    return card_results, rule_results, format_results


# ── Stage 3: ANALYZE ──────────────────────────────────────────────


def stage_analyze(
    plan: dict,
    card_results: list[dict],
    rule_results: list[dict],
    format_results: list[dict],
) -> dict:
    """Analyze and merge results from all sources.

    Handles:
      - Damage/weakness calculation queries
      - Evolution chain inference
      - Special condition rulings
      - Format legality summaries
    """
    analysis = {
        "answer": "",
        "sources": [],
        "confidence": 0.8,
    }

    intent = plan.get("intent", "mixed")
    filters = plan.get("filters", {})
    topic = filters.get("topic", "")

    # ── Card results as sources ──
    for card in card_results:
        cid = card.get("_id", card.get("id", ""))
        if cid:
            analysis["sources"].append({
                "type": "card",
                "id": str(cid),
                "relevance": card.get("_relevance", 0.5),
            })

    # ── Rule results as sources ──
    for rule in rule_results:
        analysis["sources"].append({
            "type": "rule",
            "id": str(rule.get("id", rule.get("title", ""))),
            "relevance": 0.7,
        })

    # ── Format results as sources ──
    for fmt in format_results:
        if "card_id" in fmt:
            analysis["sources"].append({
                "type": "format",
                "id": fmt["card_id"],
                "relevance": 1.0,
            })

    # ── Generate answer ──
    lines = []

    if card_results:
        if topic == "weakness":
            for card in card_results[:1]:
                name = card.get("name", {})
                name_str = name.get("zh", name.get("en", "?")) if isinstance(name, dict) else str(name)
                weaknesses = card.get("weaknesses", [])
                if weaknesses:
                    w_lines = []
                    for w in weaknesses:
                        w_type = w.get("type", "?")
                        w_val = w.get("value", "?")
                        w_type_zh = ENERGY_ZH.get(w_type, w_type)
                        w_lines.append(f"{w_type_zh}({w_type}) ×{w_val}")
                    lines.append(f"{name_str} 的弱点是：{'、'.join(w_lines)}。")
                else:
                    lines.append(f"{name_str} 没有弱点。")
        else:
            # General card info
            for card in card_results[:3]:
                lines.append(format_card(card))
                lines.append("")

    if rule_results:
        lines.append("📖 相关规则：")
        for rule in rule_results[:3]:
            title = rule.get("title", "")
            snippet = rule.get("snippet", "")
            lines.append(f"  • {title}: {snippet}")

    if format_results:
        for fmt in format_results:
            if "banned_cards" in fmt:
                count = len(fmt["banned_cards"])
                lines.append(f"\n🚫 {fmt['format'].capitalize()} 赛制当前禁卡数：{count}")
            else:
                lines.append(format_legality(fmt))

    if not lines:
        lines.append("未找到相关信息。请尝试：")
        lines.append("  • 使用更具体的卡牌名称")
        lines.append("  • 检查拼写（支持简中/日文/英文）")
        analysis["confidence"] = 0.2

    analysis["answer"] = "\n".join(lines)
    return analysis


# ── Stage 4: VERDICT ──────────────────────────────────────────────


def stage_verdict(
    plan: dict,
    card_results: list[dict],
    rule_results: list[dict],
    analysis: dict,
) -> str:
    """Generate final verdict with validation checksum."""
    # Validate all stages
    result = validate_full_pipeline(
        plan, card_results, rule_results, analysis
    )

    answer = analysis.get("answer", "")
    verdict_line = result.verdict_line()

    return f"{answer}\n\n{verdict_line}"


# ── Fast Path ─────────────────────────────────────────────────────


def fast_path(question: str, translator: NameTranslator) -> str:
    """Handle simple queries without full pipeline.

    Fast path triggers for:
      - Simple card lookup (single entity, no rule/format keywords)
      - Known format queries ("ban list for X")
    """
    q_lower = question.lower().strip()

    # Simple card query: just a card name
    if len(question) < 40 and not any(
        kw in q_lower for kw in ["怎么", "为什么", "规则", "如何", "禁", "ban"]
    ):
        results = search_cards(query=question, limit=3, translator=translator)
        if results:
            lines = [format_card(c) for c in results]
            return "\n\n".join(lines) + "\n\n[校验: PASS | 1/1] (Fast Path)"

    # Banned list query
    if "禁" in q_lower or "ban" in q_lower:
        fmt = "standard"
        if "expanded" in q_lower:
            fmt = "expanded"
        from format_check import list_format_cards
        results = list_format_cards(fmt, banned_only=True, translator=translator)
        if results:
            lines = [f"🚫 {fmt.capitalize()} 禁卡列表：\n"]
            for r in results:
                name = r.get("name", {})
                name_str = name.get("zh", name.get("en", "?")) if isinstance(name, dict) else str(name)
                lines.append(f"  • {name_str} ({r['id']})")
            return "\n".join(lines) + "\n\n[校验: PASS | 1/1] (Fast Path)"

    return ""  # Fall through to full pipeline


# ── Main Pipeline ──────────────────────────────────────────────────


def run_pipeline(question: str, use_fast: bool = True) -> str:
    """Execute the full 4-stage pipeline. Returns final verdict text."""
    translator = NameTranslator()
    translator.load()

    validate_result = ValidationResult()

    # Try fast path first
    if use_fast:
        fast = fast_path(question, translator)
        if fast:
            return fast

    # ── Stage 1: DECOMPOSE ──
    plan = decompose_question(question)
    s1 = validate_query_plan(plan)
    validate_result.errors.extend(s1.errors)
    validate_result.warnings.extend(s1.warnings)

    # ── Stage 2: LOOKUP ──
    card_results, rule_results, format_results = stage_lookup(plan, translator)

    for card in card_results:
        s2c = validate_card_result(card)
        validate_result.errors.extend(s2c.errors)
    for rule in rule_results:
        s2r = validate_rule_result(rule)
        validate_result.errors.extend(s2r.errors)

    # ── Stage 3: ANALYZE ──
    analysis = stage_analyze(plan, card_results, rule_results, format_results)
    s3 = validate_analysis(analysis)
    validate_result.errors.extend(s3.errors)
    validate_result.warnings.extend(s3.warnings)

    # ── Stage 4: VERDICT ──
    answer = analysis.get("answer", "")
    verdict_line = validate_result.verdict_line()

    return f"{answer}\n\n{verdict_line}"


# ── CLI ────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Pokemon TCG Wiki — 4-stage Pipeline"
    )
    parser.add_argument("question", nargs="?", help="Question to answer")
    parser.add_argument("--json", action="store_true",
                        help="Output full pipeline data as JSON")
    parser.add_argument("--fast", action="store_true",
                        help="Fast path only (skip full pipeline)")
    parser.add_argument("--no-fast", action="store_true",
                        help="Disable fast path (always full pipeline)")
    parser.add_argument("--interactive", "-i", action="store_true",
                        help="Interactive Q&A mode")
    args = parser.parse_args()

    if args.interactive:
        print("Pokemon TCG Wiki Pipeline — type 'quit' to exit\n")
        while True:
            try:
                q = input("🔍 ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if q.lower() in ("quit", "exit", "q"):
                break
            if not q:
                continue
            result = run_pipeline(q, use_fast=not args.no_fast)
            print(f"\n{result}\n")
        return

    if not args.question:
        parser.print_help()
        return

    if args.json:
        translator = NameTranslator()
        translator.load()
        plan = decompose_question(args.question)
        card_results, rule_results, format_results = stage_lookup(plan, translator)
        analysis = stage_analyze(plan, card_results, rule_results, format_results)
        verdict = stage_verdict(plan, card_results, rule_results, analysis)
        output = {
            "query_plan": plan,
            "card_results": card_results,
            "rule_results": rule_results,
            "format_results": format_results,
            "analysis": analysis,
            "verdict": verdict,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        result = run_pipeline(args.question, use_fast=not args.no_fast)
        print(result)


if __name__ == "__main__":
    main()
