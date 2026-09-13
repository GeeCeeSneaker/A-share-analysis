# CR-7 R1 research panel

R1 publishes a small, immutable `research_security_daily` panel from one
already verified CR-4 ReadModel snapshot. It does not call a Provider or read
Raw data. The machine-readable row/manifest contract is in
[`r1_research_contract_20260912.json`](r1_research_contract_20260912.json).

## Read a published split

The manifest path is required so the caller chooses a concrete published
version. The split is also required; Holdout is never mixed into Development
implicitly.

```python
from pathlib import Path

from ashare_state.research import load_research_security_daily

manifest = Path("data/research/<published-manifest>/manifest.json")
panel = load_research_security_daily(
    manifest,
    split="development",
    start="2020-01-01",
    end="2023-12-31",
    security_ids=["<canonical-security-id>"],
    columns=["trade_date", "security_id", "symbol", "close"],
)
```

`start`/`end` are inclusive and must stay inside the selected split. The
optional `security_ids` filter matches exact canonical `security_id` values;
it does not accept symbol prefixes or infer an exchange from a code. An empty
list deliberately returns no rows. The selected dataset version and source
lineage are available before the read:

```python
from ashare_state.research import ResearchPanelReader

reader = ResearchPanelReader.from_manifest(manifest)
print(reader.manifest.research_dataset_version, reader.manifest.dataset_id)
panel = reader.load_security_daily(
    split="development",
    security_ids=["<canonical-security-id>"],
    columns=["trade_date", "security_id", "close"],
)
```

The default reader returns only `RESEARCH_ENABLED` rows. Preserved unresolved
rows can be inspected only through the separate diagnostic
`load_disabled_research_security_daily()` entry point; they are never merged
into ordinary research reads.

The ordinary `research_security_daily` publisher is reachable only through
`ResearchPanelBuilder.build_from_readmodel()`. It verifies the CR-4 ReadModel
and derives `symbol/exchange` from the verified canonical `security_master`
output; caller-supplied rows, hashes, or identity mappings cannot mint an
authoritative manifest. If no verified identity source is available, display
identity stays null and the affected rows remain disabled. The manifest records
the concrete normalized identity artifact, hashes, run IDs, and PIT lineage.

Offline tests use a private `_build_fixture_from_rows()` helper and the visibly
separate `research_security_daily_fixture` dataset with
`publication_mode=TEST_ONLY_ROWS`. The ordinary reader rejects that dataset;
tests must opt in with `ResearchPanelReader.from_manifest(...,
allow_test_fixture=True)`.

Rows that are correctly typed but semantically ineligible are retained in the
diagnostic disabled artifact. A malformed or non-finite numeric ReadModel value
is a typed-input violation: the entire build fails closed and no partial
disabled artifact is published.

R1 also fails closed for the unresolved BSE historical old/new-code continuity
boundary. A BSE row may have a valid, verified security-master identity and
valid OHLCV, but it is still written to the disabled artifact with
`research_exclusion_reason=bse_identity_boundary_unresolved`; R1 disables all
BSE rows until a separately reviewed identity-continuity artifact is activated.
The panel does not infer or repair the `835185 -> 920185` mapping in this slice.

R1 fixes `price_basis=UNADJUSTED_CANONICAL` and
`universe_basis=OBSERVED_DAILY_BAR_UNIVERSE`. The latter is the observed daily
bar sample after the eligibility gate, not `ALL_A_SHARES`. Partial or
unresolved coverage is retained in the manifest but rejected by the default
research loader. R1 does not expose CR-5 feature columns; that join belongs to
R2 under its own lineage contract.

The index panel remains explicitly disabled as
`DISABLED_UNVERIFIED_INDEX_IDENTITY` until a versioned index identity/readmodel
path is verified. No index output is silently substituted.

## Build the fixed offline fixture

The implementation and full chain are covered by:

```text
uv run pytest -q tests/unit/test_r1_research_panel.py tests/integration/test_r1_research_panel_integration.py
```

No production credentials, endpoint, Provider response, or raw payload is
needed for this fixture.
