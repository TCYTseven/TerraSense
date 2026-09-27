import type { KeyboardEvent } from "react";

export type PanelTab = "prevention" | "response";

export const PANEL_TABS: { id: PanelTab; label: string }[] = [
  { id: "prevention", label: "Prevention" },
  { id: "response", label: "Response" },
];

export function tabId(tab: PanelTab) {
  return `panel-tab-${tab}`;
}

export function tabPanelId(tab: PanelTab) {
  return `panel-tabpanel-${tab}`;
}

/** The side panel's two sections, under the header and overall risk. Arrow keys move between them, as in any tab list. */
export default function PanelTabs({
  active,
  onChange,
  tabs = PANEL_TABS,
}: {
  active: PanelTab;
  onChange: (tab: PanelTab) => void;
  /** Response first when there is nothing to prevent (no mapped trails). */
  tabs?: readonly { id: PanelTab; label: string }[];
}) {
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const index = tabs.findIndex((tab) => tab.id === active);
    const next = tabs[(index + step + tabs.length) % tabs.length].id;
    onChange(next);
    document.getElementById(tabId(next))?.focus();
  }

  return (
    <div role="tablist" aria-label="Panel sections" onKeyDown={onKeyDown} className="flex shrink-0 border-y border-border px-5">
      {tabs.map((tab) => {
        const selected = tab.id === active;
        return (
          <button
            key={tab.id}
            id={tabId(tab.id)}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-controls={tabPanelId(tab.id)}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(tab.id)}
            className={`-mb-px h-11 border-b-2 px-3 text-sm font-medium first:-ml-3 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring ${
              selected ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
