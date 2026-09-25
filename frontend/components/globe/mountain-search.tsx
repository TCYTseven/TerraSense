"use client";

import { type KeyboardEvent, useId, useMemo, useState } from "react";
import RiskBadge from "@/components/risk-badge";
import type { Mountain } from "@/lib/types";

/** Lowercase, accents stripped, and "mt" or "mt." expanded, so "mt rainier" and "huascaran" match. */
function normalize(text: string): string {
  return text
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase()
    .trim()
    .replace(/^mt\.?\s+/, "mount ");
}

/** Mountains whose name matches the query. Name starts first, then word starts, then substrings. */
export function matchMountains(mountains: Mountain[], query: string): Mountain[] {
  const needle = normalize(query);
  if (!needle) {
    return mountains;
  }
  return mountains
    .map((mountain) => {
      const name = normalize(mountain.name);
      const rank = name.startsWith(needle)
        ? 0
        : name.split(/\s+/).some((word) => word.startsWith(needle))
          ? 1
          : name.includes(needle)
            ? 2
            : -1;
      return { mountain, rank };
    })
    .filter(({ rank }) => rank >= 0)
    .sort((a, b) => a.rank - b.rank)
    .map(({ mountain }) => mountain);
}

function SearchIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden className={className}>
      <circle cx="8.5" cy="8.5" r="5.5" />
      <path d="m13 13 4 4" strokeLinecap="round" />
    </svg>
  );
}

/**
 * Search box that matches mountain names. Enter, a click, or a tap on a match calls onSelect.
 */
export default function MountainSearch({
  mountains,
  emptyMessage,
  disabled,
  onSelect,
}: {
  mountains: Mountain[];
  /** Shown in the dropdown while there are no mountains to search. */
  emptyMessage: string;
  disabled: boolean;
  onSelect: (mountain: Mountain) => void;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const inputId = useId();
  const listId = useId();

  const matches = useMemo(() => matchMountains(mountains, query), [mountains, query]);
  const activeIndex = Math.min(active, matches.length - 1);
  const showList = open && !disabled;

  function choose(mountain: Mountain) {
    setQuery(mountain.name);
    setOpen(false);
    onSelect(mountain);
  }

  function move(step: number) {
    setOpen(true);
    if (matches.length) {
      setActive((activeIndex + step + matches.length) % matches.length);
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      move(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      move(-1);
    } else if (event.key === "Enter") {
      event.preventDefault();
      const pick = matches[activeIndex] ?? matches[0];
      if (pick) {
        choose(pick);
      } else {
        setOpen(true);
      }
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div role="search">
      <label htmlFor={inputId} className="sr-only">
        Search a mountain
      </label>
      <div className="relative">
        {/* z-10: the input's backdrop blur would otherwise paint over the icon. */}
        <SearchIcon className="pointer-events-none absolute left-3.5 top-1/2 z-10 size-4 -translate-y-1/2 text-muted" />
        <input
          id={inputId}
          type="text"
          role="combobox"
          aria-expanded={showList}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={
            showList && matches[activeIndex] ? `${listId}-${matches[activeIndex].slug}` : undefined
          }
          autoComplete="off"
          spellCheck={false}
          placeholder="Search a mountain"
          value={query}
          disabled={disabled}
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(0);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={handleKeyDown}
          className="h-11 w-full rounded-lg border border-line bg-panel/85 pl-10 pr-4 text-sm text-foreground shadow-lg shadow-black/30 backdrop-blur-sm placeholder:text-muted disabled:opacity-60"
        />
      </div>
      {showList && (
        <div className="mt-2 overflow-hidden rounded-lg border border-line bg-panel/95 shadow-xl shadow-black/40 backdrop-blur-sm">
          {matches.length > 0 ? (
            <ul id={listId} role="listbox" aria-label="Mountains" className="py-1">
              {matches.map((mountain, index) => (
                <li
                  key={mountain.slug}
                  id={`${listId}-${mountain.slug}`}
                  role="option"
                  aria-selected={index === activeIndex}
                  onMouseDown={(event) => event.preventDefault()}
                  onMouseEnter={() => setActive(index)}
                  onClick={() => choose(mountain)}
                  className={`flex cursor-pointer items-center justify-between gap-4 px-4 py-2.5 ${
                    index === activeIndex ? "bg-white/[0.06]" : ""
                  }`}
                >
                  <span className="min-w-0">
                    <span className="block truncate text-sm text-foreground">{mountain.name}</span>
                    <span className="block truncate text-xs text-muted">{mountain.region}</span>
                  </span>
                  <RiskBadge level={mountain.current_risk_level} className="shrink-0 text-xs text-muted" />
                </li>
              ))}
            </ul>
          ) : (
            <p className="px-4 py-3 text-sm text-muted">
              {mountains.length ? `No mountain matches "${query.trim()}".` : emptyMessage}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
