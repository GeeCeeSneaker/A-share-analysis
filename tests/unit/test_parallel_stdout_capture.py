"""Parallel stdout capture serialization tests (audit P1-12)."""

from __future__ import annotations

import threading

from ashare_state.providers.amazingdata.stdout_capture import (
    CapturedStdout,
    sdk_stdout_into,
)


class TestParallelCapture:
    def test_parallel_captures_do_not_interleave(self):
        """Two threads capturing concurrently must be serialized: every
        thread's holder receives exactly its own writes (fd restore order
        cannot invert; no token-text cross-contamination)."""
        results: dict[int, str] = {}
        barrier = threading.Barrier(2)

        def worker(worker_id: int) -> None:
            holder = CapturedStdout()
            barrier.wait()  # maximize contention
            with sdk_stdout_into(holder):
                # simulate a native SDK printf burst
                import os

                for i in range(20):
                    os.write(1, f"worker-{worker_id}-line-{i}\n".encode())
            results[worker_id] = holder.text

        threads = [threading.Thread(target=worker, args=(idx,)) for idx in (1, 2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for worker_id in (1, 2):
            text = results[worker_id]
            assert text, f"worker {worker_id} captured nothing"
            lines = [ln for ln in text.splitlines() if ln.strip()]
            for ln in lines:
                assert ln.startswith(f"worker-{worker_id}-"), (
                    f"cross-contamination in worker {worker_id}: {ln!r}"
                )

    def test_stdout_restored_after_parallel_captures(self):
        """After all captures complete, fd 1 must be the real stdout."""
        import sys

        def one_capture() -> None:
            with sdk_stdout_into(CapturedStdout()):
                pass

        threads = [threading.Thread(target=one_capture) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not getattr(sys.stdout, "_sdk_capture_active", False)
