"""Job-discovery source adapters and the Scout agent (P2-S02).

Each adapter fetches a job-board search-results page and parses it into a
uniform :class:`~app.services.discovery.base_adapter.JobRaw` list. Adapters
accept an optional ``fixture`` (raw HTML) so tests parse recorded/representative
markup with the same code path used against the live sites.
"""
