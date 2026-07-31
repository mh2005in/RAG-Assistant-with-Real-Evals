"""Tests for the strategy-agnostic page-exclusion request DTO."""

import pytest
from pydantic import ValidationError

from dtos.requests import PageExclusion, PageRange


def _exclusion(items: list[object]) -> PageExclusion:
    return PageExclusion.model_validate({"exclude_pages": items})


def test_defaults_to_excluding_nothing() -> None:
    assert PageExclusion().excluded_page_numbers() == set()


def test_flattens_single_page_numbers() -> None:
    assert _exclusion([1, 3]).excluded_page_numbers() == {1, 3}


def test_flattens_inclusive_ranges() -> None:
    assert _exclusion([{"start": 2, "end": 4}]).excluded_page_numbers() == {2, 3, 4}


def test_flattens_mixed_pages_and_ranges() -> None:
    exclusion = _exclusion([1, {"start": 10, "end": 12}, 5])

    assert exclusion.excluded_page_numbers() == {1, 5, 10, 11, 12}


def test_overlapping_entries_are_deduplicated() -> None:
    assert _exclusion([2, {"start": 1, "end": 3}]).excluded_page_numbers() == {1, 2, 3}


def test_rejects_page_numbers_below_one() -> None:
    with pytest.raises(ValidationError, match="page numbers must be >= 1"):
        _exclusion([0])


def test_rejects_reversed_range() -> None:
    with pytest.raises(ValidationError, match="must be >="):
        _exclusion([{"start": 5, "end": 2}])


def test_page_range_expands_to_its_pages() -> None:
    assert PageRange(start=3, end=5).pages() == {3, 4, 5}


class TestFromJsonArray:
    """The endpoint sends a bare JSON array, not a wrapper object."""

    def test_parses_mixed_pages_and_ranges(self) -> None:
        exclusion = PageExclusion.from_json_array('[1, {"start": 1, "end": 8}]')

        assert exclusion.excluded_page_numbers() == {1, 2, 3, 4, 5, 6, 7, 8}

    def test_parses_empty_array(self) -> None:
        assert PageExclusion.from_json_array("[]").excluded_page_numbers() == set()

    def test_rejects_malformed_json(self) -> None:
        with pytest.raises(ValidationError):
            PageExclusion.from_json_array("[1, ")

    def test_rejects_bad_page_numbers(self) -> None:
        with pytest.raises(ValidationError):
            PageExclusion.from_json_array("[0]")

    def test_rejects_a_wrapper_object(self) -> None:
        # The array is the contract; an object is not accepted.
        with pytest.raises(ValidationError):
            PageExclusion.from_json_array('{"exclude_pages": [1]}')
