"""run_round1_reader: the record of the index actually searched, and the --expect-index-version guard (no API calls)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "eval" / "vendor")]
import run_round1_reader as rr  # noqa: E402


class Retr:
    def __init__(self, meta):
        self.meta = meta


def test_chroma_backend_records_the_chroma_dir_not_the_preset_index():
    s = rr.searched_index(Retr({"index_version": "37c4eb2f1628"}), "chroma", "data/fullplus/chroma_C1", "data/round1/index_C1")
    assert s == {"dir": "data/fullplus/chroma_C1", "index_version": "37c4eb2f1628"}


def test_custom_backend_records_the_index_dir():
    s = rr.searched_index(Retr({"index_version": "7a7ad9801f86"}), "custom", "data/round1/chroma_C1", "data/round1/index_C1")
    assert s["dir"] == "data/round1/index_C1" and s["index_version"] == "7a7ad9801f86"


def test_retriever_without_meta_records_no_version():
    assert rr.searched_index(object(), "chroma", "x", "y")["index_version"] is None


def test_guard_passes_on_match_and_when_not_asked():
    s = {"dir": "data/fullplus/chroma_C1", "index_version": "37c4eb2f1628"}
    rr.check_expected_index(s, "37c4eb2f1628")
    rr.check_expected_index(s, None)


def test_guard_stops_on_a_different_or_missing_version():
    with pytest.raises(SystemExit, match="expected index_version 7a7ad9801f86, data/fullplus/chroma_C1 has 37c4eb2f1628"):
        rr.check_expected_index({"dir": "data/fullplus/chroma_C1", "index_version": "37c4eb2f1628"}, "7a7ad9801f86")
    with pytest.raises(SystemExit):
        rr.check_expected_index({"dir": "x", "index_version": None}, "7a7ad9801f86")
