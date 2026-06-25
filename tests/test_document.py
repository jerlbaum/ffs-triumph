"""Offline tests for document-title composition."""

from ffs_triumph.document import display_title


def test_year_woven_after_separator():
    assert (display_title("Service Manual - Speed Triple 1200 RS", "2022")
            == "Service Manual - 2022 Speed Triple 1200 RS")


def test_no_year_returns_title_unchanged():
    assert display_title("Service Manual - Speed Triple 1200 RS", None) \
        == "Service Manual - Speed Triple 1200 RS"


def test_year_already_present_not_duplicated():
    assert display_title("2022 Speed Triple 1200 RS", "2022") == "2022 Speed Triple 1200 RS"


def test_no_separator_prefixes_year():
    assert display_title("Speed Triple Manual", "2022") == "2022 Speed Triple Manual"
