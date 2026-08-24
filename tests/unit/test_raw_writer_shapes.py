"""R4-A2.3 P0-03: RawWriter payload-shape tests (audit section 5).

MANDATORY shapes: list[dict] / dict[str, list[dict]] / DataFrame /
dict[str, DataFrame] / pyarrow.Table. dict-of-tables uses scheme A (one
Parquet per logical table); "take the first dict value" is forbidden.
Round-trips are verified FIELD BY FIELD (values, nullable types, Chinese
text, NaN/None), not just by row counts.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pytest

from ashare_state.providers.amazingdata.provider import RawEnvelope
from ashare_state.providers.exchange import ProviderExchange
from ashare_state.storage.raw_writer import RawWriter, RawWriterError


def _envelope(request_id: str, dataset: str, *, status: str = "OK") -> RawEnvelope:
    return RawEnvelope(
        provider="amazingdata",
        provider_dataset=dataset,
        endpoint="Test.endpoint",
        request_id=request_id,
        requested_at="2026-08-24T00:00:00+00:00",
        received_at="2026-08-24T00:00:01+00:00",
        status=status,
        error_class=None if status == "OK" else "ProviderTestError",
        account_profile_id="TRIAL_TEST",
    )


def _exchange(request_id: str, dataset: str, payload, *, status: str = "OK"):
    return ProviderExchange(envelope=_envelope(request_id, dataset, status=status), payload=payload)


def _cells_equal(left, right) -> bool:
    """Field-by-field comparison: NaN/None are equivalent to each other,
    Decimal values compare numerically, everything else by ==."""
    import math

    if isinstance(left, (datetime, date)):
        left = left.isoformat()
    if isinstance(right, (datetime, date)):
        right = right.isoformat()
    if isinstance(left, Decimal) and isinstance(right, (int, float, Decimal)):
        return Decimal(str(right)) == left
    if isinstance(right, Decimal) and isinstance(left, (int, float)):
        return Decimal(str(left)) == right
    if left is None and right is None:
        return True
    if left is None or right is None:
        # None == NaN equivalence (float('nan') stored/retrieved as null)
        try:
            return math.isnan(float(left if right is None else right))
        except (TypeError, ValueError):
            return False
    if isinstance(left, float) and isinstance(right, float):
        return math.isnan(left) and math.isnan(right) or left == right
    return left == right


class TestWriteExchangeContract:
    def test_write_consumes_exchange_with_envelope_first_metadata(self, tmp_path: Path):
        writer = RawWriter(tmp_path)
        result = writer.write(_exchange("req-1", "ds1", [{"a": 1}]))
        assert result.request_id == "req-1"
        assert result.payload_kind == "rows"
        assert result.evidence_uri.endswith("req-1.parquet")
        assert result.evidence_hash == result.content_hash
        meta = tmp_path / "provider=amazingdata" / "dataset=ds1" / "req-1.meta.json"
        assert meta.is_file()

    def test_request_id_consistency_assertion_blocks(self, tmp_path: Path):
        writer = RawWriter(tmp_path)
        # duck-typed exchange whose request_id DISAGREES with its envelope
        # (the assertion must catch a future divergence, audit 3.2-C)
        class _Mismatched:
            request_id = "req-A"

            def __init__(self) -> None:
                self.envelope = _envelope("req-B", "ds1")
                self.payload = []

        with pytest.raises(RawWriterError, match="request_id inconsistency"):
            writer.write(_Mismatched())  # type: ignore[arg-type]

        # an empty request id is also rejected
        class _Empty:
            request_id = ""

            def __init__(self) -> None:
                self.envelope = _envelope("", "ds1")
                self.payload = []

        with pytest.raises(RawWriterError, match="request_id inconsistency"):
            writer.write(_Empty())  # type: ignore[arg-type]

    def test_external_provider_conflict_blocks(self, tmp_path: Path):
        writer = RawWriter(tmp_path)
        exchange = _exchange("req-1", "ds1", [])
        with pytest.raises(RawWriterError, match="provider conflict"):
            writer.write(exchange, provider="other-provider")
        with pytest.raises(RawWriterError, match="dataset conflict"):
            writer.write(_exchange("req-2", "ds1", []), dataset="ds2")

    def test_failure_exchange_writes_envelope_only_meta(self, tmp_path: Path):
        writer = RawWriter(tmp_path)
        result = writer.write(_exchange("req-err", "ds1", None, status="ERROR"))
        assert result.logical_uri is None  # no payload artifact
        meta = tmp_path / "provider=amazingdata" / "dataset=ds1" / "req-err.meta.json"
        assert meta.is_file()
        assert result.evidence_uri.endswith("req-err.meta.json")
        assert result.payload_kind == "failure"

    def test_missing_envelope_blocks(self, tmp_path: Path):
        writer = RawWriter(tmp_path)
        with pytest.raises(RawWriterError, match="ProviderExchange"):
            writer.write("not-an-exchange")  # type: ignore[arg-type]


class TestPayloadShapes:
    def test_rows_round_trip(self, tmp_path: Path):
        writer = RawWriter(tmp_path)
        rows = [
            {"code": "600519", "close": 1850.5},
            {"code": "000001", "close": 12.34},
        ]
        writer.write(_exchange("r1", "rows_ds", rows))
        back = writer.read(provider="amazingdata", dataset="rows_ds", request_id="r1")
        assert back.shape[0] == 2
        # field-by-field (not just row count)
        cells = back.to_dict(as_series=False)
        assert cells["code"] == ["600519", "000001"]
        assert cells["close"] == [1850.5, 12.34]

    def test_dataframe_round_trip_values_and_types(self, tmp_path: Path):
        polars = pytest.importorskip("polars")
        writer = RawWriter(tmp_path)
        frame = polars.DataFrame(
            {
                "code": ["600519", "000001"],
                "close": [1850.5, 12.34],
                "volume": [1_000_000, 2_000_000],
                "trade_date": [date(2022, 6, 30), date(2022, 7, 1)],
            }
        )
        result = writer.write(_exchange("df1", "frame_ds", frame))
        assert result.payload_kind == "dataframe"
        assert result.row_count == 2
        back = writer.read(provider="amazingdata", dataset="frame_ds", request_id="df1")
        assert isinstance(back, polars.DataFrame)
        assert back.shape == (2, 4)
        for col in ("code", "close", "volume", "trade_date"):
            original = frame.get_column(col).to_list()
            restored = back.get_column(col).to_list()
            assert len(original) == len(restored)
            for left, right in zip(original, restored, strict=True):
                assert _cells_equal(left, right), (col, left, right)

    def test_nullable_and_nan_and_chinese_round_trip(self, tmp_path: Path):
        polars = pytest.importorskip("polars")
        writer = RawWriter(tmp_path)
        frame = polars.DataFrame(
            {
                "名称": ["贵州茅台", "平安银行", None],  # Chinese + null string
                "收盘价": [1850.5, None, float("nan")],  # None + NaN
                "数量": [1, None, 3],  # nullable int (becomes null-typed)
                "因子": ["0.9737", None, "1.05"],
            }
        )
        writer.write(_exchange("cn1", "cn_ds", frame))
        back = writer.read(provider="amazingdata", dataset="cn_ds", request_id="cn1")
        assert back.shape == (3, 4)
        names = back.get_column("名称").to_list()
        assert names[0] == "贵州茅台" and names[1] == "平安银行"
        assert names[2] is None
        closes = back.get_column("收盘价").to_list()
        assert closes[0] == 1850.5
        # parquet preserves None as null; NaN stays NaN (value fidelity)
        assert closes[1] is None
        import math

        assert math.isnan(closes[2])
        volumes = back.get_column("数量").to_list()
        assert volumes[0] == 1 and volumes[1] is None and volumes[2] == 3

    def test_empty_dataframe_round_trip(self, tmp_path: Path):
        polars = pytest.importorskip("polars")
        writer = RawWriter(tmp_path)
        frame = polars.DataFrame(schema={"code": polars.String, "close": polars.Float64})
        result = writer.write(_exchange("e1", "empty_ds", frame))
        assert result.payload_kind == "dataframe"
        assert result.row_count == 0
        back = writer.read(provider="amazingdata", dataset="empty_ds", request_id="e1")
        assert back.shape[0] == 0
        assert set(back.columns) == {"code", "close"}

    def test_arrow_table_round_trip(self, tmp_path: Path):
        writer = RawWriter(tmp_path)
        table = pa.table({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        result = writer.write(_exchange("ar1", "arrow_ds", table))
        assert result.payload_kind == "arrow_table"
        back = writer.read(provider="amazingdata", dataset="arrow_ds", request_id="ar1")
        assert back.get_column("a").to_list() == [1, 2, 3]
        assert back.get_column("b").to_list() == ["x", "y", "z"]

    def test_dict_of_rows_multi_table_scheme_a(self, tmp_path: Path):
        writer = RawWriter(tmp_path)
        payload = {
            "status": [{"SECURITY_CODE": "600519", "IS_ST_SEC": 0}],
            "calendar": [{"day": 20220630}],
        }
        result = writer.write(_exchange("m1", "multi_ds", payload))
        assert result.payload_kind == "multi_table_rows"
        assert len(result.tables) == 2
        table_names = {t.name for t in result.tables}
        assert table_names == {"status", "calendar"}
        # scheme A: one parquet per logical table + a meta listing them all
        dataset_dir = tmp_path / "provider=amazingdata" / "dataset=multi_ds"
        assert (dataset_dir / "m1" / "status.parquet").is_file()
        assert (dataset_dir / "m1" / "calendar.parquet").is_file()
        assert not (dataset_dir / "m1.parquet").is_file()
        # multi-table evidence binds to the meta (all tables listed + hashed)
        assert result.evidence_uri.endswith("m1.meta.json")
        back = writer.read(provider="amazingdata", dataset="multi_ds", request_id="m1")
        assert set(back.keys()) == {"status", "calendar"}
        assert back["status"].get_column("SECURITY_CODE").to_list() == ["600519"]
        assert back["calendar"].get_column("day").to_list() == [20220630]

    def test_dict_of_dataframes_multi_table_scheme_a(self, tmp_path: Path):
        polars = pytest.importorskip("polars")
        writer = RawWriter(tmp_path)
        payload = {
            "kline": polars.DataFrame({"close": [10.0, 10.5]}),
            "status": polars.DataFrame({"is_st": [0]}),
        }
        result = writer.write(_exchange("m2", "multi_ds", payload))
        assert result.payload_kind == "multi_table_frames"
        assert {t.name for t in result.tables} == {"kline", "status"}
        back = writer.read(provider="amazingdata", dataset="multi_ds", request_id="m2")
        assert back["kline"].get_column("close").to_list() == [10.0, 10.5]
        assert back["status"].get_column("is_st").to_list() == [0]

    def test_scalar_list_round_trips_as_value_column(self, tmp_path: Path):
        writer = RawWriter(tmp_path)
        writer.write(_exchange("cal1", "calendar_ds", [20220629, 20220630, 20220701]))
        back = writer.read(provider="amazingdata", dataset="calendar_ds", request_id="cal1")
        assert back.get_column("value").to_list() == [20220629, 20220630, 20220701]

    def test_mixed_dict_shapes_rejected(self, tmp_path: Path):
        writer = RawWriter(tmp_path)
        with pytest.raises(RawWriterError, match="silently taking one dict value is forbidden"):
            writer.write(_exchange("bad1", "bad_ds", {"status": [], "weird": 42}))
        with pytest.raises(RawWriterError, match="unsupported payload shape"):
            writer.write(_exchange("bad2", "bad_ds", {"a": [1, 2], "b": [{"x": 1}]}))

    def test_scalar_payload_rejected(self, tmp_path: Path):
        writer = RawWriter(tmp_path)
        with pytest.raises(RawWriterError, match="unsupported payload shape"):
            writer.write(_exchange("bad3", "bad_ds", 12345))

    def test_none_payload_writes_empty_artifact(self, tmp_path: Path):
        writer = RawWriter(tmp_path)
        result = writer.write(_exchange("n1", "none_ds", None))
        assert result.payload_kind == "empty"
        assert result.row_count == 0
        assert (tmp_path / "provider=amazingdata" / "dataset=none_ds" / "n1.parquet").is_file()


class TestImmutability:
    def test_same_request_same_bytes_is_idempotent(self, tmp_path: Path):
        writer = RawWriter(tmp_path)
        payload = [{"a": 1}]
        first = writer.write(_exchange("idem", "ds", payload))
        second = writer.write(_exchange("idem", "ds", payload))
        assert first.idempotent is False
        assert second.idempotent is True

    def test_same_request_different_bytes_blocks(self, tmp_path: Path):
        writer = RawWriter(tmp_path)
        writer.write(_exchange("conflict", "ds", [{"a": 1}]))
        with pytest.raises(RawWriterError, match="different content"):
            writer.write(_exchange("conflict", "ds", [{"a": 2}]))


class TestReadIntegrity:
    def test_read_missing_request_raises(self, tmp_path: Path):
        writer = RawWriter(tmp_path)
        with pytest.raises(RawWriterError, match="no raw meta"):
            writer.read(provider="amazingdata", dataset="ds", request_id="nope")
