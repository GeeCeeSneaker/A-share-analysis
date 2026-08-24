# ADR-011: 交易制度事实的版本化数据层（Trading Rule Data SoR）

- 状态：ACCEPTED
- 日期：2026-08-24
- 依据：审计 R4-A2.3 开发工作要求 P0-06/P0-07，§8
- 影响契约：§13 Trading Rules、限价验证器 —— C2 级变化（按管理总册 C2 流程登记：DM-CR-20260824-005）

## 背景

原实现把制度事实（主板 ±10%、ST ±5%、创业板注册制前后 ±10%→±20%、科创板 ±20%、北交所 ±30%、IPO 首日 +44%/-36%、首 5 日无限制、生效日期窗口、板别映射）硬编码在 Python（`trading_rule.py` 的 rate 表与 `validators.py` 的 `BOARD_LIMIT_RATES`）。这违反"制度事实必须版本化、可审、PIT"的原则，且首 N 日判定用过"日历天 × 2"近似。

## 决策

### 1. 制度事实迁入数据层

`configs/trading_rules/a_share_limit_v1.yaml`（version/source_version/review_status + rules[]，每条规则含 rule_id/board/exchanges/code_patterns/effective_from/effective_to/st_state/listing_age_rule/up_rate/down_rate/tick_size/rounding_mode/source_ref）。

- 规则文件与 golden dataset 同样走 COMPILED → REVIEWED 审阅流；
- Python（`ashare_state.spike.trading_rule`）只负责：load、schema validate、PIT 匹配、冲突检测、resolve、Decimal 限价计算（ROUND_HALF_UP）；
- Python 源码中出现制度费率字面量即测试失败（test_trading_rule_data.py 静态断言）。

### 2. Fail-closed 语义（RULE_UNRESOLVED）

以下情况一律 `RuleUnresolvedError`，绝不静默退化（如退化为主板 10%）：

- 0 条匹配规则（未知板别/日期在所有生效窗口之外/未知交易所）；
- >1 条同等有效规则（含配置重叠错误）；
- 首上市期规则存在但调用方未提供 listing_date + 交易日历（拒绝猜测）；
- 日历缺失行（listing 或 trade date 不在日历中）。

### 3. 首 N 日 = 交易 session 序号

`first_n_sessions(trade_date, listing_date, calendar, n)`：以 PIT 交易日历的 **session index** 判定（上市日为第 1 个 session），绝不用日历天近似。已测春节/国庆长假、跨周末、第 5/6 个 session、日历缺行（fail-closed）。

- listing 早于日历窗口起点 → 视为早已度过首 N 日（False）；
- 上市日当天若是 IPO_DAY 规则（主板 2014-2023 的 +44/-36）优先于 FIRST_5 规则。

### 4. 调用面

- `resolve_trading_rule(exchange, code, trade_date, is_st, listing_date, calendar)`：完整 PIT 解析（金价 limit case 用，listing_date 必须来自同一 PIT context 的 hist master，日历来自独立 exchange）；
- `resolve_limit_regime(exchange, code, trade_date, is_st)`：供"该行自带 HIGH_LIMITED（必有涨跌幅）"的结构验证（B3/BJ 语义证明）选择 NONE listing-age 规则；
- `TradingRule.limit_prices(pre_close)`：Decimal ROUND_HALF_UP 计算（tick 量化）。

## 后果

- 制度变更（未来交易所规则调整）= 数据文件新版本 + 审阅，不动代码；
- `validators.validate_limit_rule` 重写为 v3：按行内 TRADE_DATE 做 PIT 解析，规则失败收集为 RULE_UNRESOLVED 违规（fail closed）；
- 旧 `BOARD_LIMIT_RATES`/`board_of`/`expected_limit_price` 已删除。
