"""Real bounded subprocess behavior, including descendants after parent exit."""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import pytest

from reposcope.adapters.source_process import ProcessRunner
from reposcope.domain.source import SourceLimits, SourceRejected


def test_bounded_output(tmp_path: Path) -> None:
    runner = ProcessRunner(tmp_path, SourceLimits(output_bytes=1024), threading.Event())
    with pytest.raises(SourceRejected, match="SOURCE_OUTPUT_LIMIT"):
        runner.run([sys.executable, "-c", "print('x'*100000)"], dict(os.environ))


@pytest.mark.parametrize("parent_exits", [True, False])
def test_descendant_is_killed(tmp_path: Path, parent_exits: bool) -> None:
    heartbeat = tmp_path / "heartbeat"
    child = (
        "import pathlib,time; p=pathlib.Path(" + repr(str(heartbeat)) + "); "
        "\nwhile True:\n p.write_text(str(time.time())); time.sleep(.02)"
    )
    parent = (
        "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c'," + repr(child) + "]); "
    )
    parent += "time.sleep(.2)" if parent_exits else "time.sleep(30)"
    runner = ProcessRunner(tmp_path, SourceLimits(deadline_seconds=1), threading.Event())
    if parent_exits:
        runner.run([sys.executable, "-c", parent], dict(os.environ))
    else:
        with pytest.raises(SourceRejected, match="SOURCE_DEADLINE"):
            runner.run([sys.executable, "-c", parent], dict(os.environ))
    assert heartbeat.exists()
    before = heartbeat.read_text()
    time.sleep(0.2)
    assert heartbeat.read_text() == before


def test_disk_growth_is_stopped(tmp_path: Path) -> None:
    code = (
        "import pathlib,time; p=pathlib.Path('growth'); f=p.open('wb');\n"
        "while True:\n f.write(b'x'*8192); f.flush(); time.sleep(.01)"
    )
    runner = ProcessRunner(
        tmp_path, SourceLimits(disk_bytes=16384, deadline_seconds=3), threading.Event()
    )
    with pytest.raises(SourceRejected, match="SOURCE_DISK_LIMIT"):
        runner.run([sys.executable, "-c", code], dict(os.environ))
    size = (tmp_path / "growth").stat().st_size
    time.sleep(0.2)
    assert (tmp_path / "growth").stat().st_size == size


def test_cancellation_is_observed(tmp_path: Path) -> None:
    stopped = threading.Event()
    timer = threading.Timer(0.2, stopped.set)
    timer.start()
    try:
        with pytest.raises(SourceRejected, match="SOURCE_CANCELLED"):
            ProcessRunner(tmp_path, SourceLimits(), stopped).run(
                [sys.executable, "-c", "import time; time.sleep(30)"], dict(os.environ)
            )
    finally:
        timer.join()
