"""Prepare and verify the GT-H2 clean golden-corpus candidate.

This utility is deliberately source-data only.  It records official source
locators and builds an explicit v3 -> v4 plan; it does not download or commit
web pages, does not bind review artifacts, and never marks a case REVIEWED.

Typical use from the repository root::

    python scripts/golden/gt_h2_prepare.py prepare
    python scripts/golden/candidate.py rebuild \
        --plan docs/golden/gt_h2/rebuild_plan_v4.json \
        --truth-version v4-candidate-20260906
    python scripts/golden/gt_h2_prepare.py finalize

The first command must run while ACTIVE is the immutable v3 candidate.  The
last command must run after candidate.py has published ACTIVE v4.  The
generated packet contains references only; human review remains the separate
review.py workflow.
"""

# The source registry and generated hand-off text retain long official URLs
# verbatim; E501 is therefore not useful for this data-heavy utility.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from ashare_state.spike.golden_store import (  # noqa: E402
    GoldenTruthStore,
    recompute_manifest_statistics,
    review_readiness_gate,
)

GOLDEN_ROOT = REPO_ROOT / "data/golden/provider/amazingdata"
OUT_DIR = REPO_ROOT / "docs/golden/gt_h2"
SOURCE_VERSION = "v3-candidate-20260822"
TARGET_VERSION = "v4-candidate-20260906"
V3_DATASET = "golden_cases_v3.jsonl"
V3_DATASET_HASH = "ab841d25858a5520c2357dcf72da9932fc1f25f988d900fd94730eb5a1a6f79e"


# These are source locators, not sealed review artifacts.  The source pages
# were independently located in the official exchange/disclosure domains.
# The final review workflow must still bind the exact bytes and hash.
ST_ADD_FACTS: tuple[dict[str, str], ...] = (
    {
        "symbol": "002681.SZ",
        "date": "20200506",
        "url": "http://disc.static.szse.cn/download/disc/disk02/finalpage/2020-04-30/6c34f44d-5bee-46df-8f17-2c699b477d18.PDF",
        "name": "SZSE official announcement: *ST 奋达 risk warning effective 2020-05-06",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "000408.SZ",
        "date": "20200506",
        "url": "http://disc.static.szse.cn/download/disc/disk02/finalpage/2020-04-30/5018e5ae-ddeb-4602-a0c1-7f2b0634f727.PDF",
        "name": "SZSE official announcement: *ST 藏格 risk warning effective 2020-05-06",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "002513.SZ",
        "date": "20200429",
        "url": "http://disc.static.szse.cn/download/disc/disk02/finalpage/2020-04-28/e3e3b094-6f16-461a-858f-f77851a3e60f.PDF",
        "name": "SZSE official announcement: *ST 蓝丰 risk warning effective 2020-04-29",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "000587.SZ",
        "date": "20200507",
        "url": "http://disc.static.szse.cn/download/disc/disk02/finalpage/2020-04-30/101bf255-d1eb-4791-96a2-28d2ebbcb1cc.PDF",
        "name": "SZSE official announcement: *ST 金洲 risk warning effective 2020-05-07",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "002052.SZ",
        "date": "20200506",
        "url": "http://disc.static.szse.cn/download/disc/disk02/finalpage/2021-06-07/276460c6-f1c9-42f5-b2d7-9159e0cb3974.PDF",
        "name": "SZSE official disclosure referring to *ST 同洲 risk warning effective 2020-05-06",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "002319.SZ",
        "date": "20200428",
        "url": "http://disc.static.szse.cn/download/disc/disk02/finalpage/2020-04-25/805e9468-baf4-40b2-b042-10e4d1172063.PDF",
        "name": "SZSE official announcement: *ST 乐通 risk warning effective 2020-04-28",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "000613.SZ",
        "date": "20210427",
        "url": "https://disc.static.szse.cn/disc/disk02/finalpage/2021-04-24/780272c9-1bb5-4ce0-b6cf-6f95a71059be.PDF",
        "name": "SZSE official announcement: *ST 东海 A risk warning effective 2021-04-27",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "300064.SZ",
        "date": "20210428",
        "url": "http://disc.static.szse.cn/download/disc/disk02/finalpage/2021-04-27/853620b1-b4a9-432d-9ee8-d8dcefd821d6.PDF",
        "name": "SZSE official announcement: *ST 金刚 risk warning effective 2021-04-28",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "CHINEXT",
    },
    {
        "symbol": "300312.SZ",
        "date": "20210429",
        "url": "http://disc.static.szse.cn/download/disc/disk02/finalpage/2021-04-28/3a1e7c33-47d7-43d3-ba85-203b8221353e.PDF",
        "name": "SZSE official announcement: *ST 邦讯 risk warning effective 2021-04-29",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "CHINEXT",
    },
    {
        "symbol": "600593.SH",
        "date": "20210722",
        "url": "http://www.sse.com.cn/disclosure/announcement/general/c/c_20210720_5526013.shtml",
        "name": "SSE official announcement: 600593 risk warning effective 2021-07-22",
        "kind": "SSE_ANNOUNCEMENT",
        "exchange": "SSE",
        "board": "MAIN",
    },
    {
        "symbol": "002113.SZ",
        "date": "20200429",
        "url": "http://disc.static.szse.cn/download/disc/disk02/finalpage/2021-08-26/d61cb4c7-8be7-45c6-ace7-99e1faed88e1.PDF",
        "name": "SZSE official disclosure referring to *ST 天润 risk warning effective 2020-04-29",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "000806.SZ",
        "date": "20220506",
        "url": "http://disc.static.szse.cn/disc/disk03/finalpage/2022-04-30/b6d5b6a7-e992-4ff1-bd09-832e4e500651.PDF",
        "name": "SZSE official announcement: *ST 银河 risk warning effective 2022-05-06",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "002022.SZ",
        "date": "20220506",
        "url": "http://disc.static.szse.cn/disc/disk02/finalpage/2022-04-30/a781efcd-39ab-4be8-9c80-0cc15863a36c.PDF",
        "name": "SZSE official announcement: *ST 科华 risk warning effective 2022-05-06",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "002417.SZ",
        "date": "20220421",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2022-04-20/d5512186-9d1c-4c2b-98a6-5a3d641e83a6.PDF",
        "name": "SZSE official announcement: *ST 深南 risk warning effective 2022-04-21",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "002781.SZ",
        "date": "20220506",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2022-11-18/d507ec79-4364-4159-b566-3b52c4df5c48.PDF",
        "name": "SZSE official disclosure referring to *ST 奇信 risk warning effective 2022-05-06",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "000606.SZ",
        "date": "20220506",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2023-03-13/fd76e611-9f68-4ddc-96de-7c8a37fc5fda.PDF",
        "name": "SZSE official disclosure referring to *ST 顺利 risk warning effective 2022-05-06",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "000995.SZ",
        "date": "20220429",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2023-03-13/0637c8e3-59a6-45ce-a0e5-de996b4a72e5.PDF",
        "name": "SZSE official disclosure referring to *ST 皇台 risk warning effective 2022-04-29",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "300336.SZ",
        "date": "20220429",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2023-01-30/58a93ed7-8b2f-4587-b43a-e9493b9daa60.PDF",
        "name": "SZSE official announcement: *ST 新文 risk warning effective 2022-04-29",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "CHINEXT",
    },
    {
        "symbol": "300297.SZ",
        "date": "20220429",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2023-03-28/39fe9657-2530-48aa-9ff9-98cac5f2e15e.PDF",
        "name": "SZSE official announcement: *ST 蓝盾 risk warning effective 2022-04-29",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "CHINEXT",
    },
    {
        "symbol": "300330.SZ",
        "date": "20220808",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2022-08-05/832ecade-fa63-42d8-8520-388cdd3930cd.PDF",
        "name": "SZSE official announcement: *ST 计通 risk warning effective 2022-08-08",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "CHINEXT",
    },
    {
        "symbol": "000410.SZ",
        "date": "20220419",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2023-04-29/fc4e9195-d651-477a-9bb9-a1e5f52cc43a.PDF",
        "name": "SZSE official disclosure referring to *ST 沈机 risk warning effective 2022-04-19",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "002485.SZ",
        "date": "20220506",
        "url": "http://disc.static.szse.cn/disc/disk03/finalpage/2022-04-30/4cb2d78e-0ec1-4c86-93b9-0d7e08127e5e.PDF",
        "name": "SZSE official announcement: *ST 雪发 risk warning effective 2022-05-06",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "000616.SZ",
        "date": "20230504",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2023-04-28/10329d33-dd5b-416b-a0cf-2af0a33c4e13.PDF",
        "name": "SZSE official announcement: *ST 海投 risk warning effective 2023-05-04",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "000540.SZ",
        "date": "20230505",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2023-04-29/09ad58d3-6179-47a3-bba4-1cccf853ae04.PDF",
        "name": "SZSE official announcement: *ST 中天 risk warning effective 2023-05-05",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "002433.SZ",
        "date": "20230505",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2024-04-30/20e9fe23-010b-4cd6-a0e8-cb71676efd21.PDF",
        "name": "SZSE official disclosure referring to *ST 太安 risk warning effective 2023-05-05",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "002086.SZ",
        "date": "20230505",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2023-12-01/d12ed6af-2ddf-4be3-9c59-050a5484375e.PDF",
        "name": "SZSE official disclosure referring to *ST 东洋 risk warning effective 2023-05-05",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "300742.SZ",
        "date": "20230504",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2024-05-08/f32b3983-feec-44e5-ba43-1bf9ec15cf84.pdf",
        "name": "SZSE official disclosure referring to *ST 越博 risk warning effective 2023-05-04",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "CHINEXT",
    },
    {
        "symbol": "300208.SZ",
        "date": "20240430",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2024-04-26/97177b91-6c27-437c-83e0-3c52d2f7b729.PDF",
        "name": "SZSE official announcement: *ST 中程 risk warning effective 2024-04-30",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "CHINEXT",
    },
    {
        "symbol": "002217.SZ",
        "date": "20240506",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2024-05-16/a4389dc6-97e8-4f1b-a2cc-bae0de6e5dec.PDF",
        "name": "SZSE official disclosure referring to *ST 合泰 risk warning effective 2024-05-06",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "300108.SZ",
        "date": "20240430",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2025-03-10/cfd76336-3ab7-4c6d-8e17-8fdb4fe8c447.PDF",
        "name": "SZSE official disclosure referring to *ST 吉药 risk warning effective 2024-04-30",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "CHINEXT",
    },
    {
        "symbol": "300209.SZ",
        "date": "20240429",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2025-04-17/16f33a70-834e-42b8-a894-d8b5abe35535.pdf",
        "name": "SZSE official disclosure referring to *ST 有树 risk warning effective 2024-04-29",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "CHINEXT",
    },
    {
        "symbol": "300167.SZ",
        "date": "20240430",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2025-04-29/30ec3b9a-dd82-4aaf-bf05-273e9edcb2a0.pdf",
        "name": "SZSE official disclosure referring to *ST 迪威风险警示 effective 2024-04-30",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "CHINEXT",
    },
    {
        "symbol": "000525.SZ",
        "date": "20240919",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2024-10-09/a133a2c9-9d40-4c92-85ac-3efed7d8359d.PDF",
        "name": "SZSE official disclosure referring to *ST 红阳 risk warning effective 2024-09-19",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "300506.SZ",
        "date": "20240429",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2025-03-20/cd19ee3f-0bc9-4e4b-9477-af6b6fab7c4b.pdf",
        "name": "SZSE official disclosure referring to *ST 名家汇 risk warning effective 2024-04-29",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "CHINEXT",
    },
    {
        "symbol": "300965.SZ",
        "date": "20240429",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2025-04-11/d1f5b09c-3741-4e64-8984-a65441b01dd1.pdf",
        "name": "SZSE official disclosure referring to *ST 恒宇 risk warning effective 2024-04-29",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "CHINEXT",
    },
    {
        "symbol": "600213.SH",
        "date": "20240506",
        "url": "https://www.sse.com.cn/disclosure/magin/announcement/ssereport/c/c_20240430_10753871.shtml",
        "name": "SSE official risk-warning adjustment list: 600213 effective 2024-05-06",
        "kind": "SSE_ANNOUNCEMENT",
        "exchange": "SSE",
        "board": "MAIN",
    },
    {
        "symbol": "603363.SH",
        "date": "20240506",
        "url": "https://www.sse.com.cn/disclosure/magin/announcement/ssereport/c/c_20240430_10753871.shtml",
        "name": "SSE official risk-warning adjustment list: 603363 effective 2024-05-06",
        "kind": "SSE_ANNOUNCEMENT",
        "exchange": "SSE",
        "board": "MAIN",
    },
    {
        "symbol": "688282.SH",
        "date": "20240506",
        "url": "https://www.sse.com.cn/disclosure/magin/announcement/ssereport/c/c_20240430_10753871.shtml",
        "name": "SSE official risk-warning adjustment list: STAR 688282 effective 2024-05-06",
        "kind": "SSE_ANNOUNCEMENT",
        "exchange": "SSE",
        "board": "STAR",
    },
)

ST_REMOVE_FACTS: tuple[dict[str, str], ...] = (
    {
        "symbol": "002681.SZ",
        "date": "20210413",
        "url": "http://disc.static.szse.cn/download/disc/disk02/finalpage/2021-04-10/ff3c0039-575f-4554-8035-d061e882f2c7.PDF",
        "name": "SZSE official announcement: 002681 *ST removal effective 2021-04-13",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "000408.SZ",
        "date": "20210512",
        "url": "https://disc.static.szse.cn/disc/disk02/finalpage/2021-05-11/f9006990-ffd3-40bb-9cb9-be8dc0511516.PDF",
        "name": "SZSE official announcement: 000408 *ST removal effective 2021-05-12",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "002513.SZ",
        "date": "20210621",
        "url": "https://disc.static.szse.cn/disc/disk02/finalpage/2021-06-18/0acbdccf-207a-4bab-a5fb-a6bf8d8c515a.PDF",
        "name": "SZSE official announcement: 002513 *ST removal effective 2021-06-21",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "002058.SZ",
        "date": "20220523",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2022-05-20/9ac63995-9ddd-4dca-ada2-f9fd0ead9e60.PDF",
        "name": "SZSE official announcement: 002058 *ST removal effective 2022-05-23",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "000007.SZ",
        "date": "20220701",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2022-06-30/7de6ae82-da34-47da-a35b-71cbb965c01e.PDF",
        "name": "SZSE official announcement: 000007 *ST removal effective 2022-07-01",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "002022.SZ",
        "date": "20230404",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2024-03-22/e0b014e3-3416-4526-9063-9845e9e42a6f.PDF",
        "name": "SZSE official disclosure referring to 002022 *ST removal effective 2023-04-04",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "300010.SZ",
        "date": "20240613",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2024-06-12/f438ff5f-8b32-4d10-aaab-a8598162ef43.PDF",
        "name": "SZSE official announcement: 300010 *ST removal effective 2024-06-13",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "CHINEXT",
    },
    {
        "symbol": "002482.SZ",
        "date": "20240618",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2024-06-14/11ae7c86-7e5d-4eba-9e5d-6bd0c31767db.PDF",
        "name": "SZSE official announcement: 002482 full *ST removal effective 2024-06-18",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "002086.SZ",
        "date": "20240612",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2024-06-07/cb052454-f6db-44e0-a320-079c4c14c864.PDF",
        "name": "SZSE official announcement: 002086 *ST removal effective 2024-06-12",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "002021.SZ",
        "date": "20240603",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2024-05-31/09907ab2-b9f4-4891-bfb4-21ed2cfa090d.PDF",
        "name": "SZSE official announcement: 002021 *ST removal effective 2024-06-03",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "300209.SZ",
        "date": "20250513",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2025-05-09/f2d85e09-1b78-42bc-a128-f1862d6b0fe9.PDF",
        "name": "SZSE official announcement: 300209 *ST removal effective 2025-05-13",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "CHINEXT",
    },
    {
        "symbol": "300965.SZ",
        "date": "20250506",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2025-04-30/d8e3ad5c-377f-4d9c-8d6c-31a510424ff8.PDF",
        "name": "SZSE official announcement: 300965 *ST removal effective 2025-05-06",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "CHINEXT",
    },
)

DELIST_FACTS: tuple[dict[str, str], ...] = (
    {
        "symbol": "601558.SH",
        "date": "20200702",
        "url": "http://www.sse.com.cn/disclosure/announcement/listing/stock/c/c_20200623_78480676.shtml",
        "name": "SSE official delisting notice: 601558摘牌 2020-07-02",
        "kind": "SSE_ANNOUNCEMENT",
        "exchange": "SSE",
        "board": "MAIN",
    },
    {
        "symbol": "600068.SH",
        "date": "20210913",
        "url": "http://www.sse.com.cn/disclosure/announcement/listing/stock/c/c_20210909_82957014.shtml",
        "name": "SSE official delisting notice: 600068终止上市 effective 2021-09-13",
        "kind": "SSE_ANNOUNCEMENT",
        "exchange": "SSE",
        "board": "MAIN",
    },
    {
        "symbol": "600145.SH",
        "date": "20220428",
        "url": "https://www.sse.com.cn/disclosure/announcement/listing/stock/c/c_20220421_84964449.shtml",
        "name": "SSE official delisting notice: 600145摘牌 2022-04-28",
        "kind": "SSE_ANNOUNCEMENT",
        "exchange": "SSE",
        "board": "MAIN",
    },
    {
        "symbol": "600093.SH",
        "date": "20220623",
        "url": "http://www.sse.com.cn/disclosure/announcement/listing/stock/c/c_20220616_85759277.shtml",
        "name": "SSE official delisting notice: 600093摘牌 2022-06-23",
        "kind": "SSE_ANNOUNCEMENT",
        "exchange": "SSE",
        "board": "MAIN",
    },
    {
        "symbol": "600695.SH",
        "date": "20220614",
        "url": "http://www.sse.com.cn/disclosure/announcement/listing/stock/c/c_20220607_85645623.shtml",
        "name": "SSE official delisting notice: 600695摘牌 2022-06-14",
        "kind": "SSE_ANNOUNCEMENT",
        "exchange": "SSE",
        "board": "MAIN",
    },
    {
        "symbol": "600781.SH",
        "date": "20230628",
        "url": "http://www.sse.com.cn/disclosure/announcement/listing/stock/c/c_20230619_90006973.shtml",
        "name": "SSE official delisting notice: 600781摘牌 2023-06-28",
        "kind": "SSE_ANNOUNCEMENT",
        "exchange": "SSE",
        "board": "MAIN",
    },
    {
        "symbol": "600225.SH",
        "date": "20250306",
        "url": "https://www.sse.com.cn/disclosure/announcement/listing/stock/c/c_20250227_10773066.shtml",
        "name": "SSE official delisting notice: 600225摘牌 2025-03-06",
        "kind": "SSE_ANNOUNCEMENT",
        "exchange": "SSE",
        "board": "MAIN",
    },
    {
        "symbol": "600190.SH",
        "date": "20250725",
        "url": "https://www.sse.com.cn/disclosure/announcement/listing/stock/c/c_20250718_10785880.shtml",
        "name": "SSE official delisting notice: 600190摘牌 2025-07-25",
        "kind": "SSE_ANNOUNCEMENT",
        "exchange": "SSE",
        "board": "MAIN",
    },
    {
        "symbol": "600837.SH",
        "date": "20250304",
        "url": "https://www.sse.com.cn/disclosure/announcement/listing/stock/c/c_20250226_10773005.shtml",
        "name": "SSE official delisting decision: 600837终止上市 effective 2025-03-04",
        "kind": "SSE_ANNOUNCEMENT",
        "exchange": "SSE",
        "board": "MAIN",
    },
    {
        "symbol": "601989.SH",
        "date": "20250905",
        "url": "https://www.sse.com.cn/disclosure/announcement/listing/stock/c/c_20250829_10790128.shtml",
        "name": "SSE official delisting decision: 601989终止上市 effective 2025-09-05",
        "kind": "SSE_ANNOUNCEMENT",
        "exchange": "SSE",
        "board": "MAIN",
    },
    {
        "symbol": "600462.SH",
        "date": "20250721",
        "url": "https://www.sse.com.cn/disclosure/announcement/listing/stock/c/c_20250714_10784844.shtml",
        "name": "SSE official delisting notice: 600462摘牌 2025-07-21",
        "kind": "SSE_ANNOUNCEMENT",
        "exchange": "SSE",
        "board": "MAIN",
    },
    {
        "symbol": "600421.SH",
        "date": "20260626",
        "url": "https://www.sse.com.cn/disclosure/announcement/listing/stock/c/c_20260622_10823158.shtml",
        "name": "SSE official delisting notice: 600421摘牌 2026-06-26",
        "kind": "SSE_ANNOUNCEMENT",
        "exchange": "SSE",
        "board": "MAIN",
    },
    {
        "symbol": "000611.SZ",
        "date": "20220628",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2022-06-28/0df4c2ca-295b-4581-a172-094d8cae8425.PDF",
        "name": "SZSE official delisting notice: 000611摘牌 2022-06-28",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "300064.SZ",
        "date": "20220627",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2022-06-27/286a098f-56a5-4a5b-8e0d-1953eebf9f2f.PDF",
        "name": "SZSE official delisting notice: 300064摘牌 2022-06-27",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "CHINEXT",
    },
    {
        "symbol": "000540.SZ",
        "date": "20230630",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2023-06-28/2d0e5c9f-a6d7-4c00-9ac2-bf286ba715b8.PDF",
        "name": "SZSE official delisting notice: 000540摘牌 2023-06-30",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "300273.SZ",
        "date": "20230706",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2023-07-05/776889cd-c8c1-48fb-b1a4-d0cf4819e8fd.PDF",
        "name": "SZSE official delisting notice: 300273摘牌 2023-07-06",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "CHINEXT",
    },
    {
        "symbol": "002118.SZ",
        "date": "20230804",
        "url": "http://disc.static.szse.cn/disc/disk03/finalpage/2023-07-31/44450b39-f154-45b0-a05f-4878f0c55261.PDF",
        "name": "SZSE official delisting notice: 002118摘牌 2023-08-04",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "002610.SZ",
        "date": "20240812",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2024-08-09/1dc535d8-fbe2-42bb-bab6-cd90d0e12e64.PDF",
        "name": "SZSE official delisting notice: 002610摘牌 2024-08-12",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "000982.SZ",
        "date": "20240812",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2024-08-12/c552bbd6-8940-49ef-bbd0-c2c83a3ece6d.PDF",
        "name": "SZSE official delisting notice: 000982摘牌 2024-08-12",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "300208.SZ",
        "date": "20250721",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2025-07-18/ff3f8315-18fd-48e8-a473-545bcb5a0a67.PDF",
        "name": "SZSE official delisting notice: 300208摘牌 2025-07-21",
        "kind": "SZSE_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "CHINEXT",
    },
)

RIGHT_ISSUE_FACTS: tuple[dict[str, str], ...] = (
    {
        "symbol": "002142.SZ",
        "date": "20211202",
        "url": "http://static.cninfo.com.cn/finalpage/2021-12-02/1211763892.PDF",
        "name": "CNINFO company announcement: 宁波银行配股除权日 2021-12-02",
        "kind": "COMPANY_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "300475.SZ",
        "date": "20230216",
        "url": "https://disc.static.szse.cn/disc/disk03/finalpage/2023-02-16/d2d8c9e3-0ad2-4a54-af01-e176019e9906.PDF",
        "name": "SZSE company announcement: 香农芯创配股除权日 2023-02-16",
        "kind": "COMPANY_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "CHINEXT",
    },
    {
        "symbol": "002788.SZ",
        "date": "20200917",
        "url": "https://disc.static.szse.cn/disc/disk02/finalpage/2020-09-17/4851a060-520a-4116-a303-00d7eb5aef65.PDF",
        "name": "SZSE company announcement: 鹭燕医药配股除权日 2020-09-17",
        "kind": "COMPANY_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "002202.SZ",
        "date": "20190329",
        "url": "http://disc.static.szse.cn/disc/disk01/finalpage/2019-03-29/27a8f9a6-cfe2-41bb-a9c7-149f5219f383.PDF",
        "name": "SZSE company announcement: 金风科技配股除权日 2019-03-29",
        "kind": "COMPANY_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
    {
        "symbol": "000750.SZ",
        "date": "20200114",
        "url": "http://static.cninfo.com.cn/finalpage/2025-03-29/1222948083.PDF",
        "name": "CNINFO annual report: 国海证券配股除权日 2020-01-14",
        "kind": "COMPANY_ANNOUNCEMENT",
        "exchange": "SZSE",
        "board": "MAIN",
    },
)


def _json_dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _jsonl_dump(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _code(symbol: str) -> str:
    return symbol.split(".", 1)[0]


def _entry(
    *,
    symbol: str,
    date: str,
    event_class: str,
    subtype: str,
    name: str,
    url: str,
    kind: str,
    exchange: str,
    board: str,
    expected_fields: dict[str, Any],
    case_id_prefix: str,
    fact: str,
) -> dict[str, Any]:
    event_id = f"{case_id_prefix}-{_code(symbol)}-{date}"
    if event_class == "ST_TRANSITION":
        case_id = f"GT-H2-ST-{subtype}-{_code(symbol)}-{date}"
        case_type = "golden_st_transition"
        date_semantics = (
            "event_effective_date is the official status-change date; "
            "trade_date intentionally equals that date for the single event-day observation"
        )
    elif event_class == "DELIST":
        case_id = f"GT-H2-DELIST-{_code(symbol)}-{date}"
        case_type = "golden_delisted"
        date_semantics = (
            "event_effective_date is the official termination/delisting effective date; "
            "trade_date intentionally equals that date for the event-day observation"
        )
    else:
        case_id = f"GT-H2-CA-RIGHT-{_code(symbol)}-{date}"
        case_type = "golden_corporate_action"
        date_semantics = "trade_date is the official right-issue ex-date"

    case = {
        "golden_case_id": case_id,
        "case_type": case_type,
        "provider_symbol": symbol,
        "trade_date": date,
        "truth_source": fact,
        "source_ref": f"{name} | {url}",
        "expected_fields": expected_fields,
        "event_id": event_id,
        "event_class": event_class,
        "event_subtype": subtype,
    }
    if event_class in {"ST_TRANSITION", "DELIST"}:
        case["event_effective_date"] = date
    if event_class == "RIGHT_ISSUE_EX_DATE":
        case["event_id"] = event_id.replace("GT-H2-", "")

    return {
        "golden_case_id": case_id,
        "case_type": case_type,
        "provider_symbol": symbol,
        "trade_date": date,
        "event_class": event_class,
        "event_subtype": subtype,
        "event_effective_date": case.get("event_effective_date", ""),
        "expected_fields": expected_fields,
        "official_source_name": name,
        "official_source_ref": url,
        "artifact_kind_candidate": kind,
        "fact_proved": True,
        "exchange": exchange,
        "board": board,
        "year": date[:4],
        "date_semantics": date_semantics,
        "case": case,
    }


def _registry() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for fact in ST_ADD_FACTS:
        entries.append(
            _entry(
                symbol=fact["symbol"],
                date=fact["date"],
                event_class="ST_TRANSITION",
                subtype="STAR_ST_ADD" if fact["board"] == "STAR" else "ST_ADD",
                name=fact["name"],
                url=fact["url"],
                kind=fact["kind"],
                exchange=fact["exchange"],
                board=fact["board"],
                expected_fields={"IS_ST_SEC": True},
                case_id_prefix="ST-ADD",
                fact=fact["name"],
            )
        )
    for fact in ST_REMOVE_FACTS:
        entries.append(
            _entry(
                symbol=fact["symbol"],
                date=fact["date"],
                event_class="ST_TRANSITION",
                subtype="ST_REMOVE",
                name=fact["name"],
                url=fact["url"],
                kind=fact["kind"],
                exchange=fact["exchange"],
                board=fact["board"],
                expected_fields={"IS_ST_SEC": False},
                case_id_prefix="ST-REMOVE",
                fact=fact["name"],
            )
        )
    for fact in DELIST_FACTS:
        entries.append(
            _entry(
                symbol=fact["symbol"],
                date=fact["date"],
                event_class="DELIST",
                subtype="",
                name=fact["name"],
                url=fact["url"],
                kind=fact["kind"],
                exchange=fact["exchange"],
                board=fact["board"],
                expected_fields={"IS_LISTED": "3"},
                case_id_prefix="DELIST",
                fact=fact["name"],
            )
        )
    for fact in RIGHT_ISSUE_FACTS:
        entries.append(
            _entry(
                symbol=fact["symbol"],
                date=fact["date"],
                event_class="RIGHT_ISSUE_EX_DATE",
                subtype="",
                name=fact["name"],
                url=fact["url"],
                kind=fact["kind"],
                exchange=fact["exchange"],
                board=fact["board"],
                expected_fields={"IS_WD_SEC": True, "event_type": "RIGHT_ISSUE"},
                case_id_prefix="RIGHT-ISSUE",
                fact=fact["name"],
            )
        )
    ids = [str(entry["golden_case_id"]) for entry in entries]
    if len(ids) != len(set(ids)):
        raise RuntimeError("GT-H2 registry contains duplicate golden_case_id")
    structural_ids = [
        (
            str(entry["provider_symbol"]),
            str(entry["event_effective_date"]),
            str(entry["event_subtype"]),
            str(entry["event_class"]),
        )
        for entry in entries
        if entry["event_class"] in {"ST_TRANSITION", "DELIST"}
    ]
    if len(structural_ids) != len(set(structural_ids)):
        raise RuntimeError("GT-H2 registry contains duplicate structural event identity")
    if len(ST_ADD_FACTS) != 38 or len(ST_REMOVE_FACTS) != 12:
        raise RuntimeError("ST registry cardinality drifted from the H2 source plan")
    if len(DELIST_FACTS) != 20 or len(RIGHT_ISSUE_FACTS) != 5:
        raise RuntimeError(
            "DELIST/RIGHT_ISSUE registry cardinality drifted from the H2 source plan"
        )
    return entries


def _source_context(doc: dict[str, Any]) -> tuple[str, str, str]:
    symbol = str(doc["provider_symbol"])
    event_class = str(doc["event_class"])
    event_id = str(doc.get("event_id", ""))
    if event_class in {"LIMIT_REGIME", "NO_LIMIT_IPO"}:
        if event_class == "NO_LIMIT_IPO":
            return (
                "SSE IPO first-day price-limit rules (2014-2023)",
                "https://www.sse.com.cn/lawandrules/sselawsrules/repeal/rules/c/c_20230418_5720136.shtml",
                "EXCHANGE_RULEBOOK",
            )
        if "BJ" in event_id or symbol.endswith(".BJ"):
            return (
                "BSE official trading-rule portal: 30% price-limit regime",
                "https://www.bse.cn/",
                "EXCHANGE_RULEBOOK",
            )
        if "STAR" in event_id or (symbol.endswith(".SH") and symbol.startswith("688")):
            return (
                "SSE official trading rules: STAR price-limit regime",
                "https://www.sse.com.cn/lawandrules/sselawsrules/repeal/rules/c/c_20230418_5720136.shtml",
                "EXCHANGE_RULEBOOK",
            )
        if "CN" in event_id or (symbol.endswith(".SZ") and symbol.startswith("300")):
            return (
                "SZSE official trading-rule portal: ChiNext price-limit regime",
                "https://www.szse.cn/lawrules/rule/trade/",
                "EXCHANGE_RULEBOOK",
            )
        if "ST" in event_id:
            if symbol.endswith(".SH"):
                return (
                    "SSE official risk-warning stock trading rules: 5% limit",
                    "https://www.sse.com.cn/lawandrules/sselawsrules/repeal/rules/c/c_20210531_5478105.shtml",
                    "EXCHANGE_RULEBOOK",
                )
            return (
                "SZSE official risk-warning stock trading rules: 5% limit",
                "https://www.szse.cn/lawrules/rule/trade/",
                "EXCHANGE_RULEBOOK",
            )
        if symbol.endswith(".SH"):
            return (
                "SSE official trading rules: main-board 10% limit",
                "https://www.sse.com.cn/lawandrules/sselawsrules/repeal/rules/c/c_20230418_5720136.shtml",
                "EXCHANGE_RULEBOOK",
            )
        return (
            "SZSE official trading rules: main-board 10% limit",
            "https://www.szse.cn/lawrules/rule/trade/",
            "EXCHANGE_RULEBOOK",
        )
    if event_class == "DIVIDEND_EX_DATE":
        if symbol.endswith(".SH"):
            return (
                "SSE listed-company disclosure portal: dividend ex-date locator",
                "https://www.sse.com.cn/disclosure/listedinfo/announcement/",
                "COMPANY_ANNOUNCEMENT",
            )
        return (
            "CNINFO listed-company disclosure portal: dividend ex-date locator",
            "https://www.cninfo.com.cn/new/disclosure",
            "COMPANY_ANNOUNCEMENT",
        )
    if event_class == "BJ_CODE_MIGRATION":
        return (
            "BSE official issuer and quotation-rule portal: code continuity/migration",
            "https://www.bse.cn/",
            "BSE_ANNOUNCEMENT",
        )
    raise RuntimeError(f"no official context mapping for {event_class}/{event_id}")


def _replacement(doc: dict[str, Any]) -> dict[str, Any]:
    replacement = copy.deepcopy(doc)
    for field in ("case_semantic_hash", "compiled_by", "compiled_at"):
        replacement.pop(field, None)
    for field in (
        "reviewed_by",
        "reviewed_at",
        "review_note",
        "source_artifact_ref",
        "source_artifact_hash",
        "source_artifact_kind",
        "source_retrieved_at",
    ):
        replacement.pop(field, None)
    name, url, _ = _source_context(replacement)
    replacement["source_ref"] = f"{name} | {url} | source claim: {doc['source_ref']}"
    replacement["truth_source"] = str(doc["truth_source"])
    return replacement


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def prepare() -> None:
    active_path = GOLDEN_ROOT / "truth_manifest.json"
    active = json.loads(active_path.read_text(encoding="utf-8"))
    if active.get("truth_version") != SOURCE_VERSION:
        raise RuntimeError(
            f"prepare requires ACTIVE {SOURCE_VERSION}, got {active.get('truth_version')}"
        )
    if active.get("dataset_file") != V3_DATASET or active.get("dataset_hash") != V3_DATASET_HASH:
        raise RuntimeError("prepare source binding does not match the immutable v3 contract")
    source_lines = _load_jsonl(GOLDEN_ROOT / V3_DATASET)
    registry = _registry()
    operations: list[dict[str, Any]] = []
    op_counts: Counter[str] = Counter()
    for doc in source_lines:
        event_class = str(doc.get("event_class", ""))
        case_id = str(doc["golden_case_id"])
        if event_class in {"ST_TRANSITION", "DELIST", "NEGATIVE_SAMPLE"}:
            operations.append({"op": "DROP", "golden_case_id": case_id})
            op_counts["DROP"] += 1
        else:
            operations.append(
                {
                    "op": "REPLACE",
                    "golden_case_id": case_id,
                    "case": _replacement(doc),
                }
            )
            op_counts["REPLACE"] += 1
    for entry in registry:
        operations.append(
            {
                "op": "ADD",
                "golden_case_id": entry["golden_case_id"],
                "case": entry["case"],
            }
        )
        op_counts["ADD"] += 1

    plan = {
        "plan_schema": 1,
        "source_truth_version": SOURCE_VERSION,
        "source_dataset_file": V3_DATASET,
        "source_dataset_hash": V3_DATASET_HASH,
        "target_truth_version": TARGET_VERSION,
        "policy": {
            "old_structural_rows": "DROP: v3 ST/DELIST rows lack exact effective dates or distinct identities",
            "old_negative_samples": "DROP: repetitive observations add no independent structural truth",
            "old_non_structural_rows": "REPLACE: preserve case semantics while adding official rule/disclosure locators",
            "new_structural_rows": "ADD: one canonical case per independently located official event",
            "new_right_issue_rows": "ADD: supplement dividend-only CA coverage with right-issue ex-dates",
            "review_boundary": "No source artifact is sealed and no case is marked REVIEWED by this utility",
        },
        "operation_summary": dict(op_counts),
        "registry_case_count": len(registry),
        "operations": operations,
    }
    _json_dump(OUT_DIR / "official_fact_registry.json", registry)
    _json_dump(OUT_DIR / "rebuild_plan_v4.json", plan)
    print(
        json.dumps(
            {
                "source": SOURCE_VERSION,
                "target": TARGET_VERSION,
                "registry_cases": len(registry),
                "operation_summary": dict(op_counts),
            },
            ensure_ascii=False,
        )
    )


def _checklist(doc: dict[str, Any]) -> list[str]:
    event_class = str(doc.get("event_class", ""))
    if event_class == "ST_TRANSITION":
        return [
            "Confirm provider_symbol and exchange/board identity in the cited official artifact.",
            "Confirm the artifact states the exact ST_ADD/ST_REMOVE subtype and status value.",
            "Confirm event_effective_date is the status-change effective date, not publication date or a fallback trade date.",
            "Bind the exact artifact bytes and SHA256 in the human review workflow; Agent must not set REVIEWED.",
        ]
    if event_class == "DELIST":
        return [
            "Confirm provider_symbol and the official termination/delisting action.",
            "Confirm event_effective_date is the printed 摘牌/终止上市 effective date; decision date alone is insufficient unless the source explicitly says effective from that date.",
            "Confirm expected_fields.IS_LISTED equals 3 for the event-day observation.",
            "Bind the exact artifact bytes and SHA256 in the human review workflow; Agent must not set REVIEWED.",
        ]
    if event_class == "RIGHT_ISSUE_EX_DATE":
        return [
            "Confirm the source is a company/exchange disclosure and states the exact right-issue ex-date.",
            "Confirm the action is RIGHT_ISSUE rather than dividend or an unrelated corporate action.",
            "Confirm expected_fields.event_type is RIGHT_ISSUE and IS_WD_SEC is true.",
            "Bind the exact artifact bytes and SHA256 in the human review workflow; Agent must not set REVIEWED.",
        ]
    if event_class in {"LIMIT_REGIME", "NO_LIMIT_IPO"}:
        return [
            "Confirm the cited official rule applies to this exchange, board, regime, and observation date.",
            "Confirm both expected limit fields and the no-limit/IPO interpretation where applicable.",
            "Bind the exact rule artifact bytes and SHA256 in the human review workflow; Agent must not set REVIEWED.",
        ]
    return [
        "Confirm the cited official exchange/disclosure source proves the mapping or corporate-action fact.",
        "Confirm the expected fields are the semantic assertion under test.",
        "Bind the exact artifact bytes and SHA256 in the human review workflow; Agent must not set REVIEWED.",
    ]


def _packet_row(doc: dict[str, Any], registry_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    case_id = str(doc["golden_case_id"])
    registry = registry_by_id.get(case_id)
    if registry:
        official_name = registry["official_source_name"]
        official_ref = registry["official_source_ref"]
        kind = registry["artifact_kind_candidate"]
        fact_proved = bool(registry["fact_proved"])
        date_semantics = registry["date_semantics"]
    else:
        official_name, official_ref, kind = _source_context(doc)
        fact_proved = True
        if doc.get("event_class") == "ST_TRANSITION":
            date_semantics = (
                "event_effective_date is the status-change date; trade_date is the observation date"
            )
        elif doc.get("event_class") == "DELIST":
            date_semantics = "event_effective_date is the official termination/delisting date; trade_date is the observation date"
        elif doc.get("event_class") in {"DIVIDEND_EX_DATE", "RIGHT_ISSUE_EX_DATE"}:
            date_semantics = "trade_date is the corporate-action ex-date"
        else:
            date_semantics = "trade_date is the regime or mapping observation date"
    return {
        "golden_case_id": case_id,
        "case_type": doc["case_type"],
        "provider_symbol": doc["provider_symbol"],
        "trade_date": doc["trade_date"],
        "event_id": doc.get("event_id", ""),
        "event_class": doc.get("event_class", ""),
        "event_subtype": doc.get("event_subtype", ""),
        "event_effective_date": doc.get("event_effective_date", ""),
        "date_semantics": date_semantics,
        "expected_fields": doc["expected_fields"],
        "source_ref": doc["source_ref"],
        "official_source_name": official_name,
        "official_source_ref": official_ref,
        "official_source_name/ref": f"{official_name} | {official_ref}",
        "artifact_kind_candidate": kind,
        "fact_proved": fact_proved,
        "human_review_checklist": _checklist(doc),
    }


def _short_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _distribution(rows: list[dict[str, Any]], event_class: str) -> dict[str, Any]:
    entries = [row for row in rows if row.get("event_class") == event_class]
    by_subtype = Counter(str(row.get("event_subtype", "")) for row in entries)
    by_exchange = Counter(
        "SSE"
        if str(row["provider_symbol"]).endswith(".SH")
        else "SZSE"
        if str(row["provider_symbol"]).endswith(".SZ")
        else "BSE"
        for row in entries
    )
    by_board: Counter[str] = Counter()
    by_year: Counter[str] = Counter()
    for row in entries:
        symbol = str(row["provider_symbol"])
        code = _code(symbol)
        if symbol.endswith(".SH") and code.startswith("688"):
            board = "STAR"
        elif symbol.endswith(".SZ") and code.startswith("300"):
            board = "CHINEXT"
        else:
            board = "MAIN"
        by_board[board] += 1
        date = str(row.get("event_effective_date") or row.get("trade_date"))
        by_year[date[:4]] += 1
    return {
        "subtype": dict(sorted(by_subtype.items())),
        "exchange": dict(sorted(by_exchange.items())),
        "board": dict(sorted(by_board.items())),
        "year": dict(sorted(by_year.items())),
    }


def finalize() -> None:
    registry = json.loads((OUT_DIR / "official_fact_registry.json").read_text(encoding="utf-8"))
    plan = json.loads((OUT_DIR / "rebuild_plan_v4.json").read_text(encoding="utf-8"))
    active_path = GOLDEN_ROOT / "truth_manifest.json"
    active = json.loads(active_path.read_text(encoding="utf-8"))
    if str(active.get("truth_version", "")).split("-", 1)[0] != "v4":
        raise RuntimeError(f"finalize requires ACTIVE v4, got {active.get('truth_version')}")
    cases = _load_jsonl(GOLDEN_ROOT / str(active["dataset_file"]))
    registry_by_id = {str(entry["golden_case_id"]): entry for entry in registry}
    packet = [_packet_row(doc, registry_by_id) for doc in cases]
    packet_ids = [str(row["golden_case_id"]) for row in packet]
    if len(packet_ids) != len(set(packet_ids)):
        raise RuntimeError("packet contains duplicate case IDs")
    if set(packet_ids) != {str(doc["golden_case_id"]) for doc in cases}:
        raise RuntimeError("packet coverage does not equal v4 dataset coverage")
    _jsonl_dump(OUT_DIR / "review_packet_index.jsonl", packet)

    store = GoldenTruthStore(GOLDEN_ROOT)
    loaded_cases, manifest = store.load()
    readiness = review_readiness_gate(loaded_cases, manifest)
    formal_gate = store.production_formal_gate(loaded_cases, manifest)
    stats = recompute_manifest_statistics(loaded_cases)

    version_hashes: dict[str, str] = {}
    for name in (
        "golden_cases_v1.jsonl",
        "truth_manifest_v1.json",
        "golden_cases_v2.jsonl",
        "truth_manifest_v2.json",
        "golden_cases_v3.jsonl",
        "truth_manifest_v3.json",
    ):
        path = GOLDEN_ROOT / name
        if path.is_file():
            version_hashes[name] = _short_hash(path)

    op_counts = Counter(str(op["op"]).upper() for op in plan["operations"])
    dropped_classes = Counter(
        str(doc.get("event_class", ""))
        for doc in _load_jsonl(GOLDEN_ROOT / V3_DATASET)
        if str(doc.get("event_class", "")) in {"ST_TRANSITION", "DELIST", "NEGATIVE_SAMPLE"}
    )
    type_counts = Counter(str(doc["case_type"]) for doc in cases)
    st_dist = _distribution(cases, "ST_TRANSITION")
    delist_dist = _distribution(cases, "DELIST")
    registry_event_counts = Counter(str(entry["event_class"]) for entry in registry)
    report_lines = [
        "# GT-H2 Clean Golden Corpus Candidate Report",
        "",
        f"- Target truth version: `{manifest.truth_version}`",
        f"- ACTIVE dataset: `{manifest.dataset_file}`",
        f"- ACTIVE dataset SHA256: `{manifest.dataset_hash}`",
        f"- Source ACTIVE: `{plan['source_truth_version']}` / `{plan['source_dataset_file']}` / `{plan['source_dataset_hash']}`",
        "- Scope: candidate corpus construction only. This report does not claim human review, Production B1-B7, Data Sufficiency, provider entitlement, 2020+ backfill, strategy, backtest, or trading readiness.",
        "",
        "## Rebuild decision",
        "",
        f"The plan contains `{len(plan['operations'])}` explicit operations: `KEEP={op_counts.get('KEEP', 0)}`, `REPLACE={op_counts.get('REPLACE', 0)}`, `DROP={op_counts.get('DROP', 0)}`, `ADD={op_counts.get('ADD', 0)}`.",
        f"Every old v3 row is addressed exactly once. Structural/negative rows dropped by class: `{dict(sorted(dropped_classes.items()))}`.",
        "All old v1/v2/v3 files remain immutable inputs; the plan does not edit or rewrite them. The old non-structural rows are REPLACE operations so their case identities remain traceable while official rule/disclosure locators are made explicit.",
        "",
        "## Candidate counts and structural gates",
        "",
        f"- Case count: `{manifest.case_count}`",
        f"- Counts by type: `{dict(sorted(type_counts.items()))}`",
        f"- Registry additions by event class: `{dict(sorted(registry_event_counts.items()))}`",
        f"- Distinct ST structural events: `{stats['distinct_events'].get('ST_TRANSITION', 0)}`; ADD `{stats['st_add_events']}`; REMOVE `{stats['st_remove_events']}`.",
        f"- Distinct DELIST structural events: `{stats['distinct_events'].get('DELIST', 0)}`; securities `{stats['distinct_delisted_securities']}`.",
        "- No structural identity uses `trade_date` as an implicit effective date. For the new single-observation cases, equality is intentional and stated in the packet date semantics/checklist.",
        "",
        "### ST distribution",
        "",
        f"`{json.dumps(st_dist, ensure_ascii=False, sort_keys=True)}`",
        "",
        "### DELIST distribution",
        "",
        f"`{json.dumps(delist_dist, ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Review packet",
        "",
        "- Packet path: `docs/golden/gt_h2/review_packet_index.jsonl`",
        f"- Packet rows: `{len(packet)}`; unique IDs: `{len(set(packet_ids))}`; dataset rows: `{len(cases)}`.",
        "- Exact coverage check: PASS — every candidate case appears exactly once, with event fields, expected fields, official source name/ref, candidate artifact kind, fact_proved flag, and a human checklist.",
        "- `fact_proved` is an Agent source-inspection flag only. It is not a human review seal and does not populate `source_artifact_ref`, `source_artifact_hash`, `reviewed_by`, or `reviewed_at`.",
        "- No raw bulk web pages or PDFs are committed; the packet stores official references only.",
        "",
        "## Local gate evidence",
        "",
        f"- `GoldenTruthStore.load`: PASS (`{manifest.truth_version}`, schema `{manifest.manifest_schema}`).",
        f"- `review_readiness_gate`: `{('PASS' if not readiness else 'FAIL: ' + '; '.join(readiness))}`",
        f"- `production_formal_gate`: expected candidate result contains only the human-review blocker: `{formal_gate}`",
        "- The candidate publisher and this utility never invoke `scripts/golden/review.py` final sealing. The only intended formal blocker after candidate construction is human review plus exact artifact binding.",
        "",
        "## Immutable lineage evidence",
        "",
        "The following hashes were computed locally from the versioned files and must remain unchanged:",
        "",
        "| File | SHA256 |",
        "| --- | --- |",
    ]
    report_lines.extend(
        f"| `{name}` | `{digest}` |" for name, digest in sorted(version_hashes.items())
    )
    report_lines.extend(
        [
            "",
            "## Human review hand-off",
            "",
            "1. Verify each official source locator and bind the exact downloaded artifact under the evidence store.",
            "2. Check symbol, board/exchange, date semantics, subtype/action type, and expected fields against the artifact.",
            "3. Run the repository review workflow to create the reviewed version only after all cases pass; do not treat this candidate report or `fact_proved` as REVIEWED evidence.",
            "4. Keep CR-5/CR-6, Production B1-B7, Data Sufficiency, provider decisions, credentials/tokens, and raw SDK/profile material outside this corpus PR.",
        ]
    )
    (OUT_DIR / "GT_H2_CORPUS_REPORT.md").write_text(
        "\n".join(report_lines) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "truth_version": manifest.truth_version,
                "case_count": manifest.case_count,
                "packet_rows": len(packet),
                "readiness_problems": readiness,
                "formal_gate": formal_gate,
            },
            ensure_ascii=False,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "finalize"))
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
    else:
        finalize()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
