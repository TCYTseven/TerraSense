import type { Metadata } from "next";
import Link from "next/link";
import BrandLogo from "@/components/brand-logo";
import HistoryRow from "@/components/history/history-row";
import { getHistory } from "@/lib/api";
import type { HistoryPage } from "@/lib/types";

export const metadata: Metadata = {
  title: "Analysis run history",
  description: "Past TerraSense agent runs, model outputs, and advisories.",
};

// Every visit shows what the database holds right now, not a build-time snapshot.
export const dynamic = "force-dynamic";

const PAGE_SIZE = 50;

/** The tag filters across the top. An empty value means no filter. */
const CLASS_FILTERS = [
  { value: "", label: "All hazards" },
  { value: "landslide", label: "Landslide" },
  { value: "debris_flow", label: "Debris flow" },
  { value: "avalanche", label: "Avalanche" },
  { value: "unknown", label: "Untagged" },
];

const STATUS_FILTERS = [
  { value: "", label: "All runs" },
  { value: "done", label: "Finished" },
  { value: "error", label: "Failed" },
];

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-card px-4 py-3">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1 font-mono text-2xl">{value}</p>
    </div>
  );
}

function FilterLinks({
  param,
  current,
  options,
  query,
}: {
  param: string;
  current: string;
  options: Array<{ value: string; label: string }>;
  query: Record<string, string>;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((option) => {
        // Keep the other filters, drop the page offset: a new filter starts at the top.
        const next = new URLSearchParams({ ...query, [param]: option.value });
        next.delete("offset");
        if (!option.value) {
          next.delete(param);
        }
        const active = current === option.value;
        return (
          <Link
            key={option.value || "all"}
            href={`/history${next.toString() ? `?${next}` : ""}`}
            className={`rounded-full border px-3 py-1 text-sm ${
              active
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border text-muted-foreground hover:bg-muted/40"
            }`}
          >
            {option.label}
          </Link>
        );
      })}
    </div>
  );
}

export default async function HistoryRoute({ searchParams }: PageProps<"/history">) {
  const params = await searchParams;
  const read = (key: string) => {
    const value = params[key];
    return (Array.isArray(value) ? value[0] : value) ?? "";
  };
  const hazardClass = read("hazard_class");
  const status = read("status");
  const slug = read("slug");
  const offset = Number.parseInt(read("offset"), 10) || 0;

  // A database that is down must not blank the page: the empty state says so.
  let page: HistoryPage | null = null;
  let error: string | null = null;
  try {
    page = await getHistory({ limit: PAGE_SIZE, offset, hazardClass, status, slug });
  } catch (caught) {
    error = caught instanceof Error ? caught.message : "The history service did not answer.";
  }

  const query: Record<string, string> = {};
  if (hazardClass) query.hazard_class = hazardClass;
  if (status) query.status = status;
  if (slug) query.slug = slug;

  const stats = page?.stats;
  const total = page?.total ?? 0;
  const shown = page?.runs.length ?? 0;

  return (
    <main className="mx-auto w-full max-w-6xl px-6 py-10">
      <header className="flex items-center gap-3">
        <Link href="/" aria-label="TerraSense home">
          <BrandLogo size={40} className="shrink-0" />
        </Link>
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Run history</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Every analysis run TerraSense has made, with what the agents said and what the model
            scored.
          </p>
        </div>
      </header>

      {stats ? (
        <section className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Runs logged" value={stats.runs} />
          <Stat label="Finished" value={stats.done} />
          <Stat label="Failed" value={stats.failed} />
          <Stat label="Mountains" value={stats.mountains} />
        </section>
      ) : null}

      <section className="mt-6 space-y-3">
        <FilterLinks param="hazard_class" current={hazardClass} options={CLASS_FILTERS} query={query} />
        <FilterLinks param="status" current={status} options={STATUS_FILTERS} query={query} />
        {slug ? (
          <p className="text-sm text-muted-foreground">
            Filtered to <span className="font-mono">{slug}</span>{" "}
            <Link className="underline underline-offset-4" href="/history">
              clear
            </Link>
          </p>
        ) : null}
      </section>

      {error ? (
        <p className="mt-8 rounded-xl border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </p>
      ) : null}

      {page && shown === 0 && !error ? (
        <p className="mt-8 rounded-xl border border-border bg-card px-4 py-6 text-sm text-muted-foreground">
          No runs logged yet. Open a mountain and start an analysis, and it will show up here when
          it finishes.
        </p>
      ) : null}

      {page && shown > 0 ? (
        <>
          <ul className="mt-6 space-y-2">
            {page.runs.map((record) => (
              <HistoryRow key={record.run_id} record={record} />
            ))}
          </ul>

          <nav className="mt-6 flex items-center justify-between text-sm">
            <span className="text-muted-foreground">
              {offset + 1}–{offset + shown} of {total}
            </span>
            <span className="flex gap-2">
              {offset > 0 ? (
                <Link
                  className="rounded-full border border-border px-3 py-1 hover:bg-muted/40"
                  href={`/history?${new URLSearchParams({ ...query, offset: String(Math.max(0, offset - PAGE_SIZE)) })}`}
                >
                  Newer
                </Link>
              ) : null}
              {offset + shown < total ? (
                <Link
                  className="rounded-full border border-border px-3 py-1 hover:bg-muted/40"
                  href={`/history?${new URLSearchParams({ ...query, offset: String(offset + PAGE_SIZE) })}`}
                >
                  Older
                </Link>
              ) : null}
            </span>
          </nav>
        </>
      ) : null}
    </main>
  );
}
