#!/usr/bin/env python3
"""
Hard-coded JSON validation for pokemon-tcg-wiki skill outputs.

Validates agent outputs against schemas for the 4-stage Pipeline:
  Stage 1: query_plan.json
  Stage 2: card_result.json / rule_result.json
  Stage 3: analysis.json
  Stage 4: verdict (text with checksum line)

No external dependencies — uses only Python standard library.

Usage:
  python3 validation.py --schema query-plan < query_plan.json
  python3 validation.py --schema card-result < card_result.json
  python3 validation.py --schema rule-result < rule_result.json
  python3 validation.py --schema analysis < analysis.json
  python3 validation.py --full-pipeline query.json card.json rule.json analysis.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional


# ── Schema definitions ─────────────────────────────────────────────

QUERY_PLAN_SCHEMA = {
    "required": ["intent", "entities", "filters"],
    "types": {
        "intent": str,
        "entities": list,
        "filters": dict,
    },
    "enums": {
        "intent": ["card_lookup", "rule_search", "format_check", "mixed"],
    },
    "item_types": {
        "entities": str,
    },
}

CARD_RESULT_SCHEMA = {
    "required": ["id", "name", "supertype", "types"],
    "types": {
        "id": str,
        "name": dict,
        "supertype": str,
        "types": list,
        "subtypes": (list, type(None)),
        "hp": (int, type(None)),
        "stage": (str, type(None)),
        "evolvesFrom": (str, type(None)),
        "evolvesTo": (list, type(None)),
        "attacks": list,
        "abilities": list,
        "weaknesses": list,
        "resistances": list,
        "retreatCost": (int, type(None)),
        "rarity": (str, type(None)),
        "set": (dict, type(None)),
        "regulationMark": (str, type(None)),
        "legal": (dict, type(None)),
        "translation": (dict, type(None)),
        "error": (str, type(None)),
    },
    "enums": {
        "supertype": ["Pokémon", "Trainer", "Energy"],
    },
    "item_types": {
        "types": str,
    },
}

RULE_RESULT_SCHEMA = {
    "required": ["title", "content", "lang", "section"],
    "types": {
        "title": str,
        "content": str,
        "lang": str,
        "section": str,
        "source_file": (str, type(None)),
    },
    "enums": {
        "lang": ["zh", "en", "ja"],
    },
}

ANALYSIS_SCHEMA = {
    "required": ["answer", "sources", "confidence"],
    "types": {
        "answer": str,
        "sources": list,
        "confidence": (int, float),
    },
    "item_types": {
        "sources": dict,
    },
}

# Source sub-schema for analysis.sources[]
SOURCE_SCHEMA = {
    "required": ["type", "id"],
    "types": {
        "type": str,
        "id": str,
        "relevance": (int, float, type(None)),
    },
    "enums": {
        "type": ["card", "rule", "format"],
    },
}

# ── Validation Result ──────────────────────────────────────────────


class ValidationResult:
    """Collects validation errors and warnings."""

    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    def summary(self) -> str:
        lines = []
        stage_count = 3  # query_plan + card/rule results + analysis
        passed = stage_count - len(self.errors) if len(self.errors) <= stage_count else 0
        if self.errors:
            lines.append(f"[校验: FAIL | {passed}/{stage_count}]")
            for e in self.errors:
                lines.append(f"  [E] {e}")
        else:
            lines.append(f"[校验: PASS | {stage_count}/{stage_count}]")
        if self.warnings:
            for w in self.warnings:
                lines.append(f"  [W] {w}")
        return "\n".join(lines)

    def verdict_line(self) -> str:
        """Return the single-line verdict for appending to Stage 4 output."""
        stage_count = 3
        passed = stage_count - len(self.errors) if len(self.errors) <= stage_count else 0
        if self.errors:
            return f"[校验: FAIL | {passed}/{stage_count}]"
        if self.warnings:
            return f"[校验: PASS | {stage_count}/{stage_count}] (warnings: {len(self.warnings)})"
        return f"[校验: PASS | {stage_count}/{stage_count}]"


# ── Generic Schema Validator ───────────────────────────────────────


def _check_type(
    path: str,
    value: Any,
    expected: type | tuple[type, ...],
    result: ValidationResult,
) -> bool:
    """Check if value matches expected type(s)."""
    if isinstance(expected, tuple):
        if not isinstance(value, expected):
            type_names = " or ".join(
                t.__name__ if t is not type(None) else "None"
                for t in expected
            )
            result.add_error(
                f"{path}: expected {type_names}, got {type(value).__name__}"
            )
            return False
    else:
        if not isinstance(value, expected):
            result.add_error(
                f"{path}: expected {expected.__name__}, got {type(value).__name__}"
            )
            return False
    return True


def validate_object(
    obj: dict,
    schema: dict,
    result: ValidationResult,
    path: str = "root",
) -> None:
    """Validate a dict object against a schema definition."""
    if not isinstance(obj, dict):
        result.add_error(f"{path}: expected object, got {type(obj).__name__}")
        return

    # Check required fields
    for field in schema.get("required", []):
        if field not in obj:
            result.add_error(f"{path}: missing required field '{field}'")

    # Check types
    for field, expected_type in schema.get("types", {}).items():
        if field in obj and obj[field] is not None:
            _check_type(f"{path}.{field}", obj[field], expected_type, result)

    # Check enums
    for field, allowed in schema.get("enums", {}).items():
        if field in obj and obj[field] is not None and obj[field] not in allowed:
            result.add_error(
                f"{path}.{field}: invalid value '{obj[field]}', "
                f"must be one of {allowed}"
            )

    # Check array item types
    for field, item_type in schema.get("item_types", {}).items():
        if field in obj and isinstance(obj[field], list):
            for i, item in enumerate(obj[field]):
                if not isinstance(item, item_type):
                    result.add_error(
                        f"{path}.{field}[{i}]: expected {item_type.__name__}, "
                        f"got {type(item).__name__}"
                    )


# ── Domain-Specific Validators ─────────────────────────────────────


def validate_query_plan(
    data: dict, result: Optional[ValidationResult] = None
) -> ValidationResult:
    """Validate a QueryPlan output (Stage 1)."""
    result = result or ValidationResult()
    validate_object(data, QUERY_PLAN_SCHEMA, result)

    if not isinstance(data, dict):
        return result

    entities = data.get("entities", [])
    if isinstance(entities, list) and len(entities) == 0:
        result.add_error("entities: must contain at least 1 item")

    for i, e in enumerate(entities):
        if isinstance(e, str) and not e.strip():
            result.add_error(f"entities[{i}]: empty string")

    return result


def validate_card_result(
    data: dict, result: Optional[ValidationResult] = None
) -> ValidationResult:
    """Validate a CardResult output (Stage 2)."""
    result = result or ValidationResult()
    validate_object(data, CARD_RESULT_SCHEMA, result)

    if not isinstance(data, dict):
        return result

    # If no error, require name.zh
    if data.get("error") is None:
        name = data.get("name", {})
        if isinstance(name, dict):
            if not name.get("zh"):
                result.add_error("name.zh: required for resolved card")
        else:
            result.add_error("name: expected object with zh field")

        if not data.get("id"):
            result.add_error("id: required for resolved card")

    # Check legal object
    legal = data.get("legal", {})
    if isinstance(legal, dict):
        for field in ["standard", "expanded"]:
            if field not in legal:
                result.add_warning(f"legal.{field}: missing")

    # Check translation metadata
    translation = data.get("translation", {})
    if isinstance(translation, dict):
        allowed = {"zh-mod", "llm", "mixed"}
        for k in ["name", "attacks"]:
            v = translation.get(k)
            if v and v not in allowed:
                result.add_warning(f"translation.{k}: unexpected value '{v}'")

    return result


def validate_rule_result(
    data: dict, result: Optional[ValidationResult] = None
) -> ValidationResult:
    """Validate a RuleResult output (Stage 2)."""
    result = result or ValidationResult()
    validate_object(data, RULE_RESULT_SCHEMA, result)

    if not isinstance(data, dict):
        return result

    content = data.get("content", "")
    title = data.get("title", "")

    if not content.strip():
        result.add_error("content: must not be empty")
    if not title.strip():
        result.add_error("title: must not be empty")

    return result


def validate_analysis(
    data: dict, result: Optional[ValidationResult] = None
) -> ValidationResult:
    """Validate an Analysis output (Stage 3)."""
    result = result or ValidationResult()
    validate_object(data, ANALYSIS_SCHEMA, result)

    if not isinstance(data, dict):
        return result

    # Validate sources
    sources = data.get("sources", [])
    if isinstance(sources, list):
        if len(sources) == 0:
            result.add_error("sources: must contain at least 1 source")
        for i, src in enumerate(sources):
            if isinstance(src, dict):
                src_result = ValidationResult()
                validate_object(src, SOURCE_SCHEMA, src_result, path=f"sources[{i}]")
                result.errors.extend(src_result.errors)
                result.warnings.extend(src_result.warnings)

    # Confidence range check
    confidence = data.get("confidence")
    if isinstance(confidence, (int, float)):
        if confidence < 0 or confidence > 1:
            result.add_warning(
                f"confidence: out of range [0,1], got {confidence}"
            )
        if confidence < 0.5:
            result.add_warning(
                f"confidence: low ({confidence}), consider flagging uncertainty"
            )

    return result


# ── Full Pipeline Validator ────────────────────────────────────────


def validate_full_pipeline(
    query_plan: dict,
    card_results: list[dict],
    rule_results: list[dict],
    analysis: dict,
) -> ValidationResult:
    """Validate all stages of a complete pipeline run."""
    result = ValidationResult()

    # Stage 1
    s1 = validate_query_plan(query_plan)
    result.errors.extend(s1.errors)
    result.warnings.extend(s1.warnings)

    # Stage 2
    for i, card in enumerate(card_results):
        s2c = validate_card_result(card)
        for e in s2c.errors:
            result.add_error(f"card[{i}]: {e}")
        for w in s2c.warnings:
            result.add_warning(f"card[{i}]: {w}")

    for i, rule in enumerate(rule_results):
        s2r = validate_rule_result(rule)
        for e in s2r.errors:
            result.add_error(f"rule[{i}]: {e}")
        for w in s2r.warnings:
            result.add_warning(f"rule[{i}]: {w}")

    # Stage 3
    s3 = validate_analysis(analysis)
    result.errors.extend(s3.errors)
    result.warnings.extend(s3.warnings)

    return result


# ── CLI ────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Pokemon TCG validation")
    parser.add_argument(
        "--schema",
        choices=["query-plan", "card-result", "rule-result", "analysis"],
        help="Schema to validate against",
    )
    parser.add_argument(
        "--full-pipeline",
        nargs=4,
        metavar=("QUERY", "CARD", "RULE", "ANALYSIS"),
        help="Validate full pipeline: query.json card.json rule.json analysis.json",
    )
    args = parser.parse_args()

    if args.full_pipeline:
        files = {}
        for label, path in zip(
            ["query", "card", "rule", "analysis"], args.full_pipeline
        ):
            with open(path, "r", encoding="utf-8") as f:
                files[label] = json.load(f)

        result = validate_full_pipeline(
            files["query"],
            files["card"] if isinstance(files["card"], list) else [files["card"]],
            files["rule"] if isinstance(files["rule"], list) else [files["rule"]],
            files["analysis"],
        )
        print(result.summary())
        sys.exit(0 if result.is_valid() else 1)

    if args.schema:
        data = json.load(sys.stdin)
        validators = {
            "query-plan": validate_query_plan,
            "card-result": validate_card_result,
            "rule-result": validate_rule_result,
            "analysis": validate_analysis,
        }
        result = validators[args.schema](data)
        print(result.summary())
        sys.exit(0 if result.is_valid() else 1)

    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
