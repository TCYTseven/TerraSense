# TerraSense conventions

TerraSense is landslide hazard intelligence for Mount Rainier, built for park rangers and hikers. The UI is dark and operational, like a small dispatch screen. The globe and the heat map are the two loud moments, and everything else stays quiet. These rules come from the product spec's Design Language and the team's design addendum.

## Setup

- Link `styles.css` and load `_ds_bundle.js`. No provider is needed: `styles.css` sets the dark background, the text color, Space Grotesk, and the 2 px focus ring on its own.
- The bundle exports `RiskBadge`, `RISK_LEVELS` (`["low","moderate","high","extreme"]`), `riskLabel(level)` (`"high"` → `"High"`), and `RISK_COLORS` (hex values for canvas or SVG code only).
- Styling is Tailwind v4 utilities, **precompiled**: a class exists only if it is in `_ds_bundle.css`. Tailwind's default palette is removed. `text-red-500` and `bg-white` do not exist. Use only the tokens below.

## Color: role tokens (shadcn names)

| Utility | Role |
|---|---|
| `bg-background` | Page (the dark end) |
| `bg-muted` | Inset fields, skeleton bars (the light end) |
| `bg-card` `bg-popover` `bg-secondary` | Side panel, toggle group, hover card, popups, search results |
| `text-foreground` / `text-muted-foreground` | Body text / labels, secondary lines, waiting states |
| `bg-primary` `text-primary` `border-primary` `outline-ring` | **The interactive cyan**: primary button, focus, selected, toggles when on |
| `text-primary-foreground` | Text on the cyan |
| `border-border` `border-input` | Every 1 px border (white at 10%) |
| `bg-accent` | Hover surface for list rows (white at 6%). **Not the cyan** |
| `text-destructive` | Error text. It is the text color, because errors never borrow risk red |
| `{bg,text,border}-risk-{low,moderate,high,extreme}` | **Risk only** |

- Color is information. Risk colors mean risk. Cyan means "you can press this." Everything else is text or muted text.
- Risk color goes only on markers, trail lines, hazard polygons and pins, level words, and the High and Extreme treatment. Never on buttons, agent status, success lines, or error lines.
- A risk color always sits beside its level word (`RiskBadge` does this). No level means no color: show muted "Not analyzed yet."
- **High and Extreme treatment:** `border-l-3 border-risk-high bg-risk-high/8` (the `extreme` equivalents for Extreme). Low and Moderate get neither.

## Surfaces and shape

- Flat. **No shadows. No gradients. No cards inside the panel.** Surfaces separate with a 1 px `border-border`. A heavier stroke always means selection, severity, or status.
- Radius: controls `rounded-md` (6 px), surfaces floating over the map or globe `rounded-lg` (8 px), side panel `rounded-none`, flush to the viewport edge.
- Panel: `w-[clamp(360px,30vw,440px)] border-l border-border bg-card`, with `px-5` side padding. Sections are divided by `border-t border-border` with `py-4`.

## Type

Space Grotesk (`font-sans`) for UI text. JetBrains Mono (`font-mono`) for **values only**: a number with its unit (`3.2 mi`, `0.82`, `12 min`). Write mono values as `font-mono text-[0.92em]`. Sentence case everywhere: no all-caps labels and no letter-spaced eyebrows.

| Role | Classes |
|---|---|
| Wordmark | `text-base/5 font-semibold tracking-[-0.01em]` |
| Panel title | `text-2xl/7 font-semibold tracking-[-0.01em]` |
| Lead (risk sentence) | `text-base` |
| Body (rows, values) | `text-sm` |
| Meta (labels, hover card, status lines) | `text-xs` |
| Button | `text-sm font-medium` |
| Hiker level / sentence / bypass name | `text-4xl font-semibold tracking-[-0.02em]` / `text-[21px]/[30px]` / `text-lg/6 font-semibold` |

## Numbers and copy

- US units: `3.2 mi`, `mi 4.2–5.1` in rows, "mile 4.2 to 5.1" in sentences, `+1.2 mi`, `+350 ft`, `14,410 ft`, `1.84 in`. Probability, confidence, and score run 0 to 1 with two decimals and no percent (`0.82`). Times read `12 min ago` or `14:05` (24-hour).
- Level words are Low, Moderate, High, and Extreme. They appear in all caps only in ranger copy: "Debris flow risk HIGH. East fork drainage, Ridge Trail mile 4.2 to 5.1. Confidence 0.82."
- Plain verbs, no apologies. The actions are **Analyze now** (then "Analyzing…") and **Hiker forecast**.
- Status and error lines: `text-xs border-l-2 border-foreground/40 pl-2`, never a risk color.

## Motion and interaction

- No `transition-*`. Hover, focus, open, and close change instantly. The only animation class is `animate-work`, used for running agent rows (`bg-foreground/4`) and skeleton bars.
- Primary button: `h-10 w-full rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-40`.
- Secondary button: `h-10 w-full rounded-md border border-primary text-primary text-sm font-medium hover:bg-primary/10`.

## Where the truth lives

`_ds_bundle.css` holds the compiled utilities, with the `:root` role variables at the top. `components/general/RiskBadge/RiskBadge.prompt.md` has the component examples.

## Example

```jsx
const { RiskBadge } = window.TerraSense;

<aside className="w-[clamp(360px,30vw,440px)] border-l border-border bg-card">
  <section className="border-l-3 border-risk-high bg-risk-high/8 px-5 py-4">
    <RiskBadge level="high" className="text-base font-semibold text-risk-high" />
    <p className="mt-1 text-base">
      Debris flow risk HIGH. East fork drainage, Ridge Trail mile 4.2 to 5.1. Confidence{" "}
      <span className="font-mono text-[0.92em]">0.82</span>.
    </p>
  </section>
  <footer className="border-t border-border px-5 py-4">
    <button className="h-10 w-full rounded-md bg-primary text-sm font-medium text-primary-foreground hover:bg-primary/90">
      Analyze now
    </button>
    <button className="mt-2 h-10 w-full rounded-md border border-primary text-sm font-medium text-primary hover:bg-primary/10">
      Hiker forecast
    </button>
  </footer>
</aside>
```
