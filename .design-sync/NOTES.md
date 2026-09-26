# design-sync notes (TerraSense → Claude Design)

Project: https://claude.ai/design/p/9607f63c-dacc-478a-8997-39b63859a0b3

## Sources of truth (user direction, 2026-09-25)

- **`context/design-addendum.md` is the source of truth for the design system.** It covers token names and roles, radius, type, units, risk mapping, surfaces, motion, and copy.
- **Hex values come from `context/TerraSense.md` → Design Language.** The addendum's own precedence rule says the spec wins on color and that hex values live only there.
- `UX.md` lives at `context/docs/UX.md` (the addendum links it as a sibling, which is wrong). The design system has not been checked against it yet.
- The addendum's **[confirm]** defaults are treated as decided: Space Grotesk and JetBrains Mono, US units, and the High/Extreme treatment. If the team changes one, update `tokens.css`, `build-pkg.mjs` (fonts and safelist), `conventions.md`, and `previews/RiskBadge.tsx`.
- **The frontend code is not the token source.** `frontend/app/globals.css` and `lib/theme.ts` predate the addendum (see Drift). `build-pkg.mjs` compiles `.design-sync/tokens.css` instead, and only `RiskBadge`'s JS comes from the app.

## Drift: the app vs the addendum (for the frontend track, not fixed by this sync)

- `globals.css` names the cyan `--color-accent`. The addendum puts it on `--primary`/`--ring`, with `--accent` = white 6% (Tokens rule 1). The app also uses `panel`/`line`/`surface`/`muted` (as text) instead of the shadcn role names.
- The app uses Geist and Geist Mono. The addendum specifies Space Grotesk and JetBrains Mono, with mono at 0.92em.
- The app has `--animate-fade-in` and a `bg-grid` gradient utility. The addendum allows only `animate-work` and no gradients except the globe backdrop.
- The globe hover card (`mountain-marker.tsx`) has `shadow-xl`, `backdrop-blur`, and meters (`4,392 m`). The addendum calls for no shadows, feet, and "Updated 12 min ago".
- `RiskBadge` renders "High risk". The addendum's level words are "High" etc., and the Overall risk word should use the level color at lead size, 600 (the previews pass `className`).
- Risk hexes live in `frontend/lib/theme.ts`. Addendum rule 4 names `frontend/lib/risk.ts`.
- The search results show region and a badge per row. The addendum shows up to three matching names.

## How this repo syncs

- `frontend/` is a Next.js app with no `dist/`. `.design-sync/build-pkg.mjs` (`cfg.buildCmd`) builds a stand-in package `terrasense-ui` into `.design-sync/.cache/pkg/`:
  - `dist/index.js`: esbuild bundle of `.design-sync/entry.ts` (`RiskBadge`, `RISK_LEVELS`, `riskLabel`, `RISK_COLORS`), with the `@/` alias pointed at `frontend/`. `THEME` is left out because its `accent` key is the cyan.
  - `dist/types/`: tsc declarations. The `@/` specifiers are rewritten to relative paths, and the entry moves to `index.d.ts`.
  - `dist/styles.css`: `.design-sync/tokens.css` compiled with `@tailwindcss/postcss`. The `@source` inputs are `risk-badge.tsx`, `previews/`, `conventions.md` (so every class the header names compiles), and an inline safelist. Tailwind's default palette is removed (`--color-*: initial`).
  - `node_modules`: symlinked to `frontend/node_modules` so the converter finds `@types/react`.
- Other globe components are NOT scanned. They use pre-addendum names (`text-muted` as text), which would compile to the wrong colors under these tokens.
- Run order: `npm ci` in `frontend/`, then `node .design-sync/build-pkg.mjs`, then the converter or driver with `--node-modules frontend/node_modules`.
- **Run build-pkg before every converter run whenever previews or conventions add classes.** `lib/preview-rebuild.mjs` does NOT recopy the CSS, so new utilities need a full `package-build.mjs` or driver run.
- Scope (user choice): tokens plus `RiskBadge` only. The globe components are left out because they need WebGL/three.js, the router, and the API.
- Fonts load from Google Fonts: Space Grotesk 400/500/600, JetBrains Mono 400/500 (`[FONT_REMOTE]`, expected).
- Render check: there's no Playwright Chromium on this machine. Use the installed Chrome: `DS_CHROMIUM_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"`, with `playwright` installed in `.ds-sync/` using `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`.
- `RiskBadge` uses `cardMode: column`, because the panel-width stories are wider than a grid cell.

## Known render warns

- None.

## Re-sync risks

- If the addendum or the spec's Design Language changes, `tokens.css`, the safelist, `conventions.md`, and the previews all need a manual update. Nothing reads those files automatically.
- `RISK_COLORS` in the bundle comes from `frontend/lib/theme.ts`. If the app's hexes drift from Design Language, the bundle's JS values drift with them while the CSS stays on-spec.
- The safelist in `build-pkg.mjs` is hand-picked from the addendum's sizes and tints. Extend it when designs need more.
- Toolchain assumptions: Node 22, Tailwind v4, and Google Fonts reachable at runtime.
