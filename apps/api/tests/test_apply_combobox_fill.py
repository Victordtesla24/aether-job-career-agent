"""The submission agent must OPERATE React typeahead comboboxes, not just type.

Regression for the owner-reported Easygo (Greenhouse) failure 2026-08-15:
``_fill_value`` had no ``combobox`` branch, so the three required screening
dropdowns fell through to ``.fill()`` — text the widget never commits — and the
site rejected the submit (honest ``no_confirmation``). The branch must click
the widget, type the planned answer, then click the matching popup option; a
missing match with an ambiguous popup is an honest ``False`` (recorded as
unfilled), never a blind commit of whatever is highlighted.
"""
from __future__ import annotations

from typing import Any

from app.services.apply_executor import _fill_value


class _Locator:
    def __init__(self, present: bool, page: "_Page", label: str) -> None:
        self._present = present
        self._page = page
        self._label = label

    # Playwright surface used by _fill_value / _first_present ------------- #
    def count(self) -> int:
        return 1 if self._present else 0

    @property
    def first(self) -> "_Locator":
        return self

    def click(self, timeout: int | None = None) -> None:
        self._page.actions.append(("click", self._label))

    def fill(self, value: str, timeout: int | None = None) -> None:
        self._page.actions.append(("fill", self._label, value))


class _Page:
    """Fake page: selector substrings mapped to present/absent locators."""

    def __init__(self, present: dict[str, bool]) -> None:
        self._present = present
        self.actions: list[tuple[Any, ...]] = []

    def locator(self, selector: str) -> _Locator:
        for key, present in self._present.items():
            if key in selector:
                return _Locator(present, self, key)
        return _Locator(False, self, selector)


_FIELD = {"name": "question_11746985007", "kind": "combobox"}


def test_combobox_clicks_the_matching_popup_option() -> None:
    page = _Page({'[id="question_11746985007"]': True, '[role="option"]:text-is': True})
    assert _fill_value(page, _FIELD, "Yes", {}) is True
    kinds = [a[0] for a in page.actions]
    # opened the widget, typed the answer, then committed the matching option
    assert kinds == ["click", "fill", "click"]
    assert ("fill", '[id="question_11746985007"]', "Yes") in page.actions


def test_combobox_commits_the_single_narrowed_candidate() -> None:
    # no literal text match, but the typeahead narrowed the popup to ONE option
    page = _Page(
        {
            '[id="question_11746985007"]': True,
            ":text-is": False,
            ":has-text": False,
            '[role="option"], [class*="select__option"]': True,
        }
    )
    assert _fill_value(page, _FIELD, "Australia", {}) is True
    assert page.actions[-1][0] == "click"  # committed the lone candidate


def test_combobox_refuses_when_popup_is_ambiguous() -> None:
    class _ManyLocator(_Locator):
        def count(self) -> int:  # 2+ candidates -> genuine ambiguity
            return 2

    class _AmbiguousPage(_Page):
        def locator(self, selector: str) -> _Locator:
            if selector == '[role="option"], [class*="select__option"]':
                return _ManyLocator(True, self, selector)
            return super().locator(selector)

    page = _AmbiguousPage({'[id="question_11746985007"]': True, ":text-is": False, ":has-text": False})
    assert _fill_value(page, _FIELD, "Something vague", {}) is False


def test_combobox_absent_control_is_an_honest_false() -> None:
    assert _fill_value(_Page({}), _FIELD, "Yes", {}) is False


class _OptionListLocator(_Locator):
    """A popup listing real option texts (the cleared-filter full list)."""

    def __init__(self, page: "_Page", texts: list[str]) -> None:
        super().__init__(True, page, "options")
        self._texts = texts

    def count(self) -> int:
        return len(self._texts)

    def nth(self, idx: int) -> "_OptionItem":
        return _OptionItem(self._page, self._texts[idx])


class _OptionItem:
    def __init__(self, page: "_Page", text: str) -> None:
        self._page = page
        self._text = text

    def inner_text(self) -> str:
        return self._text

    def click(self, timeout: int | None = None) -> None:
        self._page.actions.append(("chose", self._text))


class _FullListPage(_Page):
    """Literal matches miss; the cleared filter exposes the full option list."""

    def __init__(self, texts: list[str]) -> None:
        super().__init__({'[id="question_11746985007"]': True, ":text-is": False, ":has-text": False})
        self._texts = texts

    def locator(self, selector: str) -> _Locator:
        if selector == '[role="option"], [class*="select__option"]':
            return _OptionListLocator(self, self._texts)
        return super().locator(selector)


def test_combobox_commits_the_dominant_token_match_from_the_full_list() -> None:
    # The live Easygo case: answer "Australian Citizen" vs canonical phrasings.
    page = _FullListPage(
        [
            "I am an Australian/New Zealand Citizen",
            "I am a Permanent Resident",
            "I have a valid visa with no work restrictions",
            "I require visa sponsorship",
        ]
    )
    assert _fill_value(page, _FIELD, "Australian Citizen", {}) is True
    assert ("chose", "I am an Australian/New Zealand Citizen") in page.actions


def test_combobox_refuses_a_token_tie_between_options() -> None:
    # Both options share the same 2 tokens with the answer -> ambiguity -> False.
    page = _FullListPage(
        [
            "Melbourne Australia office",
            "Melbourne Australia remote",
        ]
    )
    assert _fill_value(page, _FIELD, "Melbourne Australia", {}) is False
    assert not any(a[0] == "chose" for a in page.actions)
