# Claude Code 策略研究流程

目标：比较多个单标的策略，找到当前项目里最值得继续研究的策略组合。

## 默认步骤

1. 选择标的和区间。

示例：

```text
标的：NDX / US / INDEX
区间：2024-01-01 至 2026-05-01
```

2. 运行多策略对比。

```bash
python main.py strategy-report \
  --strategies kdj bollinger ma_cross macd rsi dca \
  --symbol NDX \
  --market US \
  --asset-type INDEX \
  --start 2024-01-01 \
  --end 2026-05-01 \
  --output reports/ndx_strategy_report.md \
  --json-output reports/ndx_strategy_report.json
```

3. 运行策略搜索。

```bash
python main.py strategy-search \
  --symbol NDX \
  --market US \
  --asset-type INDEX \
  --start 2024-01-01 \
  --end 2026-05-01 \
  --objective composite \
  --output reports/ndx_strategy_search.md \
  --json-output reports/ndx_strategy_search.json
```

4. 读取 JSON，输出中文研究结论：

- 最优策略是谁。
- 它相对买入持有有什么优势和缺点。
- 最大回撤是否可以接受。
- 信号是否过于稀疏或过于频繁。
- 下一步应该调整哪些参数。

## 研究原则

- 单标的择时策略不要和 qlib 官方组合策略直接混排。
- 多标的股票池扩大后，再研究 Alpha158、DatasetH、TopkDropoutStrategy。
- 任何“最优策略”都只是历史区间内的结果，需要滚动验证。
