"use client";

/**
 * Story Bank — the full-read sheet (§5.8 / X-2).
 *
 * WHY. Measured on production 2026-08-14 (b3/before/before-notes.json): with
 * 20 stories the Story Bank document was **9,071 px** tall at 1600 and
 * **18,216 px** at 390, because every card printed all four STAR fields in
 * full. The list is now uniform cards with a 3-line clamp, and the FULL story
 * opens here — an `elev-3` overlay — rather than expanding inside the list
 * (the X-2 rule: never expand a cell in place and push everything below it).
 *
 * No data of its own: it renders the same `Story` the card already has in
 * hand. No fetch, no mutation.
 *
 * A11y mirrors `MobileNavSheet`: `role="dialog"` + `aria-modal`, focus moves
 * in on open and wraps, `Escape` closes, focus returns to the trigger.
 */
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef } from "react";

import { DURATION, EASE, SPRING } from "../../lib/motion";
import type { Story } from "../../lib/api/stories";

const FOCUSABLE =
  'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])';

export function StorySheet({
  story,
  onClose,
}: {
  story: Story | null;
  onClose: () => void;
}) {
  const panelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!story) return undefined;
    const panel = panelRef.current;
    panel?.querySelector<HTMLElement>(FOCUSABLE)?.focus();

    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (event.key !== "Tab" || !panelRef.current) return;
      const nodes = Array.from(panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (n) => n.offsetParent !== null,
      );
      if (nodes.length === 0) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [story, onClose]);

  const metrics = Object.entries(story?.metrics ?? {});

  return (
    <AnimatePresence>
      {story ? (
        <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto p-4 sm:p-8">
          <motion.div
            className="fixed inset-0 bg-black/60"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: DURATION.base, ease: EASE }}
            onClick={onClose}
            aria-hidden="true"
          />
          <motion.div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-label={story.title}
            data-testid="story-sheet"
            className="elev-3 relative z-10 my-4 w-full max-w-[720px] rounded-2xl p-6"
            initial={{ opacity: 0, scale: 0.97, y: 6 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.98, y: 4 }}
            transition={SPRING.snappy}
          >
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <p className="type-section">{story.category ?? "Story"}</p>
                <h2 className="mt-1 text-[19px] font-semibold leading-[1.25] tracking-[-0.015em]">
                  {story.title}
                </h2>
              </div>
              <button
                type="button"
                onClick={onClose}
                data-testid="story-sheet-close"
                aria-label="Close story"
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-aether-muted transition-colors duration-[--dur-fast] hover:bg-white/[0.06] hover:text-aether-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-aether-coral/50"
              >
                <i className="fa-solid fa-xmark" aria-hidden="true" />
              </button>
            </div>

            <dl className="mt-5 space-y-4">
              {(
                [
                  ["Situation", story.situation],
                  ["Task", story.task],
                  ["Action", story.action],
                  ["Result", story.result],
                ] as const
              ).map(([label, value]) => (
                <div key={label} className="min-w-0">
                  <dt className="type-section">{label}</dt>
                  <dd className="mt-1 min-w-0 break-words text-[13.5px] leading-[1.65] text-aether-muted">
                    {value || <span className="text-state-neutral">not recorded</span>}
                  </dd>
                </div>
              ))}
            </dl>

            <div className="mt-5 border-t border-hairline pt-4">
              <p className="type-section">Evidenced metrics</p>
              {metrics.length > 0 ? (
                <ul className="mt-2 grid gap-1.5 sm:grid-cols-2">
                  {metrics.map(([key, value]) => (
                    <li
                      key={key}
                      className="flex items-baseline justify-between gap-3 rounded-lg border border-hairline px-2.5 py-1.5 text-[12px]"
                    >
                      <span className="min-w-0 truncate text-aether-muted">{key}</span>
                      <span className="mono shrink-0 font-semibold text-state-ok">
                        {String(value)}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-1.5 text-[12px] text-state-neutral">
                  No metrics recorded on this story yet — add one so it can carry a number into an
                  interview answer.
                </p>
              )}
            </div>

            {story.tags.length > 0 ? (
              <div className="mt-4 flex flex-wrap gap-1.5">
                {story.tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded-full border border-hairline px-2 py-0.5 text-[11px] text-aether-muted-dim"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            ) : null}
          </motion.div>
        </div>
      ) : null}
    </AnimatePresence>
  );
}

export default StorySheet;
