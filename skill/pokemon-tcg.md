---
name: pokemon-tcg
description: >
  宝可梦卡牌全知识库助手。用于回答宝可梦卡牌（Pokémon TCG）相关问题：
  卡牌查询（简中/日/英）、规则检索、赛制合法性、禁限牌查询、
  弱点抗性计算、特殊状态裁定、进化链检索。
  当用户询问宝可梦卡牌相关问题时自动触发。
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [pokemon, tcg, card-game, knowledge-base]
    related_skills: []
---

# Pokemon TCG Wiki Hermes

宝可梦集换式卡牌游戏全知识库助手。

基于 TCGdex（结构化卡牌元数据）+ PTCG Live zh-mod（简中翻译，100% 卡名覆盖），
通过 4 阶段 Pipeline 回答宝可梦卡牌相关问题。

## 功能

- **卡牌查询**：简中/日文/英文名称检索，按属性/类型/系列过滤
- **规则检索**：官方规则全文搜索，特殊状态裁定，伤害/弱点计算
- **赛制查询**：Standard / Expanded 赛制合法性，禁限牌列表
- **进化链**：基础→一阶→二阶进化关系查询

## 触发方式

| 方式 | 示例 |
|------|------|
| 自动触发 | "皮卡丘VMAX的弱点""什么是进化规则""Standard禁了哪些卡" |
| 手动触发 | `/ptcg 皮卡丘VMAX` |

## Pipeline 架构

```
用户问题
├─[Fast Path]──► 简单查卡/查禁限 → 直接回答 + 校验
▼
Stage 1: DECOMPOSE — 意图识别 + 实体抽取
Stage 2: LOOKUP (并行: card_search + rule_search + format_check)
Stage 3: ANALYZE — 合并结果，数值计算
Stage 4: VERDICT — 最终回答 + [校验: PASS | N/N]
```

## 数据源

- **TCGdex** (MIT)：卡牌元数据（HP/属性/弱点/抗性/赛制）
- **PTCG Live zh-mod** (Hill-98/ptcg-live-zh-mod)：简中翻译（卡名 100% 覆盖）
- **官方规则 PDF**：待用户提供

## 使用注意

- 简中赛制/轮替使用国际版数据（TCGdex legal 字段），非简中特有规则
- 招式名/文本约 47% 已由社区翻译，未覆盖部分暂用英文
- 回答末尾的校验行格式：`[校验: PASS | 3/3]`

## 安装

```bash
cd pokemon-tcg-wiki
pip install -r requirements.txt
python tools/sync_data.py      # 同步卡牌数据
python tools/build_cards.py    # 合并简中翻译
python tools/build_indices.py  # 构建搜索索引
```

## 命令行测试

```bash
python tools/pipeline.py "皮卡丘VMAX 的弱点是什么"
python tools/card_search.py "皮卡丘VMAX"
python tools/rule_search.py "特殊状态 中毒"
python tools/format_check.py --card "皮卡丘VMAX"
```
