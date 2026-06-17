# Pokemon TCG Wiki Hermes — 安装指南

> 将本项目安装到 Hermes Agent 作为可用 Skill。

## 前置条件

- Python 3.11+
- Git
- 网络连接（首次同步需下载约 200MB 数据）

## 安装步骤

```bash
# 1. 克隆仓库（如尚未克隆）
git clone git@github.com:RogerZhang58/pokemon-tcg-wiki.git
cd pokemon-tcg-wiki

# 2. 安装 Python 依赖
pip install -r requirements.txt

# 3. 同步数据源（首次约 5-10 分钟）
python tools/sync_data.py

# 4. 合并简中卡牌翻译
python tools/build_cards.py

# 5. 构建搜索索引
python tools/build_indices.py

# 6. 补全卡牌详情（可选，约 15 分钟，8 线程并发）
python tools/enrich_cards.py
# 补全后需重建索引：
python tools/build_cards.py && python tools/build_indices.py

# 7. 注册 Hermes Skill
cp skill/pokemon-tcg.md ~/.hermes/skills/
```

## 验证安装

```bash
python tools/pipeline.py "皮卡丘 的弱点是什么"
python tools/card_search.py "皮卡丘VMAX"
python tools/rule_search.py "特殊状态"
python tools/format_check.py --list standard --banned
```

## 数据更新

定期运行以获取最新卡牌和翻译：

```bash
python tools/sync_data.py          # 拉取最新数据
python tools/build_cards.py        # 重新合并
python tools/build_indices.py      # 重建索引
```

## 安装 Prompt（喂给 Hermes）

```
请在本地安装 pokemon-tcg-wiki 项目：

1. cd ~/pokemon-tcg-wiki（如未克隆：git clone git@github.com:RogerZhang58/pokemon-tcg-wiki.git）
2. pip install -r requirements.txt
3. python tools/sync_data.py（首次约 10 分钟，耐心等待）
4. python tools/build_cards.py
5. python tools/build_indices.py
6. python tools/enrich_cards.py（可选，补全卡牌详情）
7. cp skill/pokemon-tcg.md ~/.hermes/skills/
8. 测试：python tools/pipeline.py "皮卡丘"
```
