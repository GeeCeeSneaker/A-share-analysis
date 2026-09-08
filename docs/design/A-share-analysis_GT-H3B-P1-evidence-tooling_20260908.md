# GT-H3B-P1 原始证据工具实现说明（2026-09-08）

## 当前状态

本说明记录 P1 工具层的实现边界，不代表 125/125 官方证据已经获取，也不代表 GT-H3B 已经 seal。

- P0 existing-candidate promotion 已在 PR #24 的 run #391 通过三平台 CI；v5 ACTIVE 和 v4/v5/v6 versioned bytes 未在代码提交中改变。
- P1 已增加批量审阅输入的 expect_fields 禁止规则，并增加可重现的 EVIDENCE_BUNDLE 原始字节格式、创建/检查工具和测试。
- 真实官方证据 bytes、每案 evidence manifest、一次性 REVIEWED seal、独立 Reviewer 关闭和合并后的受控 promotion 仍是后续工作，不能由本工具层自动宣称完成。

## EVIDENCE_BUNDLE 合同

复合事实 case 使用 .zip 作为最小双证据容器：

1. manifest.json 的 format 必须是 GT-H3B-EVIDENCE-BUNDLE/v1。
2. 清单至少包含两条记录，每条记录写明 source_ref（HTTP(S) 官方 URL）、artifact_kind、member_name、实际 sha256 和 size。
3. 除 manifest.json 外的每个 ZIP member 都必须在清单中出现；review 工具会重新读取并计算每份 member 的 SHA256/长度。
4. bundle 不压缩，member 时间戳固定，创建操作 create-only；同输入重复创建应得到相同 bytes。
5. 审阅 manifest 中 kind 必须为 EVIDENCE_BUNDLE，并以 bundle_sources 再声明同顺序的 URL/kind 清单；review 工具会比较两份清单，防止只提交一个未绑定的链接包。
6. EVIDENCE_BUNDLE 本身不能嵌套 bundle；成员不允许绝对路径、.. 穿越、目录、加密或符号链接。

创建工具：

~~~text
python scripts/golden/evidence_bundle.py create \
  --input bundle_sources.json \
  --output composite.zip

python scripts/golden/evidence_bundle.py inspect --bundle composite.zip
~~~

bundle_sources.json 是 JSON 数组，成员形如：

~~~json
[
  {
    "path": "local/rule.pdf",
    "source_ref": "https://official.example/rule.pdf",
    "kind": "EXCHANGE_RULEBOOK"
  },
  {
    "path": "local/applicability.html",
    "source_ref": "https://official.example/applicability.html",
    "kind": "COMPANY_ANNOUNCEMENT"
  }
]
~~~

## 批量 REVIEWED seal 输入

--manifest 必须覆盖 ACTIVE 的每个 case 恰好一次。P1 seal manifest 禁止出现 expect_fields 键（包括 null）；事实修正必须先回到 candidate/rebuild 过程。每条 entry 最小形如：

~~~json
{
  "case": "GT-H3B-CASE",
  "artifact": "composite.zip",
  "kind": "EVIDENCE_BUNDLE",
  "bundle_sources": [
    {
      "source_ref": "https://official.example/rule.pdf",
      "kind": "EXCHANGE_RULEBOOK"
    },
    {
      "source_ref": "https://official.example/applicability.html",
      "kind": "COMPANY_ANNOUNCEMENT"
    }
  ]
}
~~~

运行命令仍为：

~~~text
python scripts/golden/review.py \
  --manifest gt-h3b-125-review-manifest.json \
  --reviewer project-owner
~~~

review.py 自己计算外层 bundle bytes 的 authoritative SHA256，并在 stage 阶段复核 bundle 内每份原始 bytes。未通过的 source、bundle、覆盖、hash、manifest 或发布校验都必须 BLOCK；本批次不生成任何 REVIEWED 版本或 ACTIVE 变更。

## 未完成项

- 获取并审阅 ACTIVE v6 的 125 份官方原始 bytes；5 个复合 case 需按上面格式绑定双证据。
- 在受控环境中运行 125-entry batch，验证 REVIEWED 125 / COMPILED 0、artifact hashes、历史版本不变、ACTIVE last。
- 由独立 Reviewer 对包含证据 bytes 与 seal 的 final head 做 current-main test-merge 后再合并；GT-H3B merged 后才执行一次 Formal Production B1-B7。

## 发布失败回滚补强（2026-09-08）

在真正开始 durable publication 后，工具现在记录本次调用新建的 evidence/version 文件。若 ACTIVE 指针仍保持旧字节而提交阶段失败，工具只删除“本次新建且字节未被外部改动”的文件；已有同 hash evidence 和所有历史 versioned 文件不会删除。若无法确认 ACTIVE 是否仍为旧值，或发现新文件已被外部改动，工具保留现场并明确报错，避免把 ACTIVE 指向的文件误删。

该保护覆盖指针写失败、versioned 文件创建失败和 evidence 写入中途失败；测试验证旧 ACTIVE 不变、无新 version 文件、无新 evidence 文件。它不能替代操作系统崩溃恢复或真实 evidence 获取，仍必须以 CI 和最终 125/125 seal 结果为准。
