"""L1 subscription SCRIPT wiring tests (R4-A3.2 P1-01, audit 20260828).

The shipped bug: ``scripts/spike/l1_subscription_test.py`` created a real
``SdkLifecycle`` and immediately rebound the SAME name to a plain dict -
so ``SubscriptionController`` received a dict (no ``transition``), and
``state = lifecycle.state`` / ``lifecycle.close()`` were dead or would
AttributeError. Component tests passed while the real script wiring was
broken.

These tests execute the REAL script control flow
(``execute_subscription_flow``) with an injected fake SDK:

- fake login already done -> flow reaches SUBSCRIBE_STARTED ->
  CALLBACK_ACTIVE -> UNSUBSCRIBED through the REAL state machine;
- no AttributeError / type shadowing anywhere in the flow;
- the verdict derives from the SAME SdkLifecycle object;
- logout/close terminal handling remains safe (idempotent close);

plus an AST guard so the dict-shadowing regression cannot ship again.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

from ashare_state.providers.lifecycle import SdkLifecycleState

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "spike" / "l1_subscription_test.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("l1_subscription_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _FakePeriod:
    class snapshot:
        value = 1


class _FakeBaseData:
    def get_code_list(self, security_type=None):
        return ["600519.SH", "000001.SZ", "430047.BJ", "600520.SH"]


class _FakeSubscribeData:
    """Records the SDK subscription surface; run() simulates one market
    snapshot arriving so the callback path is exercised."""

    def __init__(self) -> None:
        self.registered: list[tuple[list[str], object]] = []
        self.callbacks: list = []
        self.ran = 0
        self.unregistered: list[tuple[list[str], object]] = []
        self.stopped = 0

    def register(self, *, code_list, period, callback) -> None:
        self.registered.append((code_list, period))
        self.callbacks.append(callback)

    def run(self) -> None:
        self.ran += 1
        for callback in list(self.callbacks):
            callback({"security_code": "600519.SH", "last_price": 1700.5, "data_time": "093000123"})

    def unregister(self, *, code_list, period) -> None:
        self.unregistered.append((code_list, period))

    def stop(self) -> None:
        self.stopped += 1


class _FakeAmazingData:
    Period = _FakePeriod

    def __init__(self) -> None:
        self.base = _FakeBaseData()
        self.subscriber = _FakeSubscribeData()

    def BaseData(self):
        return self.base

    def SubscribeData(self):
        return self.subscriber


def _run_flow(fake: _FakeAmazingData, stage: int = 2):
    module = _load_script_module()
    return module.execute_subscription_flow(
        fake,
        stage,
        duration_seconds=0,
        sleep=lambda _seconds: None,
        monotonic=lambda: 100.0,
    )


@pytest.mark.integration
class TestL1ScriptSubscriptionWiring:
    def test_flow_drives_the_real_state_machine_end_to_end(self):
        """register -> run (callback) -> unregister/stop through the REAL
        SdkLifecycle: the flow completes with no AttributeError and the
        state machine - not a dict - is the correctness SoR."""
        fake = _FakeAmazingData()
        report, lifecycle = _run_flow(fake)

        # the returned object IS the state machine and reached the
        # happy-path terminal subscription state
        assert isinstance(lifecycle.state, SdkLifecycleState)
        assert lifecycle.state is SdkLifecycleState.UNSUBSCRIBED
        # the full real path was driven (no fake SUBSCRIBE_STARTED)
        transitions = [t["to"] for t in report["lifecycle_state_machine"]["transitions"]]
        assert transitions == [
            "SESSION_READY",
            "SUBSCRIBE_STARTED",
            "CALLBACK_ACTIVE",
            "UNSUBSCRIBED",
        ]
        # the verdict derives from the SAME SdkLifecycle object
        assert report["lifecycle_state_machine"]["state"] == "UNSUBSCRIBED"
        assert report["lifecycle_verdict"] == "PASS"
        assert report["status"] == "PASS"
        # the callback path actually produced events
        assert report["events_received"] == 1
        # the SDK subscription surface was actually driven
        assert fake.subscriber.registered
        assert fake.subscriber.unregistered
        assert fake.subscriber.stopped == 1
        assert fake.subscriber.ran == 1

    def test_register_failure_is_reported_not_faked(self):
        """An SDK register failure surfaces as NOT_TESTABLE_PERMISSION
        with the diagnostic view - the state machine never advances."""

        class _RegisterRefused(_FakeSubscribeData):
            def register(self, *, code_list, period, callback) -> None:
                raise RuntimeError("register refused")

        fake = _FakeAmazingData()
        fake.subscriber = _RegisterRefused()
        report, lifecycle = _run_flow(fake, stage=1)

        assert report["status"] == "NOT_TESTABLE_PERMISSION"
        assert str(report["lifecycle"]["register"]).startswith("ERROR")
        # no fake SUBSCRIBE_STARTED: still at SESSION_READY
        assert lifecycle.state is SdkLifecycleState.SESSION_READY

    def test_terminal_close_is_safe_after_flow(self):
        """The logout path: close() is the idempotent terminal transition
        on the SAME lifecycle object the flow used."""
        fake = _FakeAmazingData()
        report, lifecycle = _run_flow(fake, stage=1)
        assert lifecycle.state is SdkLifecycleState.UNSUBSCRIBED

        lifecycle.close(reason="logout", evidence_ref="ad.logout")
        assert lifecycle.state is SdkLifecycleState.LOGGED_OUT
        # idempotent: a second close (e.g. retry in a finally block) is safe
        lifecycle.close(reason="logout again", evidence_ref="ad.logout")
        assert lifecycle.state is SdkLifecycleState.LOGGED_OUT


@pytest.mark.integration
class TestL1ScriptNoShadowingGuard:
    """Static guard (audit 20260828 P1-01): the SdkLifecycle variable
    must never be rebound/annotated as a dict in the script."""

    def test_lifecycle_is_never_rebound_to_a_dict(self):
        source = SCRIPT.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "lifecycle"
            ):
                annotation = ast.unparse(node.annotation)
                assert "dict" not in annotation, (
                    "`lifecycle` re-annotated as a dict - the R4-A3.2 P1-01 shadowing bug is back"
                )
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "lifecycle":
                        assert not isinstance(node.value, ast.Dict), (
                            "`lifecycle` rebound to a dict literal - the "
                            "R4-A3.2 P1-01 shadowing bug is back"
                        )

    def test_controller_receives_the_state_machine_variable(self):
        """The SubscriptionController constructor call must be wired to
        the ``sdk_lifecycle`` SoR variable, not a diagnostic dict."""
        source = SCRIPT.read_text(encoding="utf-8")
        tree = ast.parse(source)
        wired = False
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "SubscriptionController"
                and node.args
            ):
                first = node.args[0]
                if isinstance(first, ast.Name):
                    wired = first.id == "sdk_lifecycle"
        assert wired, (
            "SubscriptionController must receive the sdk_lifecycle state "
            "machine (SoR), never a diagnostic dict"
        )
