"""Offline tests for the 429 backoff/retry helper and Retry-After parsing."""

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest
import requests

from ffs_triumph.client import (
    RequestRetryFailure,
    TriumphClient,
    _parse_retry_after,
)


class FakeResponse:
    def __init__(self, status_code=200, headers=None, json_data=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._json = json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            err = requests.exceptions.HTTPError(f"{self.status_code} Error")
            err.response = self
            raise err

    def json(self):
        return self._json


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, params=None, **kwargs):
        self.calls.append(url)
        return self._responses.pop(0)


def make_client(responses):
    """A TriumphClient with a fake session, bypassing __init__ (and its login call)."""
    c = TriumphClient.__new__(TriumphClient)
    c.verbose = 0
    c.session = FakeSession(responses)
    return c


@pytest.fixture
def slept(monkeypatch):
    """Capture sleep durations instead of actually sleeping."""
    durations = []
    monkeypatch.setattr("ffs_triumph.client.time.sleep", durations.append)
    return durations


# -- _parse_retry_after -------------------------------------------------------

def test_parse_retry_after_numeric():
    assert _parse_retry_after("30") == 30.0


@pytest.mark.parametrize("value", [None, "", "soon"])
def test_parse_retry_after_absent_or_garbage(value):
    assert _parse_retry_after(value) is None


def test_parse_retry_after_http_date():
    future = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=45))
    assert _parse_retry_after(future) == pytest.approx(45, abs=2)


def test_parse_retry_after_past_date_clamps_to_zero():
    assert _parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0


# -- _get_with_backoff_retry --------------------------------------------------

def test_succeeds_after_429_uses_exponential_backoff(slept):
    ok = FakeResponse(json_data={"ok": True})
    client = make_client([FakeResponse(status_code=429), ok])

    resp = client._get_with_backoff_retry("http://x/api")

    assert resp is ok
    assert len(client.session.calls) == 2
    # First sleep is the polite REQUEST_DELAY; the retry uses backoff_base**1 == 3.
    assert slept == [0.15, 3]


def test_honors_retry_after_header(slept):
    ok = FakeResponse(json_data={"ok": True})
    throttled = FakeResponse(status_code=429, headers={"Retry-After": "7"})
    client = make_client([throttled, ok])

    resp = client._get_with_backoff_retry("http://x/api")

    assert resp is ok
    # The retry waits exactly what the server asked for, not the 3s schedule.
    assert slept == [0.15, 7.0]


def test_gives_up_after_retries(slept):
    client = make_client([FakeResponse(status_code=429), FakeResponse(status_code=429)])

    with pytest.raises(RequestRetryFailure):
        client._get_with_backoff_retry("http://x/api", retries=1)

    assert len(client.session.calls) == 2  # initial attempt + 1 retry


def test_non_429_reraises_without_retry(slept):
    client = make_client([FakeResponse(status_code=500)])

    with pytest.raises(requests.exceptions.HTTPError):
        client._get_with_backoff_retry("http://x/api")

    assert len(client.session.calls) == 1  # no retry on non-429
