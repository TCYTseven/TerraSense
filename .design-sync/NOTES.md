# design-sync notes (TerraSense → Claude Design)

Project: https://claude.ai/design/p/9607f63c-dacc-478a-8997-39b63859a0b3

## Sources of truth (user direction, 2026-09-25)

- **`context/design-addendum.md` is the source of truth for the design system.** It covers token names and roles, radius, type, units, risk mapping, surfaces, motion, copy, and, since the hill card rebuild, the panel's components (Panel → Sections, Trail markers, Agent pipeline, Reactive Measures).
- **Hex values come from `context/TerraSense.md` → Design Language** ("basalt and glacier": background `#0D0C0A`–`#13120F`, panels `#1A1814`, accent `#7FDDE6`, text `#ECE6DC`, muted `#9C9387`). The addendum's own precedence rule says the spec wins on color.
- **The light globe home (`.theme-home-light`)** isn't in Design Language. Its values come from `frontend/app/globals.css` and `HOME_THEME` in `frontend/lib/theme.ts`. If the spec adds light values, move the source to the spec.
- `UX.md` lives at `context/docs/UX.md`. It decides which controls ship (the mountain page is a map and one panel, with no drawers or second sidebar).
- The addendum's **[confirm]** defaults are treated as decided: Space Grotesk and JetBrains Mono, US units, and the High/Extreme treatment. If the team changes one, update `tokens.css`, `build-pkg.mjs` (fonts and safelist), `conventions.md`, and the previews.

## Re-sync of 2026-09-25 (evening): what changed and why

- **The palette was stale.** The spec switched from the old blue-gray palette (`#0A0E14`, `#22D3EE`, …) to basalt and glacier in commit 30a5ee1, the same commit that saved the first sync's files. `tokens.css` now carries the current values, which match `globals.css` `:root`.
- **Scope grew from `RiskBadge` to 12 components.** The hill card rebuild (PRs #5 and #7) put the ranger UI in `frontend/components/hill/` and `components/pipeline/`, using the addendum's role names, so it compiles correctly under these tokens. `entry.ts` exports them plus the data helpers and `usePipeline`.
- **Left out on purpose:** `HillHeader` (`next/link` needs the Next router), the map and globe (MapLibre, three.js), `HikerCard` and `HazardBlock` (not rendered on the page), and `THEME` (WebGL values).

## Re-sync of 2026-09-26: Reactive Measures cluster by timing

- The user decided that measures group by **when** they must happen, not by kind of work. `ReactiveMeasure.when` (free text) became `timing` (`now`, `within-1h`, `within-6h`, `within-24h`), and the category is now a card label. Updated: the `ReactiveMeasures` preview data, the `ReactiveMeasures` and `AgentPipeline` bodies in `dtsPropsFor`, the `entry.ts` exports (`MEASURE_TIMINGS`, `MEASURE_TIMING_LABELS`, `MeasureTiming`), and `conventions.md`.

## Drift: the app vs the addendum (for the frontend track, not fixed by this sync)

- The app loads Geist and Geist Mono (`frontend/app/layout.tsx`). The addendum specifies Space Grotesk and JetBrains Mono, so designs built here use the addendum's faces.
- `.theme-home-light` in `globals.css` sets `--card-foreground`, `--ring`, and the other derived roles only through `:root`'s `var(--foreground)` aliases, which resolve at `:root`. Inside the light scope they keep the dark values (for example, `text-card-foreground` would be light text on white). `tokens.css` sets every role explicitly; the app should too.
- The globe hover card (`mountain-marker.tsx`) has `shadow-xl` and `backdrop-blur`, and `RiskBadge` renders "High risk" rather than the bare level word. The addendum calls for no shadows, and inside the panel the app uses `LevelWord`.
- Risk hexes live in `frontend/lib/theme.ts`. Addendum Tokens rule 4 names `frontend/lib/risk.ts`.

## How this repo syncs

- `frontend/` is a Next.js app with no `dist/`. `.design-sync/build-pkg.mjs` (`cfg.buildCmd`) builds a stand-in package `terrasense-ui` into `.design-sync/.cache/pkg/`:
  - `dist/index.js`: an esbuild bundle of `.design-sync/entry.ts`, with the `@/` alias pointed at `frontend/`.
  - `dist/types/`: tsc declarations, with `@/` specifiers rewritten to relative paths.
  - `dist/styles.css`: `.design-sync/tokens.css` compiled with `@tailwindcss/postcss`. The `@source` inputs are the exported components' own files (`risk-badge.tsx`, `icons.tsx`, `panel/level.tsx`, `hill/`, `pipeline/`), `previews/`, `conventions.md`, and an inline safelist. Tailwind's default palette is removed (`--color-*: initial`).
  - `node_modules`: symlinked to `frontend/node_modules`.
- Run order: `npm ci` in `frontend/`, then `node .design-sync/build-pkg.mjs`, then the driver with `--node-modules frontend/node_modules` and `DS_CHROMIUM_PATH` set (see Render check below).
- **Run build-pkg before the driver whenever previews, conventions, or components add classes.** `lib/preview-rebuild.mjs` does not recopy the CSS.
- **Groups come from the source folder** (`hill`, `pipeline`). A doc's `category` applies only when the folder is generic, so `docsMap` points `RiskBadge`, `LevelWord`, and `NeedsReviewTag` at `.design-sync/docs/risk.md` (`category: Risk`). `TrailBadge` stays in `hill`, its folder.
- **`dtsPropsFor` holds hand-written props** for `OverallRisk`, `TrailList`, `AgentCard`, `AgentPipeline`, `ReactiveMeasures`, and `NeedsReviewTag`. The extractor left the `lib/hill.ts` type names (`TrailRisk`, `PipelineAgentState`, …) undefined in the standalone `.d.ts`, dropped `| null` from `TrailList.selected`, and gave `NeedsReviewTag` an open index signature. **If `lib/hill.ts` changes, update these bodies by hand.**
- **A `viewport` override needs a full build.** `preview-rebuild.mjs` rejects it with `[CONFIG_STALE]`, so run build-pkg and then the driver. `ReactiveMeasures` uses `900x1500` so the full High response fits in the card.
- Card modes: every panel-width component is `cardMode: column`.
- Render check: Playwright's Chromium isn't installed on this machine. Use the installed Chrome via `DS_CHROMIUM_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"`, with `playwright` installed in `.ds-sync/`.
- Fonts load from Google Fonts: Space Grotesk 400/500/600 and JetBrains Mono 400/500 (`[FONT_REMOTE]`, expected).
- **Previews sit on `bg-card`.** The High/Extreme treatment's 8% tint reads pink on the white card page unless a `bg-card` wrapper is underneath.

## Known render warns

- The running `AgentCard` and `AgentPipeline` cells capture dim: `animate-work` is mid-pulse. That's expected.

## Re-sync risks

- If the addendum or the spec's Design Language changes, `tokens.css`, the safelist, `conventions.md`, and the previews all need a manual update. Nothing reads those files automatically.
- `.theme-home-light` is copied from `globals.css`. If the home theme changes there, update `tokens.css`.
- `RISK_COLORS` in the bundle comes from `frontend/lib/theme.ts`. If the app's hexes drift from Design Language, the bundle's JS values drift while the CSS stays on-spec.
- The hand-written `dtsPropsFor` bodies mirror `frontend/lib/hill.ts` (TrailRisk, HillView, PipelineState, ReactiveMeasure with its `timing` clusters). The measure shape appears twice, in `ReactiveMeasures` and in `AgentPipeline`; change both. Step 31 (wiring the card to the backend) or seven agent cards will change those shapes.
- The card shows five agents; the backend runs seven. When step 31 adds History and Route Scout cards, re-author the `AgentPipeline` and `AgentCard` previews.
- Toolchain assumptions: Node 22, Tailwind v4, and Google Fonts reachable at runtime.
