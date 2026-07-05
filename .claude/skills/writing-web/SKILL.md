---
name: writing-web
description: Conventions for the Next.js frontend (web/). Read before adding or editing pages, components, hooks, API calls, or types under web/.
---

# Writing web/ code

Stack: Next.js App Router, React 19, TypeScript strict, Tailwind v4, TanStack Query v5.

## Data fetching — one path, no exceptions

All HTTP goes through `web/lib/api.ts`:
1. `fetchX()` function using the private `apiGet<T>` helper / `ApiError` pattern,
2. a `queryKeys.x` entry,
3. an `xQueryOptions()` factory.
Components call `useQuery(xQueryOptions(...))` — never a raw `fetch` in a component.
Response types live in `web/lib/types.ts` and mirror the Java DTO record field-for-field
(camelCase, Java nullable wrapper types → `| null`).

## Where logic lives

- **Pick/outcome grading**: `web/lib/picks.ts` owns it (`propOutcome`, `runLineOutcome`, …).
  Extend it there; never re-derive grading inside a component.
- **Formatting**: shared formatters (`pct`, `signedPct`, …) live in `web/lib/format.ts`
  (being consolidated in the cleanup — if it doesn't exist yet, create it rather than adding
  another inline `pct`).
- **Selection/veto business logic** (edge gates, EV thresholds): `web/lib/`, not the render tree.
  Components present; libs decide.

## UI primitives — import, don't redefine

- `microLabel` (the tiny uppercase label class string), `Skeleton`, and the label-over-value
  stat tile are shared primitives (`components/game/ui.tsx` / `components/ui/` — consolidation
  in progress). Never paste the class string or re-declare a local `Skeleton`/`Stat` variant.
- Card scaffolding (header chip row + `OutcomeBadge` + matchup link + why-disclosure) is shared
  structure — compose the existing card pieces instead of copying a card file.
- Styling: Tailwind utilities + `cn()` from `lib/utils.ts`; variants via `cva` (see
  `components/ui/button.tsx`).

## Pages

Route = thin **server** `page.tsx` (exports `metadata`, renders the board) + a **client**
board/view component that owns the queries. Retired routes keep a cheap `redirect()` stub
(see `app/mlb/most-likely/page.tsx`).

## Done =

`npx tsc --noEmit` clean and `npm run lint` clean (CI enforces both plus `next build`).
Pure logic added to `lib/` should get a vitest test once the test harness exists.
