import pytest
import logging

from zigpy_znp.logger import _find_trace_level


def test_no_trace_level():
    # If no TRACE level exists, make TRACE == DEBUG
    assert _find_trace_level() == logging.DEBUG


def monkeypatch_addLevelName(monkeypatch, level, levelName):
    monkeypatch.setitem(logging._levelToName, level, levelName)
    monkeypatch.setitem(logging._nameToLevel, levelName, level)


@pytest.mark.parametrize("trace_level", [1, 2, 3, 4, 5, 6, 7, 8, 9])
def test_existing_trace_level(trace_level, monkeypatch):
    monkeypatch_addLevelName(monkeypatch, trace_level, "TRACE")

    monkeypatch.setattr(logging, "TRACE", trace_level, raising=False)
    assert logging.TRACE == trace_level

    # If a TRACE level already exists and TRACE < DEBUG, we use it
    assert _find_trace_level() == trace_level


def test_bad_trace_level(monkeypatch):
    monkeypatch_addLevelName(monkeypatch, logging.DEBUG + 1, "TRACE")

    # If a TRACE level already exists but TRACE >= DEBUG, we use DEBUG
    assert _find_trace_level() == logging.DEBUG
