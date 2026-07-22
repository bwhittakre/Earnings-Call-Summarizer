"""earnings-scraper: earnings-call ingestion into an Angelo zettelkasten.

Two entry points, one destination (the ``inbox/`` folder):

* Manual  — drop report files into ``inbox/`` (see ``scripts/stage_inbox.py``).
* Automated (future) — pull transcripts from the LSEG StreetEvents Snowflake
  share into ``inbox/`` (see ``scripts/pull_to_inbox.py``), once the share is
  provisioned to the account.

Whatever lands in ``inbox/`` is crunched by the coordinator (grounded extraction
via ``create_extraction_graph``) — no external LLM API key or Stream driver: the
extraction agents are local Cursor subagents the coordinator spawns.
"""

__version__ = "0.1.0"
