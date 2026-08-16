"""S1 — inbound BACKLOG scan.

Live defect (owner's manual run returned all zeros): ``_poll_account`` defaulted
its watermark to ``now - 86400`` with ``max_results=50``, so a Gmail account
that had just been (re)connected only ever looked at the last 24 hours. Every
real prospect email that arrived BEFORE the connection was invisible — forever,
because the watermark then jumped to ``now`` on the very first run.

What this suite pins:

1. first sight of an account scans ``AETHER_SALES_BACKLOG_DAYS`` (default 90)
   back, not 24 hours, and the window is configurable;
2. the scan stays bounded by ``max_results`` per run, and successive runs walk
   the remaining backlog until caught up (paging via the watermark);
3. the watermark NEVER advances past mail that was not actually scanned — while
   a backlog remains it does not jump to "now";
4. watermark rows whose Gmail account no longer exists are pruned at run start
   (idempotently), so a deleted account cannot leave a stale watermark behind;
5. every one of the above holds under EVERY reading of Gmail's ``after:`` /
   ``before:`` epoch bounds (:data:`tests._sales_fakes.BOUNDARY_READINGS`).
   Google documents those operators by example and never states whether either
   bound is inclusive, so a walk that only works under one reading silently
   loses mail under the other three — and the run result would say
   ``tieDrained: {messages: 0}`` with no error, which looks exactly like proof
   of coverage. The window arithmetic must therefore be reading-INDEPENDENT.
"""
from __future__ import annotations

import re
import time
import uuid

import pytest

from app.agents.sales_agent import INBOUND_MAX_RESULTS, sales_backlog_days
from tests._sales_fakes import (
    BOUNDARY_READINGS,
    RecordingLLM,
    WindowedGmail,
    agent_for,
    make_message,
)
from tests.test_sales_agent import (  # type: ignore[import-untyped]
    admin_headers,  # noqa: F401 — fixture
    repo,  # noqa: F401 — fixture
    sales_env,  # noqa: F401 — fixture
)

_AFTER = re.compile(r"after:(\d+)")
_BEFORE = re.compile(r"before:(\d+)")


def _acct() -> str:
    return f"acct-s1-{uuid.uuid4().hex[:10]}"


def _noise_llm() -> RecordingLLM:
    """Classifier that judges everything 'noise' — keeps these tests about the
    SCAN WINDOW, never about lead creation."""
    return RecordingLLM({"category": "noise", "confidence": 0.95, "reason": "internal"})


# ------------------------------------------------------------------ window
def test_backlog_days_default_is_90(monkeypatch):
    monkeypatch.delenv("AETHER_SALES_BACKLOG_DAYS", raising=False)
    assert sales_backlog_days() == 90


def test_first_sight_scans_the_backlog_not_only_24_hours(repo, sales_env, monkeypatch):  # noqa: F811
    """The regression itself: an account with no stored watermark must look 90
    days back. Before the fix the query said ``after:{now-86400}``."""
    monkeypatch.delenv("AETHER_SALES_BACKLOG_DAYS", raising=False)
    fake = WindowedGmail([])
    agent = agent_for(repo, fake, monkeypatch, account_id=_acct(), llm=_noise_llm())
    before = int(time.time())

    agent.run(trigger="manual")

    assert fake.queries, "the account was never polled"
    after_epoch = int(_AFTER.search(fake.queries[0]).group(1))
    span_days = (before - after_epoch) / 86400.0
    assert 89.5 <= span_days <= 90.5, (
        f"first-sight scan window was {span_days:.2f} days — a reconnected "
        "account never sees its existing inbox history"
    )


def test_backlog_window_is_configurable(repo, sales_env, monkeypatch):  # noqa: F811
    monkeypatch.setenv("AETHER_SALES_BACKLOG_DAYS", "30")
    fake = WindowedGmail([])
    agent = agent_for(repo, fake, monkeypatch, account_id=_acct(), llm=_noise_llm())
    before = int(time.time())

    agent.run(trigger="manual")

    after_epoch = int(_AFTER.search(fake.queries[0]).group(1))
    span_days = (before - after_epoch) / 86400.0
    assert 29.5 <= span_days <= 30.5


def test_scan_stays_bounded_per_run(repo, sales_env, monkeypatch):  # noqa: F811
    """Bounded work per run — the cap is unchanged, only the WINDOW grew."""
    now = int(time.time())
    msgs = [
        make_message(
            sender=f"bulk-{i}@example.com", subject="Weekly team notes",
            text="Notes from the team meeting.", epoch=now - i * 3600,
        )
        for i in range(INBOUND_MAX_RESULTS + 25)
    ]
    fake = WindowedGmail(msgs)
    agent = agent_for(repo, fake, monkeypatch, account_id=_acct(), llm=_noise_llm())

    result = agent.run(trigger="manual")

    assert fake.max_results[0] == INBOUND_MAX_RESULTS
    assert result["inboundScanned"] == INBOUND_MAX_RESULTS


# ------------------------------------------------------------------- paging
def test_successive_runs_walk_the_backlog_until_caught_up(repo, sales_env, monkeypatch):  # noqa: F811
    """120 messages over 30 days, 50 per run: three runs scan every one of
    them, and only then does the watermark declare the backlog clear."""
    account_id = _acct()
    now = int(time.time())
    total = 120
    msgs = [
        make_message(
            sender=f"backlog-{i}@example.com", subject="Weekly team notes",
            text="Notes from the team meeting.", epoch=now - (i + 1) * 6 * 3600,
        )
        for i in range(total)
    ]
    fake = WindowedGmail(msgs)
    scanned_per_run: list[int] = []

    for run_no in range(3):
        agent = agent_for(
            repo, fake, monkeypatch, account_id=account_id, llm=_noise_llm()
        )
        result = agent.run(trigger="manual")
        scanned_per_run.append(result["inboundScanned"])
        account = result["accounts"][0]
        if run_no < 2:
            assert account["backlogRemaining"] is True, (
                f"run {run_no + 1} claimed the backlog was clear with "
                f"{total - sum(scanned_per_run)} messages never scanned"
            )
        else:
            assert account["backlogRemaining"] is False

    # Bounded per run, and every single message reached — the page boundary is
    # deliberately INCLUSIVE (``before:<oldest scanned>``), so a message may be
    # re-seen once rather than risk skipping a sibling sharing its timestamp.
    assert all(n <= INBOUND_MAX_RESULTS for n in scanned_per_run), scanned_per_run
    assert set(fake.fetched) == {m["id"] for m in msgs}, (
        "the backlog walk skipped messages"
    )
    assert sum(scanned_per_run) <= total + 2, (
        f"page overlap is larger than one message per boundary: {scanned_per_run}"
    )
    ceilings = [int(_BEFORE.search(q).group(1)) for q in fake.queries]
    assert ceilings[1] < ceilings[0] and ceilings[2] < ceilings[1], (
        "the scan window never moved — the backlog would never be walked"
    )


def test_watermark_never_jumps_to_now_while_a_backlog_remains(repo, sales_env, monkeypatch):  # noqa: F811
    account_id = _acct()
    now = int(time.time())
    msgs = [
        make_message(
            sender=f"deep-{i}@example.com", subject="Weekly team notes",
            text="Notes from the team meeting.", epoch=now - (i + 1) * 6 * 3600,
        )
        for i in range(INBOUND_MAX_RESULTS + 10)
    ]
    fake = WindowedGmail(msgs)
    agent = agent_for(repo, fake, monkeypatch, account_id=account_id, llm=_noise_llm())

    agent.run(trigger="manual")

    wm = repo.get_watermark(account_id)
    assert wm, "no watermark stored"
    # Floor stays at the backlog floor — it must NOT have jumped to now.
    assert now - int(wm["lastEpoch"]) > 80 * 86400, (
        "the watermark jumped forward past messages that were never scanned"
    )
    # ... and the unscanned ceiling is recorded so the next run resumes there.
    cursor = int(wm["backlogCursorEpoch"])
    oldest_scanned = min(
        int(int(m["internalDate"]) / 1000)
        for m in sorted(msgs, key=lambda m: -int(m["internalDate"]))[:INBOUND_MAX_RESULTS]
    )
    assert cursor <= oldest_scanned


def test_watermark_clears_the_backlog_only_when_the_window_is_exhausted(
    repo, sales_env, monkeypatch  # noqa: F811
):
    account_id = _acct()
    now = int(time.time())
    fake = WindowedGmail([
        make_message(
            sender="one@example.com", subject="Weekly team notes",
            text="Notes from the team meeting.", epoch=now - 5 * 86400,
        )
    ])
    agent = agent_for(repo, fake, monkeypatch, account_id=account_id, llm=_noise_llm())

    result = agent.run(trigger="manual")

    assert result["accounts"][0]["backlogRemaining"] is False
    wm = repo.get_watermark(account_id)
    assert wm.get("backlogCursorEpoch") in (None, 0)
    assert abs(int(wm["lastEpoch"]) - now) < 300, (
        "an exhausted window must move the watermark up to the run time"
    )


# ---------------------------------------------------------------- pruning
def test_orphan_watermarks_are_pruned_at_run_start(repo, sales_env, monkeypatch):  # noqa: F811
    """A deleted Gmail account must not leave its watermark behind forever."""
    ghost = f"ghost-{uuid.uuid4().hex[:10]}"
    live = _acct()
    repo.set_watermark(ghost, {"lastEpoch": 1700000000})
    assert repo.get_watermark(ghost)

    fake = WindowedGmail([])
    agent = agent_for(repo, fake, monkeypatch, account_id=live, llm=_noise_llm())
    result = agent.run(trigger="manual")

    assert repo.get_watermark(ghost) == {}, "stale watermark row survived the run"
    assert result["watermarksPruned"] >= 1
    # The account being polled RIGHT NOW is never pruned.
    assert repo.get_watermark(live)

    # Idempotent: a second run prunes nothing and does not fail.
    agent2 = agent_for(repo, fake, monkeypatch, account_id=live, llm=_noise_llm())
    result2 = agent2.run(trigger="manual")
    assert result2["watermarksPruned"] == 0


# -------------------------------------------------- same-second tie blocks
# Gmail's ``internalDate`` has whole-second resolution and the page cap is per
# REQUEST, so a mailbox can hold more messages in ONE second than a single page
# can return (bulk import, a migrated inbox, a mailing-list burst). The walk
# moves its ceiling by TIMESTAMP, so that second is the one place the ceiling
# cannot step down without stepping OVER messages nobody looked at. These tests
# are the adversarial case the reviewer asked for.
def _tied_messages(epoch: int, count: int, tag: str) -> list[dict]:
    return [
        make_message(
            sender=f"{tag}-{i}@example.com", subject="Weekly team notes",
            text="Notes from the team meeting.", epoch=epoch,
        )
        for i in range(count)
    ]


def _walk_until_caught_up(
    repo, monkeypatch, fake, account_id: str, max_runs: int  # noqa: F811
) -> list[dict]:
    """Run the agent until the backlog clears (or ``max_runs`` is spent)."""
    results: list[dict] = []
    for _ in range(max_runs):
        agent = agent_for(
            repo, fake, monkeypatch, account_id=account_id, llm=_noise_llm()
        )
        result = agent.run(trigger="manual")
        results.append(result)
        if result["accounts"] and not result["accounts"][0]["backlogRemaining"]:
            break
    return results


@pytest.mark.parametrize("boundary", BOUNDARY_READINGS)
def test_same_second_tie_bigger_than_a_page_is_never_silently_skipped(
    repo, sales_env, monkeypatch, boundary  # noqa: F811
):
    """55 messages sharing ONE whole second, page cap 50.

    Every one of them must be scanned before the walk drops below that second.
    The failure this pins is silent loss: the ceiling clamps to ``second - 1``
    once it can no longer move, and the 5 messages the page never returned are
    never looked at again — while the run reports the backlog fully scanned.

    Run under all four boundary readings: the drain must actually reach the
    tied second no matter how Gmail resolves ``after:``/``before:``.
    """
    account_id = _acct()
    tie_epoch = int(time.time()) - 3600
    msgs = _tied_messages(tie_epoch, INBOUND_MAX_RESULTS + 5, "tie")
    fake = WindowedGmail(msgs, boundary=boundary)

    results = _walk_until_caught_up(repo, monkeypatch, fake, account_id, 6)

    assert not results[-1]["accounts"][0]["backlogRemaining"], (
        "the walk never caught up in 6 runs — the account is stalled on a "
        "same-second tie and can no longer see NEW mail above it"
    )
    missing = {m["id"] for m in msgs} - set(fake.fetched)
    assert not missing, (
        f"{len(missing)} of {len(msgs)} messages sharing epoch {tie_epoch} were "
        "never scanned, yet the run declared the backlog clear"
    )


@pytest.mark.parametrize("boundary", BOUNDARY_READINGS)
def test_tie_block_far_larger_than_a_page_still_completes_and_is_scanned(
    repo, sales_env, monkeypatch, boundary  # noqa: F811
):
    """A 130-message single-second block: all scanned, walk still terminates."""
    account_id = _acct()
    tie_epoch = int(time.time()) - 7200
    msgs = _tied_messages(tie_epoch, 130, "burst")
    fake = WindowedGmail(msgs, boundary=boundary)

    results = _walk_until_caught_up(repo, monkeypatch, fake, account_id, 6)

    assert not results[-1]["accounts"][0]["backlogRemaining"], results[-1]["accounts"]
    assert set(fake.fetched) == {m["id"] for m in msgs}, (
        "the walk skipped part of a single-second burst"
    )


@pytest.mark.parametrize("boundary", BOUNDARY_READINGS)
def test_new_mail_above_a_tie_block_is_still_seen(
    repo, sales_env, monkeypatch, boundary  # noqa: F811
):
    """The stall this guards against is worse than the bug it replaced: an
    account wedged on a tie stops seeing genuinely NEW prospect mail."""
    account_id = _acct()
    now = int(time.time())
    tie_epoch = now - 3600
    msgs = _tied_messages(tie_epoch, INBOUND_MAX_RESULTS + 5, "wedge")
    fake = WindowedGmail(msgs, boundary=boundary)

    _walk_until_caught_up(repo, monkeypatch, fake, account_id, 6)

    fresh = make_message(
        sender="new-prospect@example.com", subject="Weekly team notes",
        text="Notes from the team meeting.", epoch=int(time.time()),
    )
    fake.messages.append(fresh)
    agent = agent_for(repo, fake, monkeypatch, account_id=account_id, llm=_noise_llm())
    result = agent.run(trigger="manual")

    assert fresh["id"] in fake.fetched, (
        "mail newer than the tie block was never scanned — the account is "
        "locked out of new prospect mail"
    )
    assert result["inboundScanned"] >= 1


@pytest.mark.parametrize("boundary", BOUNDARY_READINGS)
def test_tie_block_above_the_drain_cap_is_disclosed_never_silently_dropped(
    repo, sales_env, monkeypatch, boundary  # noqa: F811
):
    """Pathological: more messages in one second than the drain cap allows.

    The only two honest outcomes are 'scanned' or 'said out loud'. Silence is
    not one of them, and neither is a permanent stall.
    """
    account_id = _acct()
    monkeypatch.setenv("AETHER_SALES_TIE_MAX_RESULTS", "60")
    tie_epoch = int(time.time()) - 5400
    msgs = _tied_messages(tie_epoch, 80, "flood")
    fake = WindowedGmail(msgs, boundary=boundary)

    results = _walk_until_caught_up(repo, monkeypatch, fake, account_id, 6)

    assert not results[-1]["accounts"][0]["backlogRemaining"], (
        "the walk stalled instead of advancing past a disclosed overflow"
    )
    unscanned = {m["id"] for m in msgs} - set(fake.fetched)
    if unscanned:
        disclosed = [
            e for r in results for e in r["errors"] if str(tie_epoch) in e
        ]
        assert disclosed, (
            f"{len(unscanned)} messages at epoch {tie_epoch} were skipped with "
            "nothing in the run result saying so"
        )
        overflow = [
            a.get("tieOverflow")
            for r in results for a in r["accounts"] if a.get("tieOverflow")
        ]
        assert overflow and overflow[0]["epoch"] == tie_epoch, (
            "the per-account summary must name the second it could not drain"
        )


# ------------------------------------------- the QUERY the walk actually sends
# The tests above prove behaviour through the fake. These prove the property the
# fake can never prove on its own: that the STRING sent to Gmail is not a range
# whose emptiness depends on an assumption about Gmail's boundary semantics.
def _ranges(queries: list[str]) -> list[tuple[int, int]]:
    return [
        (int(_AFTER.search(q).group(1)), int(_BEFORE.search(q).group(1)))
        for q in queries
        if _AFTER.search(q) and _BEFORE.search(q)
    ]


def _matched(epoch: int, lo: int, hi: int, reading: str) -> bool:
    """Does ``after:lo before:hi`` match ``epoch`` under ``reading``?"""
    lo_ok = epoch >= lo if reading in ("after_inclusive", "inclusive") else epoch > lo
    hi_ok = epoch <= hi if reading in ("before_inclusive", "inclusive") else epoch < hi
    return lo_ok and hi_ok


def test_window_query_covers_its_closed_window_under_every_reading():
    """``_window_query(lo, hi)`` must match every epoch in ``[lo, hi]`` no
    matter which of the four readings Gmail implements.

    This is the property the round-2 code got wrong: ``after:X before:X`` is
    self-contradictory (empty) under three of the four readings, so the drain
    it powered returned nothing and the walk stepped past a second nobody had
    looked at — silently.
    """
    from app.agents.sales_agent import _window_query  # noqa: PLC0415

    for lo, hi in ((1700000000, 1700000000), (1700000000, 1700000600)):
        query = _window_query(lo, hi)
        (after, before), = _ranges([query])
        assert before - after >= 2, (
            f"{query!r} is a degenerate range: no integer epoch can satisfy it "
            "under a strict reading of after:/before:"
        )
        for reading in BOUNDARY_READINGS:
            for epoch in (lo, (lo + hi) // 2, hi):
                assert _matched(epoch, after, before, reading), (
                    f"{query!r} misses epoch {epoch} of window [{lo}, {hi}] "
                    f"under the {reading!r} reading"
                )


@pytest.mark.parametrize("boundary", BOUNDARY_READINGS)
def test_no_query_the_walk_sends_is_a_degenerate_range(
    repo, sales_env, monkeypatch, boundary  # noqa: F811
):
    """Every query issued during a real tie-drain walk — page AND drain — must
    be a range that can match something under a strict reading."""
    account_id = _acct()
    tie_epoch = int(time.time()) - 3600
    msgs = _tied_messages(tie_epoch, INBOUND_MAX_RESULTS + 5, "shape")
    fake = WindowedGmail(msgs, boundary=boundary)

    _walk_until_caught_up(repo, monkeypatch, fake, account_id, 6)

    ranges = _ranges(fake.queries)
    assert ranges, "no windowed query was ever issued"
    for after, before in ranges:
        assert before - after >= 2, (
            f"degenerate query range after:{after} before:{before} — empty "
            "under every reading except both-bounds-inclusive"
        )
    # ... and the drain specifically must cover the tied second itself.
    drain = [r for r in ranges if r[0] <= tie_epoch <= r[1] and r[1] - r[0] == 2]
    assert drain, (
        f"no query bracketed the tied second {tie_epoch} — the boundary was "
        "never drained, so the walk could only have guessed past it"
    )


class _UnreachableBoundaryGmail(WindowedGmail):
    """Gmail whose boundary-drain call comes back EMPTY.

    Stands in for any world where the drain query does not resolve to the
    second the code believes it does — a semantics change, a different reading,
    an index lag. The point is that the code must not be able to tell the
    difference between that and 'zero further tied messages' by ASSUMPTION: it
    knows at least one message sits at the boundary second, so an empty drain
    is proof the drain failed, not proof the second is clear.
    """

    def __init__(self, messages, *, page_cap: int, **kwargs):
        super().__init__(messages, **kwargs)
        self._page_cap = page_cap

    def list_message_headers(self, query=None, max_results=100):  # noqa: ANN001
        headers = super().list_message_headers(query=query, max_results=max_results)
        if max_results != self._page_cap:  # the drain call uses the tie cap
            return []
        return headers


def test_a_drain_that_returns_nothing_is_never_read_as_a_clear_boundary(
    repo, sales_env, monkeypatch  # noqa: F811
):
    """The silent-skip signature, pinned.

    55 messages share one second; the drain comes back empty. The only honest
    outcomes are 'held and said out loud'. Declaring the backlog clear while 5
    messages were never fetched is the exact production defect.
    """
    account_id = _acct()
    tie_epoch = int(time.time()) - 3600
    msgs = _tied_messages(tie_epoch, INBOUND_MAX_RESULTS + 5, "blind")
    fake = _UnreachableBoundaryGmail(msgs, page_cap=INBOUND_MAX_RESULTS)

    results = _walk_until_caught_up(repo, monkeypatch, fake, account_id, 4)

    missing = {m["id"] for m in msgs} - set(fake.fetched)
    if missing:
        assert all(
            r["accounts"][0]["backlogRemaining"] for r in results
        ), (
            f"{len(missing)} messages at epoch {tie_epoch} were never fetched, "
            "yet a run declared the backlog clear — silent loss"
        )
        disclosed = [e for r in results for e in r["errors"] if str(tie_epoch) in e]
        assert disclosed, (
            "the walk could not drain the boundary second and said nothing "
            "about it in the run result"
        )
    unverified = [
        a.get("tieDrainUnverified")
        for r in results for a in r["accounts"] if a.get("tieDrainUnverified")
    ]
    assert unverified and unverified[0]["epoch"] == tie_epoch, (
        "an unverifiable boundary drain must be named on the account summary, "
        "not reported as tieDrained: {messages: 0}"
    )
    assert all(
        not a.get("tieDrained") for r in results for a in r["accounts"]
    ), "an unreachable second must never be reported as a drained one"
    explained = [r["explanation"] for r in results if str(tie_epoch) in r["explanation"]]
    assert explained, (
        "the founder-readable explanation never mentions the second the walk "
        f"is held on ({tie_epoch}): "
        + " | ".join(r["explanation"] for r in results)
    )
