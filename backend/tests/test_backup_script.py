"""backup.sh run against a stub `docker` (no containers needed)."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(shutil.which("bash") is None or not (REPO / "backup.sh").exists(),
                                reason="needs bash and the repository's backup.sh")

DOCKER_STUB = r"""#!/usr/bin/env bash
case "$1 $2" in
  "compose ps") echo cid ;;
  "compose exec") echo "SELECT 1;" ;;
  "compose pause"|"compose unpause") ;;
  inspect*) echo img ;;
  run*) vol=""; out=""; prev=""
    for a in "$@"; do
      [ "$prev" = "-v" ] && vol="${a%%:/backup*}"
      [ "$prev" = "-czf" ] && out="${a#/backup/}"
      prev="$a"
    done
    [ "$out" = "${FAIL_ON:-}" ] && exit 2
    echo data > "$vol/$out" ;;
esac
"""

DF_STUB = """#!/bin/sh
echo "Filesystem 1024-blocks Used Available Capacity Mounted"
echo "fake 1000 900 100 90% /"
"""


@pytest.fixture
def install(tmp_path):
    root = tmp_path / "mentis"
    root.mkdir()
    shutil.copy(REPO / "backup.sh", root / "backup.sh")
    (root / ".env").write_text("MENTIS_SECRET_KEY=x\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(DOCKER_STUB)
    (bin_dir / "docker").chmod(0o755)
    return root, bin_dir


def run(root, bin_dir, *args, **env):
    e = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", **env}
    return subprocess.run(["bash", str(root / "backup.sh"), *args], env=e, capture_output=True, text=True, timeout=60)


def test_backup_writes_a_complete_folder(install):
    root, bin_dir = install
    r = run(root, bin_dir)
    assert r.returncode == 0, r.stdout + r.stderr
    [dest] = list((root / "backups").iterdir())
    assert {"postgres.sql.gz", "minio.tar.gz", "qdrant.tar.gz", "env.backup", "manifest.txt", "SHA256SUMS"} <= {
        p.name for p in dest.iterdir()}


def test_failed_backup_never_deletes_an_existing_folder(install, tmp_path):
    root, bin_dir = install
    usb = tmp_path / "usb"
    usb.mkdir()
    (usb / "keep.txt").write_text("precious")
    r = run(root, bin_dir, str(usb), FAIL_ON="qdrant.tar.gz")
    assert r.returncode != 0
    assert (usb / "keep.txt").read_text() == "precious"


def test_free_space_check_measures_the_previous_backup(install):
    root, bin_dir = install
    old = root / "backups" / "mentis-20000101-000000"
    old.mkdir(parents=True)
    (old / "manifest.txt").write_text("x")
    (old / "minio.tar.gz").write_bytes(b"\0" * 2_000_000)
    (bin_dir / "df").write_text(DF_STUB)  # 100 KB free
    (bin_dir / "df").chmod(0o755)
    r = run(root, bin_dir)
    assert r.returncode == 1
    assert "Not enough free disk space" in r.stdout
    assert [p.name for p in (root / "backups").iterdir()] == [old.name]
