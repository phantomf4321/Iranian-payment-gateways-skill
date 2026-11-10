# Iranian payment gateways skill

Build one reusable Codex skill under `.agents/skills/iranian-payment-gateways`.
Phase 1 implements only Zarinpal; prioritize Django and keep transport separate
from payment orchestration. Do not add another provider incidentally.

Work on `zarinpal`, based on `master`. Preserve existing work, never force push,
and never merge or push implementation to `master` automatically.

Use Python 3.12+ and the pinned `requirements-dev.txt`. Keep `SKILL.md` concise;
put protocol evidence in references and adaptable executable code in assets.
Protocol changes require authoritative URLs, pinned source revisions, verification
dates, and matching tests. Document uncertainties rather than guessing behavior.

Never log secrets, raw gateway bodies, or card data. Use integer IRR internally,
server-owned prices, server verification, database locks and unique fulfillment
events. Never make live financial calls in tests or deploy automatically.

Run `python -m pytest`, `ruff check .`, `ruff format --check .`, and all three
validators as described in README. Run PostgreSQL tests when touching concurrency;
SQLite does not validate row locks. Update tests and references with behavior.
Keep required integration hooks explicit and fail closed if they are unconfigured.
