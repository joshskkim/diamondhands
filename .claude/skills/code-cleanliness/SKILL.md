---
name: code-cleanliness
description: Cross-cutting rules for writing or changing ANY code in this repo (web, api, ingester, mcp-server). Read before writing new functions, helpers, components, or files. Core principle - function and cleanliness; write only what is necessary.
---

# Code cleanliness — write only what's necessary

## Before writing anything new

1. **Search for an existing implementation first.** This repo's history shows helpers get forked,
   not reused — `pct()` existed 9× with divergent null-handling, `Skeleton` 5×, upsert boilerplate
   50×. Grep for the concept (name, not just exact signature) across the layer before writing.
2. **Extend the canonical util; never fork it.** If an existing helper almost fits, add the
   parameter or overload there. If two near-copies already exist, unify them as part of your change
   rather than adding a third.
3. **No speculative code.** No abstractions for hypothetical future callers, no unused parameters,
   no config flags nothing reads, no "might need this later" exports. A helper earns existence at
   its second caller, not its first.

## While changing existing code

- **Delete dead code you find** — but verify zero inbound references first (grep imports/usages
  across the whole repo including `web/`, `api/`, `ingester/`, `mcp-server/`; a page with no inbound
  links is still reachable by URL — confirm intent before deleting routes). Git history preserves it.
- **Leave the file cleaner than you found it, but keep the diff reviewable.** Opportunistic cleanup
  belongs in the files you're already touching; repo-wide sweeps are their own PR.
- Match the surrounding idiom (naming, comment density, error style). Consistency beats personal
  preference.

## Definition of done (every change)

- Layer checks pass: `web` → `npx tsc --noEmit`; `api` → `mvn -B -ntp verify` (needs JDK 21);
  `ingester` → `uv run pytest -q` + `uv run ruff check .`.
- Behavior-preserving refactors need evidence: tests green before AND after, and for output-shaped
  code (API responses, projections) a before/after diff of real output.
- New logic gets a test in the layer's convention (see writing-web / writing-api /
  writing-ingester skills).
