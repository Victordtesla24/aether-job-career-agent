"use client";

/**
 * S-UI-REBUILD §1.6 — the command palette, the shell's hero moment.
 *
 * WIRING LAW (non-negotiable, §1.6)
 * ---------------------------------
 * This palette **reuses `loadSearchIndex()` and `filterSearchHits()`
 * unchanged**. They were moved verbatim from `components/topbar.tsx` to
 * `lib/search.ts` and are re-exported from their old path, so
 * `src/__tests__/dashboard/topbar-search.test.ts` still imports them from
 * `components/topbar` and still passes unmodified. Same three API calls
 * (`/jobs?`, `/applications`, `fetchAgents()`), same lazy-on-first-open
 * trigger, same ">= 2 characters" rule, same `limit 8`.
 *
 * The Navigate section is the 13 `NAV_ITEMS` matched on label: client-side
 * routing only, ZERO API. Recents are the last five selections, in
 * `localStorage`, client-only.
 *
 * NOTHING HERE MUTATES. No "Run agent", no "Approve". §1.6 forbids it
 * outright: a mutating command would be new behaviour, and this workstream
 * may not change what the app does.
 */

import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { DURATION, EASE, SPRING } from "../../lib/motion";
import { NAV_ITEMS } from "../../lib/navigation";
import { filterSearchHits, loadSearchIndex, type SearchHit } from "../../lib/search";

const RECENTS_KEY = "aether.palette.recents";
const MAX_RECENTS = 5;

export interface PaletteRow {
  id: string;
  section: string;
  label: string;
  sublabel: string;
  href: string;
}

interface PaletteSection {
  title: string;
  rows: PaletteRow[];
}

function readRecents(): PaletteRow[] {
  try {
    const raw = window.localStorage.getItem(RECENTS_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(
        (entry): entry is PaletteRow =>
          !!entry &&
          typeof entry === "object" &&
          typeof (entry as PaletteRow).href === "string" &&
          typeof (entry as PaletteRow).label === "string",
      )
      .slice(0, MAX_RECENTS)
      .map((entry) => ({ ...entry, id: `recent:${entry.href}:${entry.label}`, section: "Recent" }));
  } catch {
    // Corrupt or blocked storage: no recents, never a fabricated list.
    return [];
  }
}

function writeRecents(rows: PaletteRow[]): void {
  try {
    window.localStorage.setItem(RECENTS_KEY, JSON.stringify(rows.slice(0, MAX_RECENTS)));
  } catch {
    // Preference simply is not persisted.
  }
}

/** Section titles for the three `SearchHit` kinds, in a stable order. */
const HIT_SECTIONS: Array<{ kind: SearchHit["kind"]; title: string }> = [
  { kind: "job", title: "Jobs" },
  { kind: "application", title: "Applications" },
  { kind: "agent", title: "Agents" },
];

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const [recents, setRecents] = useState<PaletteRow[]>([]);
  const [mounted, setMounted] = useState(false);
  // Same lazy-on-first-open contract the top bar's search box had.
  const indexRef = useRef<SearchHit[] | null>(null);
  const [, setIndexReady] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const listRef = useRef<HTMLUListElement | null>(null);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActiveIndex(0);
    setRecents(readRecents());
    if (indexRef.current) return;
    loadSearchIndex()
      .then((hits) => {
        indexRef.current = hits;
        setIndexReady(true);
      })
      .catch(() => undefined);
  }, [open]);

  const sections = useMemo<PaletteSection[]>(() => {
    const trimmed = query.trim().toLowerCase();
    const navigate: PaletteRow[] = NAV_ITEMS.filter(
      (item) => trimmed === "" || item.label.toLowerCase().includes(trimmed),
    ).map((item) => ({
      id: `nav:${item.href}`,
      section: "Navigate",
      label: item.label,
      sublabel: item.href,
      href: item.href,
    }));

    if (trimmed === "") {
      const out: PaletteSection[] = [{ title: "Navigate", rows: navigate }];
      if (recents.length > 0) out.push({ title: "Recent", rows: recents });
      return out;
    }

    const hits = filterSearchHits(indexRef.current ?? [], query);
    const out: PaletteSection[] = [];
    if (navigate.length > 0) out.push({ title: "Navigate", rows: navigate });
    for (const { kind, title } of HIT_SECTIONS) {
      const rows = hits
        .filter((hit) => hit.kind === kind)
        .map<PaletteRow>((hit) => ({
          id: `${hit.kind}:${hit.id}`,
          section: title,
          label: hit.label,
          sublabel: hit.sublabel,
          href: hit.href,
        }));
      if (rows.length > 0) out.push({ title, rows });
    }
    return out;
  }, [query, recents]);

  const flatRows = useMemo(() => sections.flatMap((section) => section.rows), [sections]);

  const select = useCallback(
    (row: PaletteRow) => {
      const next = [
        { ...row, id: `recent:${row.href}:${row.label}`, section: "Recent" },
        ...recents.filter((entry) => !(entry.href === row.href && entry.label === row.label)),
      ].slice(0, MAX_RECENTS);
      writeRecents(next);
      setRecents(next);
      onClose();
      router.push(row.href);
    },
    [onClose, recents, router],
  );

  useEffect(() => {
    if (!open) return undefined;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setActiveIndex((i) => (flatRows.length === 0 ? 0 : (i + 1) % flatRows.length));
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setActiveIndex((i) =>
          flatRows.length === 0 ? 0 : (i - 1 + flatRows.length) % flatRows.length,
        );
        return;
      }
      if (event.key === "Enter") {
        const row = flatRows[activeIndex];
        if (row) {
          event.preventDefault();
          select(row);
        }
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, flatRows, activeIndex, onClose, select]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (activeIndex > 0 && activeIndex >= flatRows.length) setActiveIndex(0);
  }, [activeIndex, flatRows.length]);

  if (!mounted) return null;

  const activeRow = flatRows[activeIndex];

  return createPortal(
    <AnimatePresence>
      {open ? (
        <div data-testid="command-palette-root">
          <motion.div
            aria-hidden="true"
            data-testid="command-palette-scrim"
            onClick={onClose}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: DURATION.base, ease: EASE }}
            className="fixed inset-0 z-[60] bg-black/60 backdrop-blur-sm"
          />
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-label="Command palette — search or jump to"
            data-testid="command-palette"
            initial={{ opacity: 0, scale: 0.97, y: 4 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: 4 }}
            transition={SPRING.snappy}
            className="elev-3 fixed inset-x-4 top-[20vh] z-[61] mx-auto max-w-[560px] overflow-hidden rounded-2xl"
          >
            <div className="flex items-center gap-3 border-b border-hairline px-4 py-3">
              <i
                className="fa-solid fa-magnifying-glass text-[13px] text-aether-muted-dim"
                aria-hidden="true"
              />
              <input
                ref={inputRef}
                type="text"
                role="combobox"
                aria-expanded
                aria-controls="command-palette-list"
                aria-activedescendant={activeRow ? `palette-row-${activeRow.id}` : undefined}
                aria-label="Search jobs, applications, agents"
                placeholder="Search or jump to…"
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setActiveIndex(0);
                }}
                className="min-w-0 flex-1 bg-transparent text-[14px] placeholder:text-aether-muted-dim focus:outline-none"
              />
              <kbd className="type-mono-micro rounded border border-hairline px-1.5 py-0.5 text-aether-muted-dim">
                esc
              </kbd>
            </div>

            <ul
              ref={listRef}
              id="command-palette-list"
              role="listbox"
              aria-label="Results"
              className="max-h-[52vh] overflow-y-auto py-1"
            >
              {flatRows.length === 0 ? (
                <li
                  data-testid="command-palette-empty"
                  className="px-4 py-6 text-center text-[13px] text-aether-muted"
                >
                  No matches for <span className="font-medium text-aether-text">{query.trim()}</span>
                  . Try a company, a role, or an agent name.
                </li>
              ) : (
                sections.map((section) => (
                  <li key={section.title} role="presentation">
                    <p className="type-section px-4 pb-1 pt-3">{section.title}</p>
                    <ul role="group" aria-label={section.title}>
                      {section.rows.map((row) => {
                        const index = flatRows.indexOf(row);
                        const isActive = index === activeIndex;
                        return (
                          <li
                            key={row.id}
                            id={`palette-row-${row.id}`}
                            role="option"
                            aria-selected={isActive}
                            data-testid={`palette-row-${row.href}`}
                          >
                            <button
                              type="button"
                              tabIndex={-1}
                              onMouseEnter={() => setActiveIndex(index)}
                              onMouseDown={(event) => {
                                event.preventDefault();
                                select(row);
                              }}
                              className={`flex w-full items-center gap-3 px-4 py-2 text-left transition-colors duration-[--dur-fast] ${
                                isActive ? "bg-surface-3" : ""
                              }`}
                            >
                              <span className="min-w-0 flex-1 truncate text-[13px]">
                                {row.label}
                              </span>
                              {row.sublabel ? (
                                <span className="type-meta min-w-0 max-w-[45%] truncate">
                                  {row.sublabel}
                                </span>
                              ) : null}
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  </li>
                ))
              )}
            </ul>

            <p className="type-meta flex items-center gap-3 border-t border-hairline px-4 py-2">
              <span>↑↓ move</span>
              <span>↵ open</span>
              <span>esc close</span>
            </p>
          </motion.div>
        </div>
      ) : null}
    </AnimatePresence>,
    document.body,
  );
}

export default CommandPalette;
