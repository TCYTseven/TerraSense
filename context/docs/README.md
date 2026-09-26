# Docs index

Read these in order if you are new, or if you just pulled.

1. [`TEAM_BRIEF.md`](TEAM_BRIEF.md) — two minutes. Status, setup, who owns which track.
2. [`TEAM_HANDOFF.md`](TEAM_HANDOFF.md) — what is decided, what exists, and how to resume.
3. [`../9-26-todo.md`](../9-26-todo.md) — open work for Saturday, Sep 26, 2026.
4. [`../TerraSense.md`](../TerraSense.md) — the product. If a feature is not in its hackathon scope, do not build it.
5. [`../implementation-steps.md`](../implementation-steps.md) — the 31 steps, split into pending and done.
6. [`UX.md`](UX.md) — before you add a screen or a control.
7. [`CODE_REFERENCE.md`](CODE_REFERENCE.md) — when you need a file. Update it in the same change that adds or renames code.

The root [`README.md`](../../README.md) is the one-line pitch. This folder is the working set.

## Every doc

| Doc | Read it when |
|---|---|
| [`TEAM_BRIEF.md`](TEAM_BRIEF.md) | You need the current status and your track. |
| [`TEAM_HANDOFF.md`](TEAM_HANDOFF.md) | You are about to write code, or an agent is picking the repo up. |
| [`../9-26-todo.md`](../9-26-todo.md) | You need the open tasks, and nothing else. |
| [`UX.md`](UX.md) | You are adding UI. It decides what the screen is for. Tokens live in the spec's Design Language section. |
| [`../design-addendum.md`](../design-addendum.md) | You need sizes, copy, and states for a screen that UX.md already allows. |
| [`seeding-and-catalog.md`](seeding-and-catalog.md) | You need to know where globe peaks and Rainier trails come from. |
| [`CODE_REFERENCE.md`](CODE_REFERENCE.md) | You need a path, a type, or an endpoint. |
| [`geographic_validation.md`](geographic_validation.md) | You need how well the landslide models hold up on unseen regions, at Rainier, and combined with rain. |
| [`data_gap_analysis.md`](data_gap_analysis.md) | You need what labeled data exists by region and what to collect next. |
| [`../TerraSense.md`](../TerraSense.md) | You need the product, the data model, the API, or the demo script. |
| [`../implementation-steps.md`](../implementation-steps.md) | You need the build notes for a step. |

## Where do I find…

| I need… | Look here |
|---|---|
| What is left today | [`context/9-26-todo.md`](../9-26-todo.md) |
| The demo script | [`context/TerraSense.md`](../TerraSense.md) → Demo Script |
| What not to build | [`context/TerraSense.md`](../TerraSense.md) → Out of Scope |
| The next build step | [`context/9-26-todo.md`](../9-26-todo.md), then the matching section of [`context/implementation-steps.md`](../implementation-steps.md) |
| Colors, type, layout | [`context/TerraSense.md`](../TerraSense.md) → Design Language, and [`UX.md`](UX.md) |
| Rainier bounding box and risk bins | [`context/implementation-steps.md`](../implementation-steps.md) → Shared facts |
| How peaks and trails are seeded | [`seeding-and-catalog.md`](seeding-and-catalog.md) |
| Env vars | [`.env.example`](../../.env.example) at the repo root |
| Frontend app | `frontend/` |
| Agent rules and folder owners | [`AGENTS.md`](../../AGENTS.md) at the repo root, plus one per folder |
| API, model, tiles | The API is in `backend/`, offline scripts in `ml/`. Current and planned paths are in [`CODE_REFERENCE.md`](CODE_REFERENCE.md) |
