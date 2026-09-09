# Trading Rule H1R2 来源合同与范围收缩整改记录

日期：2026-09-09（Asia/Shanghai）
状态：`SOURCE-CONTRACT-CORRECTION STAGED / 2020+ SCOPED / COMPILED NON-ACTIVE / REVIEW CHECKLIST PREPARED / HUMAN REVIEW DEFERRED TO SEPARATE SEAL PR`

## 1. 记录关系与已确认事实

本记录响应 PR #35 独立复审以及项目管理者随后提出的范围修正。它 supersede 本 PR 中关于“直接修改 `v20260909-h1-compiled`”和“必须先闭合 1998 年 ST 起点”的当前执行假设，但不改写 PR #32/#33 已接受的历史要求和实现记录。

已确认：

- 执行基线为 `main@a797f1186209e7548167e2fa652ce78715f24180`；当前 ACTIVE 仍为旧的 `v20260824-compiled` / `COMPILED`。
- `configs/trading_rules/versions/v20260909-h1-compiled/rules.yaml` 已恢复到 `main` 的原始字节。其 manifest-style SHA-256 为 `75d21777f1f135c47b963868641dfffc5428c5c5d897e17480a91ebaec1edd51`；本 PR 不再修改该目录。
- 新建 `configs/trading_rules/versions/v20260909-h1r2-compiled/rules.yaml`，dataset version 为 `2026-09-09.2`，共 14 条，仍为 `COMPILED`、非 `ACTIVE`。其 manifest-style SHA-256 为 `6cb355fdaf5f9cc5fe2da09d9d0ecce18ee1e04378a42a25515364fd4019c55f`。
- H1R2 的研究真值范围是 `2020-01-01` 以后；主板普通/ST、主板 IPO 旧制度、创业板改革前和科创板的更早 `effective_from` 已收窄到该范围。创业板 2020-08-24、主板 2023-04-10、主板 ST 2026-07-06 等必要切换仍保留。
- H1R2 不把 1998 年 SH/SZ ST 起点写入候选、bundle 或本轮放行条件。完整 pre-2020 历史重建保留为后续非阻断 backlog；这不是对 2020+ PIT 证据要求的放宽。
- 当前输入 bundle 仍未封印，也未写入 `configs/trading_rules/evidence/`，未创建 REVIEWED 版本，未切换 ACTIVE，未启动或消耗 Formal Production B1-B7。

## 2. 来源合同修正

`RULE_EVIDENCE_BUNDLE.v1` 只把 `source_url`、原始字节 hash/size、role 和 artifact kind 写入 canonical bundle，不把 catalog 的 `download_url` 自动带入封印内容。因此 H1R2 采用最小且可审计的修正：

1. `source_ref` 中声明的 URL 与 evidence input 的 `source_url` 必须是 `artifact_path` 对应原始 HTML/PDF/DOCX 的实际下载 URL；
2. 官方发布页若只是 locator/notice page，只能在 source catalog 的 `source_page_url` 中记录页面与附件的关系，不能用页面 URL 冒充附件字节来源；
3. 五类已发现的链接附件均已直接绑定：SSE 2026 规则 DOCX、SZSE 2020 创业板特别规定 PDF，以及 BSE 的三份规则 DOCX；catalog 同时保留附件 HTTP 200、发布页 HTTP 状态、最终 URL、大小和 SHA-256；
4. 不扩展 `RULE_EVIDENCE_BUNDLE.v1` schema，不把 locator page 和附件 bytes 合并成一个来源，不使用 browser-resolved DOM、截图、搜索摘要或手工摘录替代原始文件。

H1R2 输入校验结果：19 个唯一 source URL、19 个去重 raw artifact、1,702,416 bytes；canonical bundle 16,557 bytes，SHA-256 为 `14f09ed0707b0ef1d84ae2dbe880f87bdd186d0c21e61e6387f26fa41bd403d0`。这些是未封印的候选校验值，不是 REVIEWED provenance。

本次复审整改还删除了 `MAIN_BOARD_ST_HISTORICAL_SZ` 输入中的重复 `artifact_path` key，并新增递归 JSON duplicate-key 回归断言；H1R1 的 `direct_06.pdf` / `direct_07.html` 已从当前分支移除，不再保留为 H1R2 的孤立 pre-2020 负载。

## 3. 当前审阅分层

审阅对象改为 [`TradingRule_H1_人工审阅操作表_20260909.md`](TradingRule_H1_人工审阅操作表_20260909.md) 中的 H1R2 候选。该表已准备好，但 14/14 人工原文审阅属于合并后的独立 evidence/seal PR，不是 PR #35 的合并前置条件。PR #35 当前只需要独立 Reviewer 核验：

- 新旧 COMPILED candidate 的不可变性与版本分离；
- H1R2 的 2020+ 范围、必要制度切换和 fail-closed 边界；
- `source_ref`/`source_url` 与实际归档 bytes 的一一绑定、重复 JSON key 已清理；
- 19 个 source artifact、catalog、bundle 统计和三平台 CI。

合并后的独立 evidence/seal PR 再由项目管理者/独立 Reviewer 实际打开每份 raw artifact，逐行填写 14 条：

- 数值或语义是否与正文一致；
- 2020+ 生效区间、交易所和代码范围是否一致；
- 2020-08-24、2023-04-10、2026-07-06 等候选明确写出的制度切换是否有原文支持；
- 每个 `RULE` 来源是否真的是包含所声明条款的正文，而不是只有 locator page；
- BSE 的 venue、上市日语义和真实 `listing_date` 依赖是否成立。

PR #35 不以 14/14 `APPROVE` 作为合并条件；但在后续独立 evidence/seal PR 中，只有 14/14 `APPROVE`、边界测试闭合且独立 Reviewer 接受并合并后，才能运行 candidate seal。该独立 PR 仍必须重新核验旧 candidate、H1R2 candidate、旧 ACTIVE 和 bundle 的不可变性。

## 4. 后续工作顺序

1. 在 PR #35 中完成独立 Reviewer 对 source contract、范围、不可变性和 CI 的核验，保持 Draft，不在本 PR seal 或切 ACTIVE；
2. CI 与独立复审通过后合并 PR #35；再更新或 supersede Issue #34，使其指向 H1R2 candidate/hash；
3. 从合并后的最新 clean `main` 开单独 evidence/seal PR，重新冻结 bundle，完成人工 14/14 审阅和一次性 `--candidate` seal；
4. REVIEWED evidence/seal PR 独立审阅并合并后，才允许按 Formal baseline 重新做 SDK/runtime/网络/query preflight；在此之前 Formal B1-B7 仍禁止。

账号、密码、IP、端口、Token、Cookie、profile、原始 Provider 输出和专有 SDK/runtime 文件均不得进入 GitHub。
