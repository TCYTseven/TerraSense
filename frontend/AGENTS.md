<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

# TerraSense frontend guide

Next.js App Router app for TerraSense. Track: frontend. Serves http://localhost:3000.

Read the repo root [`AGENTS.md`](../AGENTS.md) for the team rules and shared facts, and [`../context/docs/UX.md`](../context/docs/UX.md) before you add a screen or a control.

## Steps this folder owns

| Step | Adds |
|---|---|
| 2 | Dark dispatch theme and the full-bleed shell |
| 7 | `lib/types.ts`, `lib/api.ts`, `lib/fixtures/run.json` |
| 8–9 | Globe markers, hover card, search, fly-to, `/mountains/[slug]` |
| 15–16 | Mapbox terrain view, layer toggles |
| 23 | Agent stream and hazard panel |
| 25 | Hiker card, empty, loading, and error states |

## Commands

Run from `frontend/`:

```bash
npm install
npm run dev          # http://localhost:3000
npm run lint
npm run typecheck    # next typegen, then tsc --noEmit
npm run build
```

## Rules

- Screens: the globe is the way in, the mountain page is a ranger dispatch board, the hiker card is the only consumer-style surface.
- Risk colors mark risk only: markers, trails, heat, severity. The cyan accent marks interactive elements only.
- UI text uses the sans face. Scores, miles, coordinates, and timestamps use the mono face.
- All API calls go through `lib/api.ts`. Types in `lib/types.ts` mirror the backend's Pydantic models.
- `next.config.ts` loads the repo root `.env`, so `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_MAPBOX_TOKEN` live there. Restart `next dev` after editing it. Never read a secret such as `DATABASE_URL` in frontend code.
- Validate JSON you did not type yourself, such as fixtures and stream messages, with `lib/agent-events.ts`.
- The bundled lint rules reject a synchronous `setState` inside `useEffect`. Set state in the async callback, and abort fetches in the cleanup.
- WebGL and Mapbox code is client-only. Load it with `next/dynamic` and `ssr: false` from a client component.
- Motion stays short: idle globe spin, a 1.5 s fly-to, the heat map fade. Nothing else animates unless work is happening.
- Walk the demo click path in a browser before you commit a UI change. A screenshot of one screen is not the check.
