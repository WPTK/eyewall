# Milestones

Each milestone is one working session, one branch (`mN-<slug>`), one pull request and one release. The brief for a
milestone is self-contained: a session reads `CLAUDE.md`, `docs/plan.md`, `docs/data-sources.md` and its own brief, and
nothing else is needed.

```
M0 scaffold
 ├─► M1 NHC data ──────────┐
 ├─► M2 observations data ─┼─► M4 core ─► M5 storm UI ─► M6 observations UI ─► M7 graphics ─► M8 release
 └─► M3 renderer + basemap ┘ (M3 feeds M5 directly)
```

M1, M2 and M3 touch disjoint directories and can run at the same time, each in its own git worktree with its own `.venv`.
Everything after M3 runs in order.

| Milestone | Brief | Release | Status |
|---|---|---|---|
| M0 Scaffold and handoff | [M0-scaffold.md](M0-scaffold.md) | 0.0.1 | done |
| M1 NHC data layer | [M1-nhc-data.md](M1-nhc-data.md) | 0.1.0 | not started |
| M2 Observations data layer | [M2-observations-data.md](M2-observations-data.md) | 0.2.0 | done |
| M3 Renderer and basemap | [M3-renderer.md](M3-renderer.md) | 0.3.0 | not started |
| M4 Core | [M4-core.md](M4-core.md) | 0.4.0 | not started |
| M5 Storm UI | [M5-storm-ui.md](M5-storm-ui.md) | 0.5.0 | not started |
| M6 Observations UI | [M6-observations-ui.md](M6-observations-ui.md) | 0.6.0 | not started |
| M7 Graphics | [M7-graphics.md](M7-graphics.md) | 0.7.0 | not started |
| M8 Polish and release | [M8-release.md](M8-release.md) | 0.8.0 | not started |

Update the status column in the same pull request that finishes a milestone.

## Starting a session

> Implement milestone Mn of this repo per `docs/milestones/Mn-<slug>.md`; branch `mN-<slug>`, PR to `main`, CI green,
> release `0.N.0`.

## Brief format

Every brief has the same headings: **Goal**, **Depends on**, **Scope**, **Out of scope**, **Done when**, **Verify**,
**State after**. The session fills in **State after** before opening its pull request: what exists, what deviated from the
plan and why, and what the next session must know.
