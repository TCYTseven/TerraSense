# TerraSense conventions

TerraSense is landslide hazard intelligence for park rangers and hikers. The ranger UI is dark and operational, like a small dispatch screen ("basalt and glacier"). The globe home is the one light surface. Color is information: risk colors mean risk, the glacier cyan means "you can press this", and everything else is text or muted text. These rules come from the product spec's Design Language and the team's design addendum.

## Setup

- Link `styles.css` and load `_ds_bundle.js`. No provider is needed: `styles.css` sets the dark background, the text color, Space Grotesk, and the 2 px focus ring.
- Components live on `window.TerraSense`: `RiskBadge`, `LevelWord`, `NeedsReviewTag`, `TrailBadge`, `OverallRisk`, `TrailList`, `PreventativeMeasures`, `AgentPipeline`, `AgentCard`, `StatusGlyph`, `ReactiveMeasures`, `AnalyzeButton`. Helpers: `RISK_LEVELS`, `riskLabel`, `levelForScore(score)` (bins: low < 0.2, moderate < 0.45, high ≤ 0.7, extreme above), `formatScore`, `PIPELINE_LABELS`, `MEASURE_CATEGORY_LABELS`, `initialPipelineState()`, and `usePipeline(hill)`, which plays a scripted agent run (`{state, running, analyze}`).
- Each component's `.d.ts` spells out its data shapes inline. Read it before passing props.
- Styling is Tailwind v4 utilities, **precompiled**: a class exists only if it is in `_ds_bundle.css`. Tailwind's default palette is removed, so `text-red-500` and `bg-white` do not exist. Use only the tokens below.
- **The globe home** sits in the light scope: put `theme-home-light` on the home screen's root. Every role token swaps to its light value there. Mountain pages stay dark.

## Color: role tokens

| Utility | Role |
|---|---|
| `bg-background` / `bg-muted` | Page / inset fields and skeleton bars |
| `bg-card` `bg-popover` `bg-secondary` | Panel, hover card, popups, search results |
| `text-foreground` / `text-muted-foreground` | Body text / labels, secondary lines, waiting states |
| `bg-primary` `text-primary` `border-primary` `outline-ring` | **The interactive cyan**: primary button, View, focus, selected |
| `text-primary-foreground` | Text on the cyan |
| `border-border` | Every 1 px border (the text color at 10%) |
| `bg-accent` | Hover and selected-row surface (text at 6%). **Not the cyan** |
| `text-destructive` | Error text. It is the text color: errors never borrow risk red |
| `{bg,text,border}-risk-{low,moderate,high,extreme}` | **Risk only** |

- Risk color goes only on markers, trail lines, level words and dots, trail badges, and the High/Extreme treatment. Never on buttons, agent status, or error lines. A risk color always sits beside its level word.
- **High and Extreme treatment:** `border-l-3 border-risk-high bg-risk-high/8` (`extreme` for Extreme), always on top of `bg-card`. `OverallRisk` and `ReactiveMeasures` apply it themselves.

## Surfaces and shape

- Flat. No shadows. No gradients (except the home's backdrop). Sections separate with `border-t border-border` and `px-5 py-4`.
- Radius: controls `rounded-md` (6 px), floating surfaces and measure cards `rounded-lg` (8 px), the panel `rounded-none`.
- **Mountain page:** map left `md:w-[55%]`, one scrolling panel right `md:w-[45%] border-l border-border bg-card`, and `AnalyzeButton` in a footer pinned below the scroll area. Panel order: header, `OverallRisk`, `TrailList`, `PreventativeMeasures`, an "Agents" section with `AgentPipeline`, then `ReactiveMeasures` once a run finishes. No second sidebar and no drawer.

## Type

Space Grotesk (`font-sans`) for UI text. JetBrains Mono (`font-mono`) for **values only**, a number with its unit (`3.2 mi`, `0.74`, `2.4 s`). Write mono inside sentences as `font-mono text-[0.92em]`. Sentence case everywhere.

| Role | Classes |
|---|---|
| Panel title | `text-2xl/7 font-semibold tracking-[-0.01em]` |
| Overall score | `font-mono text-4xl/10 font-semibold tracking-tight` |
| Section title (Reactive Measures) | `text-xl font-semibold tracking-[-0.01em]` |
| Rows, trail names, bullets, agent names | `text-base` |
| Labels, secondary lines, status, traces | `text-sm` (section labels `text-sm text-muted-foreground`) |
| Chips and tags | `text-xs` |

## Numbers and copy

- US units: `14,410 ft`, `3.2 mi`, `1.84 in`, slope `34°`. Scores run 0 to 1 with two decimals and no percent (`0.74`). Times read `12 min ago` or `14:05`.
- Level words: Low, Moderate, High, Extreme. The agents are Terrain, Weather, Trails, Synthesizer, and Mass Alert Writer, under one Orchestrator.
- Reactive Measures group in this order: closures and access, evacuation and sweeps, search and rescue readiness, field monitoring, agency coordination, public notice. Each has a deadline ("Now", "Within 1 h"). **Every public notice is a draft, "Draft, not sent"; nothing is ever sent, and no public notice gets a send button.**
- Plain verbs, no apologies. The action is **Analyze now** (then "Analyzing…").

## Motion

No `transition-*`. The only animation class is `animate-work` (the running agent card, skeleton bars), with `motion-reduce:animate-none`.

## Where the truth lives

`_ds_bundle.css` holds the compiled utilities and the `:root` and `.theme-home-light` role variables at the top. Each `components/<group>/<Name>/<Name>.prompt.md` has worked examples, and `<Name>.d.ts` has the props.

## Example

```jsx
const { OverallRisk, TrailList, AgentPipeline, ReactiveMeasures, AnalyzeButton, usePipeline } = window.TerraSense;

function RangerPanel({ hill }) {
  const pipeline = usePipeline(hill);
  const [selected, setSelected] = React.useState(null);
  return (
    <aside className="flex h-dvh flex-col border-l border-border bg-card md:w-[45%]">
      <div className="flex-1 overflow-y-auto">
        <header className="px-5 pb-4 pt-5">
          <h1 className="text-2xl/7 font-semibold tracking-[-0.01em]">{hill.name}</h1>
          <p className="mt-1.5 text-base text-muted-foreground">
            <span className="font-mono text-[0.92em] text-foreground">14,410 ft</span> {hill.region}
          </p>
        </header>
        <OverallRisk hill={hill} />
        <TrailList trails={hill.trails} selected={selected} onView={setSelected} />
        <section className="border-t border-border px-5 py-4">
          <h2 className="text-sm text-muted-foreground">Agents</h2>
          <div className="mt-2"><AgentPipeline state={pipeline.state} /></div>
        </section>
        {pipeline.state.measures && (
          <ReactiveMeasures measures={pipeline.state.measures} level={hill.risk.level} trails={hill.trails} />
        )}
      </div>
      <footer className="border-t border-border px-5 py-4">
        <AnalyzeButton running={pipeline.running} onAnalyze={pipeline.analyze} />
      </footer>
    </aside>
  );
}
```
