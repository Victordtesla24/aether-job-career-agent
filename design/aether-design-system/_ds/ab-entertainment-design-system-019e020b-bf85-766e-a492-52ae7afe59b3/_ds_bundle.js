/* @ds-bundle: {"format":4,"namespace":"ABEntertainmentDesignSystem_019e02","components":[{"name":"Button","sourcePath":"components/Button/Button.jsx"},{"name":"GlassCard","sourcePath":"components/GlassCard/GlassCard.jsx"},{"name":"OrnamentDivider","sourcePath":"components/OrnamentDivider/OrnamentDivider.jsx"},{"name":"StatusBadge","sourcePath":"components/StatusBadge/StatusBadge.jsx"}],"sourceHashes":{"components/Button/Button.jsx":"44b9e601e276","components/GlassCard/GlassCard.jsx":"948d08011f57","components/OrnamentDivider/OrnamentDivider.jsx":"77864faadd9c","components/StatusBadge/StatusBadge.jsx":"3a61a0b0d747","doc-page.js":"371bab66f42d","tools/build-fonts.js":"3a869d9e18fd","ui_kits/website/events-grid.jsx":"2ae6741c05a5","ui_kits/website/footer.jsx":"2b295d818030","ui_kits/website/hero-section.jsx":"c2d34af1bdf6","ui_kits/website/navigation.jsx":"04a8b4c54524","ui_kits/website/shared.jsx":"46891928245b","ui_kits/website/testimonials.jsx":"9d2519543ac3","ui_kits/website/tweaks-panel.jsx":"d259e3a86f73"},"inlinedExternals":[],"unexposedExports":[]} */

(() => {

const __ds_ns = (window.ABEntertainmentDesignSystem_019e02 = window.ABEntertainmentDesignSystem_019e02 || {});

const __ds_scope = {};

(__ds_ns.__errors = __ds_ns.__errors || []);

// components/Button/Button.jsx
try { (() => {
const GOLD = '#C9A84C';
const base = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  fontFamily: "'AB Sans', 'DM Sans', Helvetica, sans-serif",
  fontSize: '0.72rem',
  fontWeight: 700,
  letterSpacing: '0.12em',
  textTransform: 'uppercase',
  textDecoration: 'none',
  border: 'none',
  cursor: 'pointer',
  transition: 'all 400ms cubic-bezier(0.25,1,0.5,1)'
};
const sizes = {
  sm: {
    padding: '9px 22px',
    fontSize: '0.65rem'
  },
  md: {
    padding: '14px 40px'
  },
  lg: {
    padding: '18px 52px',
    fontSize: '0.78rem'
  }
};
function Button({
  variant = 'primary',
  size = 'md',
  children,
  onClick,
  style
}) {
  const [hover, setHover] = React.useState(false);
  const sz = sizes[size] || sizes.md;
  let skin;
  if (variant === 'outline') {
    skin = {
      background: hover ? GOLD : 'transparent',
      color: hover ? '#000' : GOLD,
      border: `1px solid ${hover ? GOLD : 'rgba(201,168,76,0.25)'}`,
      boxShadow: hover ? '0 0 20px rgba(201,168,76,0.3)' : 'none'
    };
  } else if (variant === 'ghost') {
    skin = {
      background: 'transparent',
      color: hover ? GOLD : 'rgba(255,255,255,0.9)',
      border: `1px solid ${hover ? 'rgba(201,168,76,0.5)' : 'rgba(255,255,255,0.2)'}`,
      fontWeight: 500,
      backdropFilter: 'blur(4px)',
      boxShadow: hover ? '0 0 30px rgba(201,168,76,0.15)' : 'none'
    };
  } else {
    skin = {
      background: hover ? 'linear-gradient(135deg,#D4B65C,#E8D5A3 50%,#D4B65C)' : 'linear-gradient(135deg,#C9A84C,#D4B65C 50%,#C9A84C)',
      color: '#000',
      boxShadow: hover ? '0 0 40px rgba(201,168,76,0.4)' : 'none',
      transform: hover ? 'translateY(-1px)' : 'none'
    };
  }
  return React.createElement('button', {
    onClick,
    onMouseEnter: () => setHover(true),
    onMouseLeave: () => setHover(false),
    style: {
      ...base,
      ...sz,
      ...skin,
      ...style
    }
  }, children);
}
Object.assign(__ds_scope, { Button });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/Button/Button.jsx", error: String((e && e.message) || e) }); }

// components/GlassCard/GlassCard.jsx
try { (() => {
function GlassCard({
  children,
  padding = 24,
  radius = 0,
  style,
  onClick
}) {
  const [hover, setHover] = React.useState(false);
  return React.createElement('div', {
    onClick,
    onMouseEnter: () => setHover(true),
    onMouseLeave: () => setHover(false),
    style: {
      background: hover ? 'rgba(255,255,255,0.04)' : 'rgba(255,255,255,0.02)',
      backdropFilter: 'blur(12px)',
      WebkitBackdropFilter: 'blur(12px)',
      border: `1px solid ${hover ? 'rgba(201,168,76,0.25)' : 'rgba(201,168,76,0.08)'}`,
      boxShadow: hover ? '0 8px 32px rgba(0,0,0,0.4), 0 0 0 1px rgba(201,168,76,0.1), inset 0 1px 0 rgba(255,255,255,0.05)' : 'none',
      transform: hover ? 'translateY(-4px)' : 'translateY(0)',
      transition: 'all 600ms cubic-bezier(0.25,1,0.5,1)',
      borderRadius: radius,
      padding,
      cursor: onClick ? 'pointer' : 'default',
      ...style
    }
  }, children);
}
Object.assign(__ds_scope, { GlassCard });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/GlassCard/GlassCard.jsx", error: String((e && e.message) || e) }); }

// components/OrnamentDivider/OrnamentDivider.jsx
try { (() => {
function OrnamentDivider({
  width = 64,
  style
}) {
  const h = React.createElement;
  return h('div', {
    style: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 12,
      ...style
    }
  }, h('div', {
    style: {
      width,
      height: 1,
      background: 'linear-gradient(90deg,transparent,rgba(201,168,76,0.4))'
    }
  }), h('div', {
    style: {
      width: 8,
      height: 8,
      transform: 'rotate(45deg)',
      border: '1px solid rgba(201,168,76,0.5)'
    }
  }), h('div', {
    style: {
      width,
      height: 1,
      background: 'linear-gradient(90deg,rgba(201,168,76,0.4),transparent)'
    }
  }));
}
Object.assign(__ds_scope, { OrnamentDivider });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/OrnamentDivider/OrnamentDivider.jsx", error: String((e && e.message) || e) }); }

// components/StatusBadge/StatusBadge.jsx
try { (() => {
const TONES = {
  available: {
    label: 'On Sale Now',
    bg: '#22C55E',
    color: '#fff'
  },
  selling_fast: {
    label: 'Selling Fast',
    bg: '#F59E0B',
    color: '#000'
  },
  sold_out: {
    label: 'Sold Out',
    bg: '#DC2626',
    color: '#fff'
  },
  new_date: {
    label: 'New Date Added',
    bg: 'linear-gradient(90deg,#C9A84C,#D4B65C)',
    color: '#000'
  },
  category: {
    label: null,
    bg: 'linear-gradient(90deg,#C9A84C,#D4B65C)',
    color: '#000'
  }
};
function StatusBadge({
  status = 'available',
  label,
  style
}) {
  const tone = TONES[status] || TONES.available;
  const text = label || tone.label;
  if (!text) return null;
  return React.createElement('span', {
    style: {
      display: 'inline-block',
      padding: '4px 10px',
      background: tone.bg,
      color: tone.color,
      fontFamily: "'AB Sans', 'DM Sans', Helvetica, sans-serif",
      fontSize: '9px',
      fontWeight: 700,
      letterSpacing: '0.08em',
      textTransform: 'uppercase',
      ...style
    }
  }, text);
}
Object.assign(__ds_scope, { StatusBadge });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/StatusBadge/StatusBadge.jsx", error: String((e && e.message) || e) }); }

// doc-page.js
try { (() => {
// @ds-adherence-ignore -- omelette starter scaffold (raw elements/hex/px by design)
// Copied omelette starter. Re-running copy_starter_component with this kind overwrites this file with the latest version (page content is unaffected).
/* BEGIN USAGE */
/**
 * <doc-page> — paged-document shell for printable HTML.
 *
 * FIRST, decide how the document paginates — up front, before building:
 *
 * - FLOWING document (the default): write the whole document as one
 *   normal HTML flow inside <doc-page>; the browser's print engine
 *   splits it onto pages at export. Use for long-form documents with a
 *   single text flow: reports, memos, letters, essays.
 * - EXPLICIT pagination: a fixed set of pre-paginated pages, one
 *   <section class="page"> child per page. Use when the user asks for a
 *   specific page count, or the design implies one: a one-page resume, a
 *   two-sided flier, a poster, a certificate, a brochure — any richly
 *   laid-out document without a single text flow.
 * - If in doubt, ask the user as part of the build.
 *
 * PAGE SIZING — paper differs by country (letter vs A4), so the printed
 * sheet is not one fixed truth:
 * - FLOWING documents pin NO paper size: the print engine paginates
 *   onto the user's real paper, and the content reflows to it.
 * - EXPLICITLY PAGINATED documents print each page at a FIXED page box
 *   with overflow hidden — letter by default, size="a4" for a clearly
 *   metric user, the user's chosen paper when they export. Design each
 *   page to FILL that box, fitting letter and A4 alike without overlap.
 * - width/height pin an explicit fixed size, ONLY when the user gives
 *   one.
 * Never write your own @page rule or hard-code paper dimensions in the
 * content.
 *
 * Sizing modes (attributes):
 *   (none)                      — portrait: flowing docs use the user's
 *           paper; explicitly paginated pages use the named size box
 *           (letter unless size="a4")
 *   orientation="landscape"     — the same, landscape
 *   width / height              — explicit fixed size, ONLY when the user
 *           gives one (e.g. width="22in" height="30in" for a 22×30
 *           poster): the page IS the design's size, printed at true
 *           dimensions (or scaled onto the user's paper at print time).
 *           Any absolute CSS length: px/in/mm/cm/pt/pc.
 * The component announces the chosen mode to the host app at runtime (a
 * meta tag it injects), so the print path can inject the user's true
 * paper size.
 *
 * On screen the document renders on a desk background: a flowing
 * document as one tall scrolling sheet (Google Docs' pageless view);
 * explicitly paginated documents as one card per page.
 *
 * EXPLICIT pagination usage:
 *   <style>doc-page:not(:defined){visibility:hidden}</style>
 *   <doc-page>
 *     <section class="page" id="p1">…one page's design…</section>
 *     <section class="page" id="p2">…</section>
 *   </doc-page>
 *   <script src="doc-page.js"></script>
 * How the page box works, concretely: each .page prints as ONE full-bleed
 * sheet at a FIXED physical size — letter by default (set size="a4" for
 * a clearly metric user), the user's chosen paper when they export —
 * with overflow hidden. Nothing scrolls and nothing reflows onto a next
 * sheet: content that misses the box is CLIPPED. Design each page to
 * FILL that page box, and to fit it — letter and A4 alike — without
 * overlap. Each page is a size container; don't size anything in
 * viewport units (they track the window, not the page), and never set
 * width or height on the .page section itself (the component sizes the
 * page box; an authored height like 100% is meaningless at print and is
 * overridden). The component owns the page box, the screen card chrome,
 * and the page breaks (never add your own break-before/after). Don't mix
 * .page sections with flowing content or header/footer slots in the same
 * document.
 *
 * FLOWING usage:
 *   <style>doc-page:not(:defined){visibility:hidden}</style>
 *   <doc-page margin="0.75in">
 *     <h1>Title</h1>
 *     <p>…body…</p>
 *   </doc-page>
 *   <script src="doc-page.js"></script>
 * There is no manual page-splitting — the browser's print engine
 * paginates at export. Standard break-hygiene rules (`break-inside:
 * avoid` on figures, code blocks, images and table rows; `orphans/
 * widows: 3`) are applied so paragraphs and groups split cleanly. On
 * screen and at print, headings default to `text-wrap: balance` and
 * body text to `text-wrap: pretty`; the defaults have zero specificity,
 * so any text-wrap you declare wins.
 *
 * Other attributes:
 *   size    — letter | a4 | legal (default letter). Flowing documents:
 *           preview proportion only — it does NOT pin their printed
 *           paper (the print dialog's paper governs); leave it alone
 *           there. Explicitly paginated documents: it sets the page box
 *           the cards and the pinned @page share (the export dialog's
 *           choice overrides both at print) — set size="a4" for a
 *           clearly metric user. Scaled-fit: names the sheet the fit is
 *           computed against, same a4-for-metric-users advice.
 *   content-width / content-height — the design's own fixed dimensions
 *           (CSS lengths), for scaling a fixed-size design ONTO the
 *           named sheet: content lays out at exactly this size, and the
 *           component scales it to fit that sheet's printable area
 *           (centered horizontally, top-aligned; the export dialog
 *           re-fits to the user's actual paper choice where available).
 *           Both must be set; they do not change the page box. For pages
 *           WITHOUT running header/footer slots.
 *   margin  — printable inset on every page of a FLOWING document
 *           (default 0.75in); margin="0" makes pages full-bleed.
 *           Explicitly paginated pages are always full-bleed.
 *
 * Running header/footer (flowing documents only): give an element
 * `slot="header"` or `slot="footer"` and it repeats on every printed
 * page via `position: fixed`. To keep body text from sliding under it,
 * the component prints inside a single-cell table whose <thead>/<tfoot>
 * are spacers sized to the header/footer height — browsers repeat
 * thead/tfoot on every page, so each sheet's content starts below the
 * header and ends above the footer. On screen the header/footer render
 * once at the top/bottom of the sheet.
 *
 * At print the component injects `@page { margin: 0 }` (which leaves
 * Chrome no margin box to draw its date/URL/page-count header in) and
 * moves the visual margin onto the sheet's own padding. It also marks
 * the document as owning its print CSS (a
 * `meta[name="omelette-owns-print"]` it injects at runtime), so the
 * PDF export never injects page-geometry CSS of its own on top.
 *
 * Print best practices for the content you author:
 * - Multi-column text: use CSS columns (`column-count` +
 *   `column-gap`), never side-by-side flex/grid columns — only real
 *   CSS columns flow and break across pages. `column-span: all` lets
 *   a heading span the columns; `hyphens: auto` (needs `lang` on
 *   the html element) keeps narrow columns readable.
 * - Page breaks in flowing documents: `break-before: page` on an
 *   element that must start a new page (a chapter, an appendix). Add
 *   your own kept-together blocks (callouts, stat tiles, cards) to a
 *   `break-inside: avoid` rule, and keep each one shorter than a page.
 * - Extend `orphans: 3; widows: 3` to any custom text blocks you add
 *   (p and li are covered by default).
 * - Give long tables a <thead> — browsers repeat it on every printed
 *   page.
 * - No `position: fixed`/`sticky` and no viewport units in content:
 *   fixed elements stamp every printed page (running headers/footers go
 *   in the component's slots) and `100vh` mis-sizes at print.
 *
 * Author content as static HTML so the user can click-to-edit any text
 * directly. Do not set width/padding/background on the document body —
 * the component owns the sheet box.
 */
/* END USAGE */

(() => {
  const PAPER = {
    letter: ['8.5in', '11in'],
    a4: ['210mm', '297mm'],
    legal: ['8.5in', '14in']
  };
  const CSS_LENGTH = /^\d+(\.\d+)?(px|in|mm|cm|pt|pc)$/;
  // Unitless "0" is a valid CSS length and the natural way to write
  // margin="0"; normalise it to 0px so max()/calc() (which reject a bare
  // number) keep working.
  const safeLen = (v, fb) => {
    v = (v || '').trim();
    return v === '0' ? '0px' : CSS_LENGTH.test(v) ? v : fb;
  };
  // WebKit (Safari and every iOS browser shell) never repeats a table's
  // thead/tfoot on printed pages (WebKit bug 17205), so the spacer-borne
  // vertical margins of a FLOWING document reach only the first page
  // there. Engine check, not browser check: vendor is 'Apple Computer,
  // Inc.' exactly for WebKit and 'Google Inc.' for Blink.
  const WK_PRINT = /apple/i.test(navigator.vendor || '');
  // CSS length → px number (CSS absolute units are exact: 1in = 96px).
  // Returns NaN for anything safeLen would reject — callers gate on it.
  const PX_PER = {
    px: 1,
    in: 96,
    mm: 96 / 25.4,
    cm: 96 / 2.54,
    pt: 96 / 72,
    pc: 16
  };
  const toPx = v => {
    const m = /^(\d+(?:\.\d+)?)(px|in|mm|cm|pt|pc)$/.exec((v || '').trim());
    return m ? parseFloat(m[1]) * PX_PER[m[2]] : NaN;
  };
  const stylesheet = `
    :host {
      position: relative;
      display: block;
      /* When the viewport is narrower than the page, grow to wrap the
       * sheet (plus this padding) instead of staying viewport-width, so
       * the desk background and right margin reach the sheet's far edge
       * in the horizontal scroll. */
      min-width: max-content;
      min-height: 100vh;
      background: #f5f5f4;
      padding: 48px 24px;
      box-sizing: border-box;
      font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
      --doc-page-w: 8.5in;
      --doc-page-h: 11in;
      --doc-page-margin: 0.75in;
      --doc-hdr-h: 0px;
      --doc-ftr-h: 0px;
      --doc-hdr-pad: 0px;
      --doc-ftr-pad: 0px;
    }
    .sheet {
      width: var(--doc-page-w);
      margin: 0 auto;
      background: #fff;
      box-shadow: 0 2px 10px rgba(20, 20, 19, 0.12);
      border-radius: 7px;
      box-sizing: border-box;
      padding: var(--doc-page-margin);
    }
    .frame { width: 100%; border-collapse: collapse; }
    /* Scaled-fit mode (content-width/content-height): the inner .fit box
     * lays the content out at its authored fixed size and scales it onto
     * the printable area; .fit-box reserves the scaled footprint in flow
     * (transforms don't affect layout) and centers it. Without the mode,
     * both divs are unstyled block pass-throughs. */
    /* Explicit pagination: direct .page children are the pages. The sheet
     * becomes a transparent stack and each page carries the card look on
     * screen; at print each page is exactly one full-bleed sheet. The
     * ::slotted defaults are deliberately weak (document CSS wins), so
     * authored page styling can override any of this. */
    .sheet.paginated {
      background: transparent;
      box-shadow: none;
      border-radius: 0;
      padding: 0;
    }
    .paginated ::slotted(.page) {
      position: relative;
      display: block;
      width: 100%;
      aspect-ratio: var(--doc-page-ar);
      container-type: size;
      overflow: hidden;
      box-sizing: border-box;
      background: #fff;
      border-radius: 7px;
      box-shadow: 0 2px 10px rgba(0, 0, 0, 0.25);
      print-color-adjust: exact;
      -webkit-print-color-adjust: exact;
      break-inside: avoid;
    }
    .paginated ::slotted(.page:not(:first-child)) { margin-top: 1rem; }
    @media print {
      .sheet.paginated { padding: 0; }
      /* The flowing-document vertical inset lives on the repeating
       * thead/tfoot spacers, not the sheet padding — they must go too,
       * or each full-sheet .page is pushed ~margin down and spills onto
       * a second sheet. Paginated pages are full-bleed by definition
       * (content owns its insets). */
      .sheet.paginated .hdr-space,
      .sheet.paginated .ftr-space { height: 0; }
      .paginated ::slotted(.page) {
        border-radius: 0 !important;
        box-shadow: none !important;
        margin: 0 !important;
        /* Physical page-box sizing, no viewport units: Safari resolves
         * 100vh against the window, not the page box, so a vh-sized card
         * paginates wrong there. --doc-page-w/h are the named size by
         * default and are overridden to the user's chosen paper by the
         * export path, so every card is exactly one sheet either way.
         * Width + height (same source values as @page size) rather than
         * width + aspect-ratio: the ratio is a 6-decimal rounding of the
         * same division, and a few millionths of overflow would spill a
         * blank sheet after every page. The screen-only aspect-ratio
         * (preview proportions) must not leak into print. cqh typography
         * tracks the same box.
         *
         * Every declaration is !important: per CSS Scoping, unimportant
         * shadow ::slotted rules LOSE to the document context, so a page
         * section's authored inline style would silently beat this print
         * geometry. A model-authored height:100% did exactly that — the
         * percentage resolves as auto in the all-auto print ancestry, the
         * base rule's size containment turns auto into ZERO, and
         * overflow:hidden then paints nothing: a blank PDF with perfect
         * page boxes. At print the component's geometry is the design's
         * whole contract, so it must win over any authored sizing. */
        aspect-ratio: auto !important;
        width: var(--doc-page-w) !important;
        height: var(--doc-page-h) !important;
        overflow: hidden !important;
      }
      .paginated ::slotted(.page:not(:first-child)) {
        break-before: page !important;
        margin-top: 0 !important;
      }
    }
    .fit-mode .fit-box {
      width: calc(var(--doc-fit-w) * var(--doc-fit-scale));
      height: calc(var(--doc-fit-h) * var(--doc-fit-scale));
      margin: 0 auto;
      break-inside: avoid;
    }
    .fit-mode .fit {
      width: var(--doc-fit-w);
      height: var(--doc-fit-h);
      transform: scale(var(--doc-fit-scale));
      transform-origin: top left;
    }
    .frame td, .frame th { padding: 0; text-align: left; font-weight: inherit; }
    .hdr-space { height: var(--doc-hdr-h); }
    .ftr-space { height: var(--doc-ftr-h); }
    ::slotted([slot="header"]),
    ::slotted([slot="footer"]) { display: block; box-sizing: border-box; }
    @media print {
      :host { background: none; padding: 0; min-width: 0; min-height: 0; }
      .sheet {
        width: auto; margin: 0; box-shadow: none; border-radius: 0;
        padding: 0 var(--doc-page-margin);
      }
      /* The thead/tfoot spacers repeat on every page, so they carry the
       * vertical page margin (which the sheet's own padding cannot, since
       * that padding is consumed once on the first/last page). The running
       * header/footer are fixed inside that band. */
      /* The 0.35in is breathing room between a running header/footer and
       * the body; without one the spacer is exactly the page margin, so a
       * margin="0" full-bleed document gets truly full-bleed pages. */
      .hdr-space { height: max(var(--doc-page-margin), calc(var(--doc-hdr-h) + var(--doc-hdr-pad))); }
      .ftr-space { height: max(var(--doc-page-margin), calc(var(--doc-ftr-h) + var(--doc-ftr-pad))); }
      /* WebKit flowing documents: @page carries the vertical margin (see
       * _syncPrintPageRule), so the spacers keep only whatever a running
       * header/footer needs BEYOND it — page 1 would otherwise double its
       * top inset. Paginated sheets already zero their spacers above. */
      .sheet.wk-print:not(.paginated) .hdr-space { height: max(0px, calc(max(var(--doc-page-margin), calc(var(--doc-hdr-h) + var(--doc-hdr-pad))) - var(--doc-page-margin))); }
      .sheet.wk-print:not(.paginated) .ftr-space { height: max(0px, calc(max(var(--doc-page-margin), calc(var(--doc-ftr-h) + var(--doc-ftr-pad))) - var(--doc-page-margin))); }
      ::slotted([slot="header"]) {
        position: fixed; top: 0; left: 0; right: 0; margin: 0;
        padding: calc(var(--doc-page-margin) * 0.45) var(--doc-page-margin) 0;
      }
      ::slotted([slot="footer"]) {
        position: fixed; bottom: 0; left: 0; right: 0; margin: 0;
        padding: 0 var(--doc-page-margin) calc(var(--doc-page-margin) * 0.45);
      }
    }
  `;
  class DocPage extends HTMLElement {
    static get observedAttributes() {
      return ['size', 'width', 'height', 'margin', 'orientation', 'content-width', 'content-height'];
    }
    constructor() {
      super();
      this._root = this.attachShadow({
        mode: 'open'
      });
      this._mo = typeof MutationObserver === 'function' ? new MutationObserver(() => this._scheduleMeasure()) : null;
    }

    /** The named paper's [w, h], swapped when orientation="landscape".
     *  Only the named size swaps — explicit width/height are exact values
     *  the author already oriented. */
    _paperSize() {
      const named = PAPER[(this.getAttribute('size') || '').toLowerCase()] || PAPER.letter;
      const landscape = (this.getAttribute('orientation') || '').trim().toLowerCase() === 'landscape';
      return landscape ? [named[1], named[0]] : named;
    }
    get pageWidth() {
      return safeLen(this.getAttribute('width'), this._paperSize()[0]);
    }
    get pageHeight() {
      return safeLen(this.getAttribute('height'), this._paperSize()[1]);
    }
    get pageMargin() {
      return safeLen(this.getAttribute('margin'), '0.75in');
    }

    /** Scaled-fit mode's content box [w, h] as CSS lengths, or null when
     *  the mode is off (either attribute missing/invalid/zero — a partial
     *  declaration falls back to normal flow rather than guessing). */
    _contentFit() {
      const w = safeLen(this.getAttribute('content-width'), null);
      const h = safeLen(this.getAttribute('content-height'), null);
      if (!w || !h) return null;
      const wPx = toPx(w),
        hPx = toPx(h);
      return wPx > 0 && hPx > 0 ? [w, h, wPx, hPx] : null;
    }
    connectedCallback() {
      if (!this._sheet) this._render();
      this._syncSize();
      this._syncPrintPageRule();
      this._ensureTextWrapDefaults();
      this._ensureOwnsPrintMeta();
      this._syncFixedSizeMeta();
      this._syncPrintSizingMeta();
      if (this._mo) this._mo.observe(this, {
        subtree: true,
        childList: true,
        characterData: true,
        attributes: true
      });
      this._onResize = () => this._scheduleMeasure();
      window.addEventListener('resize', this._onResize);
      if (document.fonts && document.fonts.ready) {
        document.fonts.ready.then(() => this._scheduleMeasure());
      }
      this._scheduleMeasure();
    }
    disconnectedCallback() {
      window.removeEventListener('resize', this._onResize);
      if (this._mo) this._mo.disconnect();
      if (this._raf) {
        cancelAnimationFrame(this._raf);
        this._raf = null;
      }
      // Drop the head rules when the last doc-page leaves, so a deleted
      // document's @page geometry and text-wrap defaults can't apply to
      // whatever replaces it.
      const survivor = document.querySelector('doc-page');
      if (!survivor) {
        ['doc-page-print', 'doc-page-text-wrap', 'doc-page-owns-print', 'doc-page-fixed-size', 'doc-page-print-sizing'].forEach(id => {
          const tag = document.getElementById(id);
          if (tag) tag.remove();
        });
        // A live deck-stage deferred its own print-sizing meta to ours —
        // hand the page-global meta over so the deck isn't left unmarked.
        const deck = document.querySelector('deck-stage');
        if (deck && typeof deck._ensurePrintSizingMeta === 'function') {
          deck._ensurePrintSizingMeta();
        }
      } else {
        // A departed owner hands each page-global meta to whatever
        // doc-page remains (or it's removed).
        if (typeof survivor._syncFixedSizeMeta === 'function') {
          survivor._syncFixedSizeMeta();
        }
        if (typeof survivor._syncPrintSizingMeta === 'function') {
          survivor._syncPrintSizingMeta();
        }
      }
    }
    attributeChangedCallback() {
      if (!this._sheet) return;
      this._syncSize();
      this._syncPrintPageRule();
      this._syncFixedSizeMeta();
      this._syncPrintSizingMeta();
      this._scheduleMeasure();
    }
    _render() {
      this._root.innerHTML = `
        <style>${stylesheet}</style>
        <style id="vars"></style>
        <div class="sheet" data-screen-label="Document">
          <table class="frame" role="presentation">
            <thead><tr><th><div class="hdr-space"><slot name="header"></slot></div></th></tr></thead>
            <tbody><tr><td class="body"><div class="fit-box"><div class="fit"><slot></slot></div></div></td></tr></tbody>
            <tfoot><tr><td><div class="ftr-space"><slot name="footer"></slot></div></td></tr></tfoot>
          </table>
        </div>`;
      this._sheet = this._root.querySelector('.sheet');
      this._vars = this._root.getElementById('vars');
    }

    /** Runtime sizing lives in a shadow <style> :host rule, never on the
     *  light-DOM host element, so serialize-persist can't write it back. */
    _syncSize(hdrH, ftrH) {
      // Scaled-fit mode: content at its authored size, scaled onto the
      // printable area (page minus margins on both axes). The factor is a
      // plain number var so calc(length * number) stays valid; 4 decimals
      // keeps the shadow style stable across re-measures. Upscaling is
      // allowed — print transforms are vector, so text and CSS stay crisp
      // (raster images soften, which the catalog bullet warns about).
      const fit = this._contentFit();
      let fitVars = '';
      if (fit) {
        const marginPx = toPx(this.pageMargin) || 0;
        const availW = toPx(this.pageWidth) - 2 * marginPx;
        const availH = toPx(this.pageHeight) - 2 * marginPx;
        const scale = Math.min(availW / fit[2], availH / fit[3]);
        if (scale > 0 && Number.isFinite(scale)) {
          fitVars = '--doc-fit-w:' + fit[0] + ';' + '--doc-fit-h:' + fit[1] + ';' + '--doc-fit-scale:' + scale.toFixed(4) + ';';
        }
      }
      this._sheet.classList.toggle('fit-mode', !!fitVars);
      // Numeric w/h ratio for the paginated page cards' aspect-ratio —
      // aspect-ratio takes a number, not a length ratio, so compute it
      // here (CSS length division isn't portable). 6 decimals keeps the
      // shadow style stable across re-syncs.
      const arW = toPx(this.pageWidth);
      const arH = toPx(this.pageHeight);
      const ar = arW > 0 && arH > 0 ? (arW / arH).toFixed(6) : '0.772727';
      this._vars.textContent = ':host{' + fitVars + '--doc-page-ar:' + ar + ';' + '--doc-page-w:' + this.pageWidth + ';' + '--doc-page-h:' + this.pageHeight + ';' + '--doc-page-margin:' + this.pageMargin + ';' + '--doc-hdr-h:' + (hdrH || 0) + 'px;' + '--doc-ftr-h:' + (ftrH || 0) + 'px;' + '--doc-hdr-pad:' + (hdrH ? '0.35in' : '0px') + ';' + '--doc-ftr-pad:' + (ftrH ? '0.35in' : '0px') + '}';
    }

    /** @page is a no-op inside shadow DOM, so the rule lives in <head>.
     *  Re-appended on every sync so it stays last in source order — the
     *  @page cascade is source-order per descriptor, so this rule wins
     *  over any other @page rule in the document.
     *
     *  The @page SIZE is pinned where the page box IS part of the design:
     *  explicit-fixed-size mode (width + height authored), scaled-fit
     *  mode (the named sheet the fit targets), and explicit pagination
     *  (the named size the cards share — so card and sheet agree on
     *  every print path, and the export path's chosen paper overrides
     *  BOTH with one later rule). For FLOWING documents no paper size is
     *  emitted at all — the true size comes from the user's preference,
     *  injected by the export path or chosen in the print dialog — so a
     *  flowing document never fights the paper it lands on.
     *  margin: 0 is emitted in every mode: it leaves Chrome no margin box
     *  to draw its date/URL/page-count header in, and the visual margin
     *  lives on the sheet's own padding. */
    _syncPrintPageRule() {
      const id = 'doc-page-print';
      let tag = document.getElementById(id);
      if (!tag) {
        tag = document.createElement('style');
        tag.id = id;
      }
      document.head.appendChild(tag);
      // Three print-geometry regimes:
      // - true-size: the page IS the design — pin its exact size.
      // - scaled-fit (content-width/height): the fit factor is computed
      //   against the NAMED paper's printable area, so that paper must
      //   stay pinned or the scaled content overflows a smaller sheet
      //   (the export path re-fits and re-pins at print time on top).
      // - default modes: no paper size — but landscape still needs the
      //   paper-agnostic 'size: landscape' keyword, because the size
      //   descriptor is what carries orientation; without it a landscape
      //   document prints portrait whenever nothing injects a size.
      const landscape = (this.getAttribute('orientation') || '').trim().toLowerCase() === 'landscape';
      // Explicit pagination pins the page box to the SAME values that
      // size the cards (the named size by default, the export path's
      // chosen paper when its later rule overrides both) — card and
      // sheet agree on every print path, and a mismatched real paper
      // shrinks-to-fit in the dialog instead of clipping a Letter card
      // on A4. Declared before the paginated read below so both derive
      // from one check.
      const paginatedNow = this.querySelector(':scope > .page') !== null;
      const sizeDescriptor = this._trueSizePx() ? 'size: ' + this.pageWidth + ' ' + this.pageHeight + '; ' : this._contentFit() ? 'size: ' + this.pageWidth + ' ' + this.pageHeight + '; ' : paginatedNow ? 'size: ' + this.pageWidth + ' ' + this.pageHeight + '; ' : landscape ? 'size: landscape; ' : '';
      // WebKit never repeats the thead/tfoot spacers that carry a flowing
      // document's vertical page margins (see WK_PRINT above), so pages
      // after the first print edge-to-edge there. Carry the VERTICAL
      // margins on @page for WebKit instead, and the shadow print CSS
      // trims the first-page spacers by the same amount (.sheet.wk-print
      // rules). Horizontal inset stays on the sheet's own padding in
      // every engine. Blink keeps margin: 0 (a nonzero margin there
      // re-opens the box Chrome draws its header furniture in). One cost,
      // learned in testing: Safari's own date/URL headers are a USER
      // dialog setting ("Print headers and footers") that renders in the
      // margin area when room exists — margin: 0 only suppressed it by
      // leaving no room, and no CSS controls it. The export dialog's
      // Safari guide teaches turning the setting off for flowing
      // documents. Explicitly paginated and fixed-size documents keep
      // margin: 0 everywhere: their pages ARE the sheet.
      const wkFlowing = WK_PRINT && !paginatedNow && !this._trueSizePx() && !this._contentFit();
      const marginDescriptor = wkFlowing ? 'margin: ' + this.pageMargin + ' 0; ' : 'margin: 0; ';
      // Shadow-internal marker (never serialized), kept in lockstep with
      // the @page decision above: the print CSS trims the first-page
      // spacers ONLY while @page actually carries the margins — a
      // true-size or scaled-fit sheet keeps margin: 0 and must keep its
      // spacers too. Re-synced here so attribute changes and pagination
      // flips move both together.
      if (this._sheet) this._sheet.classList.toggle('wk-print', wkFlowing);
      tag.textContent = '@page { ' + sizeDescriptor + marginDescriptor + '} ' + '@media print { html, body { margin: 0 !important; padding: 0 !important; background: none !important; height: auto !important; overflow: visible !important; } ' + 'h1,h2,h3,h4,h5,h6 { break-after: avoid; } ' + 'figure,pre,blockquote,img,svg,tr { break-inside: avoid; } ' + 'p,li { orphans: 3; widows: 3; } ' + '* { -webkit-print-color-adjust: exact; print-color-adjust: exact; ' + 'backdrop-filter: none !important; -webkit-backdrop-filter: none !important; } ' + '*, *::before, *::after { animation-delay: -99s !important; animation-duration: .001s !important; ' + 'animation-iteration-count: 1 !important; animation-fill-mode: both !important; ' + 'animation-play-state: running !important; transition-duration: 0s !important; } }';
    }

    /** Typographic defaults for document text: balance headings, avoid
     *  widowed/orphaned words in body copy (browsers without text-wrap
     *  support drop the declarations). Zero-specificity via :where() so
     *  any text-wrap authored on those elements wins; document-level so the
     *  rules reach the slotted (light DOM) content — shadow styles can't.
     *  data-omelette-injected marks the tag for the host editor to strip
     *  at serialize, so it is never written back as authored source. */
    _ensureTextWrapDefaults() {
      if (document.getElementById('doc-page-text-wrap')) return;
      const tag = document.createElement('style');
      tag.id = 'doc-page-text-wrap';
      tag.setAttribute('data-omelette-injected', '');
      tag.textContent = ':where(h1,h2,h3,h4,h5,h6){text-wrap:balance}' + ':where(p,li,blockquote,figcaption){text-wrap:pretty}';
      document.head.appendChild(tag);
    }

    /** Declares that this document owns its print CSS. The instant-PDF
     *  export checks for the meta by NAME PRESENCE alone (content is
     *  ignored) and skips its automatic print-CSS injections, so the
     *  component's @page geometry is never overridden by a heuristic.
     *  data-omelette-injected keeps it out of serialized source. */
    _ensureOwnsPrintMeta() {
      if (document.getElementById('doc-page-owns-print')) return;
      const tag = document.createElement('meta');
      tag.id = 'doc-page-owns-print';
      tag.name = 'omelette-owns-print';
      tag.content = 'true';
      tag.setAttribute('data-omelette-injected', '');
      document.head.appendChild(tag);
    }

    /** This page's valid true-size page box (explicit width AND height)
     *  as [w, h] px ints, or null when the mode is off. */
    _trueSizePx() {
      if (!safeLen(this.getAttribute('width'), null) || !safeLen(this.getAttribute('height'), null)) return null;
      const w = Math.round(toPx(this.pageWidth));
      const h = Math.round(toPx(this.pageHeight));
      return w > 0 && h > 0 ? [w, h] : null;
    }

    /** True-size pages (explicit width AND height) also declare the page
     *  box as the preview size: the in-app preview reads
     *  meta[name="omelette-fixed-size"] (content "W,H" in px ints) and
     *  scales the sheet into view — without it an 18in poster previews at
     *  true size with scrollbars. Never overrides an author-set meta
     *  (only the component's own id is managed). The meta is page-global
     *  while doc-page instances are not, so every sync recomputes the
     *  page-wide owner — the first connected true-size doc-page — and a
     *  non-true-size sibling's sync can never delete the owner's meta.
     *  Removed when no true-size page remains (the owner's disconnect
     *  re-syncs via any survivor) or when an author-set meta exists. */
    _syncFixedSizeMeta() {
      const id = 'doc-page-fixed-size';
      const own = document.getElementById(id);
      const authored = document.querySelector('meta[name="omelette-fixed-size"]:not([data-omelette-injected])');
      // The page-wide owner, not this instance: an upgraded true-size page
      // anywhere in the document keeps the meta alive and sized.
      let box = null;
      for (const el of document.querySelectorAll('doc-page')) {
        box = typeof el._trueSizePx === 'function' ? el._trueSizePx() : null;
        if (box) break;
      }
      if (!box || authored) {
        if (own) own.remove();
        return;
      }
      const tag = own || document.createElement('meta');
      tag.id = id;
      tag.name = 'omelette-fixed-size';
      tag.content = box[0] + ',' + box[1];
      tag.setAttribute('data-omelette-injected', '');
      if (!own) document.head.appendChild(tag);
    }

    /** This page's print-sizing mode: 'fixed' when an explicit width AND
     *  height are authored (the page is the design's own size), else the
     *  default paper in the authored orientation. */
    _printSizingMode() {
      if (this._trueSizePx()) return 'fixed';
      const landscape = (this.getAttribute('orientation') || '').trim().toLowerCase() === 'landscape';
      return landscape ? 'default-landscape' : 'default-portrait';
    }

    /** Announces the print-sizing mode to the host app:
     *  meta[name="omelette-print-sizing"] with content 'default-portrait',
     *  'default-landscape', or 'fixed' (fixed pages also carry the
     *  omelette-fixed-size meta with the page box in px). The export path
     *  probes it to decide what true paper size to inject at print time —
     *  in the default modes the component emits no paper size of its own.
     *  Same page-global ownership rules as the fixed-size meta above:
     *  first connected doc-page owns it, an authored meta is never
     *  overridden, removed when no doc-page remains. */
    _syncPrintSizingMeta() {
      const id = 'doc-page-print-sizing';
      const own = document.getElementById(id);
      const authored = document.querySelector('meta[name="omelette-print-sizing"]:not([data-omelette-injected])');
      // A fixed page wins outright (mirroring the fixed-size loop above,
      // so the two metas can never contradict each other in a mixed
      // multi-page document); otherwise the first page's mode holds.
      let mode = null;
      for (const el of document.querySelectorAll('doc-page')) {
        if (typeof el._printSizingMode !== 'function') continue;
        const m = el._printSizingMode();
        if (m === 'fixed') {
          mode = m;
          break;
        }
        if (mode === null) mode = m;
      }
      if (!mode || authored) {
        if (own) own.remove();
        return;
      }
      // A deck-stage that connected first injected its own meta and
      // defers to any existing one — take it over, or the document ends
      // up with two conflicting injected metas (a doc-page page is the
      // document; the deck re-ensures its meta if every doc-page leaves).
      const deckMeta = document.getElementById('deck-stage-print-sizing');
      if (deckMeta) deckMeta.remove();
      const tag = own || document.createElement('meta');
      tag.id = id;
      tag.name = 'omelette-print-sizing';
      tag.content = mode;
      tag.setAttribute('data-omelette-injected', '');
      if (!own) document.head.appendChild(tag);
    }
    _scheduleMeasure() {
      if (this._raf) return;
      this._raf = requestAnimationFrame(() => {
        this._raf = null;
        this._measure();
      });
    }

    /** Slot heights feed the print spacers (--doc-hdr-h / --doc-ftr-h), so
     *  they re-measure on content mutation, resize, and font load. The
     *  same pass detects explicit pagination (direct .page children) and
     *  toggles the sheet between the flowing-document card and the
     *  page-per-card stack — content edits can add or remove pages at any
     *  time, so this tracks the same mutations the measurement does. */
    _measure() {
      const hdr = this.querySelector(':scope > [slot="header"]');
      const ftr = this.querySelector(':scope > [slot="footer"]');
      const wasPaginated = this._sheet.classList.contains('paginated');
      this._sheet.classList.toggle('paginated', this.querySelector(':scope > .page') !== null);
      // The WebKit @page margin is flowing-only, so a pagination flip
      // must re-emit the rule (content edits can add or remove .page
      // sections at any time).
      if (this._sheet.classList.contains('paginated') !== wasPaginated) {
        this._syncPrintPageRule();
      }
      this._syncSize(hdr ? hdr.offsetHeight : 0, ftr ? ftr.offsetHeight : 0);
    }
  }
  if (!customElements.get('doc-page')) {
    customElements.define('doc-page', DocPage);
  }
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "doc-page.js", error: String((e && e.message) || e) }); }

// tools/build-fonts.js
try { (() => {
// AB Entertainment font generator — v3
// Both faces share one verified letterform table.
//   • Winding: fills normalized CCW (+area), holes CW (−area) → non-zero fill cuts holes.
//   • Curves are polyline-sampled; no hand-rolled bezier control points.
//   • Stencil bands (AB Marquee) are applied per-contour, and ONLY to convex contours
//     (rects / ellipses / diagonal quads). Ribbon contours are non-convex, so clipping
//     them would bridge separated pieces — those strokes stay continuous by design.
(function () {
  'use strict';

  const UPM = 1000,
    CAP = 700,
    ASC = 800,
    DESC = -200;
  const area = p => {
    let a = 0;
    for (let i = 0; i < p.length; i++) {
      const [x1, y1] = p[i],
        [x2, y2] = p[(i + 1) % p.length];
      a += x1 * y2 - x2 * y1;
    }
    return a / 2;
  };
  const R = (x, y, w, h) => [[x, y], [x + w, y], [x + w, y + h], [x, y + h]];
  function arc(cx, cy, rx, ry, a0, a1, steps) {
    steps = steps || Math.max(10, Math.ceil(Math.abs(a1 - a0) / 8));
    const o = [];
    for (let i = 0; i <= steps; i++) {
      const t = (a0 + (a1 - a0) * i / steps) * Math.PI / 180;
      o.push([cx + rx * Math.cos(t), cy + ry * Math.sin(t)]);
    }
    return o;
  }
  const ellipsePts = (cx, cy, rx, ry) => arc(cx, cy, rx, ry, 0, 360, 48).slice(0, -1);

  // Sutherland–Hodgman against a horizontal band (convex clip region)
  function clipBand(pts, lo, hi) {
    const cut = (poly, keep, yv) => {
      if (!poly.length) return [];
      const out = [];
      for (let i = 0; i < poly.length; i++) {
        const A = poly[i],
          B = poly[(i + 1) % poly.length],
          ia = keep(A[1], yv),
          ib = keep(B[1], yv);
        if (ia) out.push(A);
        if (ia !== ib) {
          const t = (yv - A[1]) / (B[1] - A[1] || 1e-9);
          out.push([A[0] + (B[0] - A[0]) * t, yv]);
        }
      }
      return out;
    };
    let p = cut(pts, (y, v) => y >= v, lo);
    p = cut(p, (y, v) => y <= v, hi);
    return p.length >= 3 ? p : null;
  }

  // ─── drawing context: routes contours through optional stencil banding ─────
  function Ctx(bands) {
    const path = new opentype.Path();
    const zones = bands ? [[-200, bands.c1], [bands.c1 + bands.cut, bands.c2], [bands.c2 + bands.cut, CAP + 200]] : null;
    const put = (pts, isHole) => {
      const norm = isHole ? area(pts) > 0 ? pts.slice().reverse() : pts : area(pts) < 0 ? pts.slice().reverse() : pts;
      if (norm.length < 3) return;
      path.moveTo(norm[0][0], norm[0][1]);
      for (let i = 1; i < norm.length; i++) path.lineTo(norm[i][0], norm[i][1]);
      path.close();
    };
    const emit = (pts, isHole, convex) => {
      if (zones && convex) {
        for (const [lo, hi] of zones) {
          const c = clipBand(pts, lo, hi);
          if (c) put(c, isHole);
        }
      } else put(pts, isHole);
    };
    return {
      path,
      fill: pts => emit(pts, false, true),
      hole: pts => emit(pts, true, true),
      // ribbon: non-convex as one contour, so when banding is active it is emitted as a
      // strip of per-step quads (each convex) to go through the same band-clip path.
      ribbon: (outer, inner) => {
        if (!zones) {
          emit(outer.concat(inner.slice().reverse()), false, false);
          return;
        }
        const n = Math.min(outer.length, inner.length);
        for (let i = 0; i < n - 1; i++) emit([outer[i], outer[i + 1], inner[i + 1], inner[i]], false, true);
      }
    };
  }

  // ─── shared letterform table ──────────────────────────────────────────────
  // Each entry: [char, unicode, baseWidth, draw(k)] where k bundles helpers+metrics.
  function letterTable() {
    return [['A', 65, 640, k => {
      k.seg(k.h, 0, k.w / 2, CAP);
      k.seg(k.w / 2, CAP, k.w - k.h, 0);
      const y = CAP * 0.34,
        r = y / CAP,
        lx = k.h + (k.w / 2 - k.h) * r,
        rx = k.w - k.h - (k.w / 2 - k.h) * r;
      k.H(lx, y, rx - lx);
    }], ['B', 66, 610, k => {
      k.V(k.h, 0, CAP);
      const m = CAP * 0.5;
      k.bowl(k.sw, k.w - k.h, m - k.sw * 0.15, CAP);
      k.bowl(k.sw, k.w, 0, m + k.sw * 0.15);
    }], ['C', 67, 650, k => k.aperture(52, 308)], ['D', 68, 660, k => {
      k.V(k.h, 0, CAP);
      k.bowl(k.sw, k.w, 0, CAP);
    }], ['E', 69, 555, k => {
      k.V(k.h, 0, CAP);
      k.H(k.h, CAP - k.h, k.w - k.h);
      k.H(k.h, CAP / 2, k.w - k.h - k.sw * 0.45);
      k.H(k.h, k.h, k.w - k.h);
    }], ['F', 70, 535, k => {
      k.V(k.h, 0, CAP);
      k.H(k.h, CAP - k.h, k.w - k.h);
      k.H(k.h, CAP / 2, k.w - k.h - k.sw * 0.45);
    }], ['G', 71, 680, k => {
      k.aperture(52, 308);
      k.V(k.w - k.h, CAP * 0.17, CAP * 0.31);
      k.H(k.w / 2, CAP * 0.44, k.w / 2 - k.h);
    }], ['H', 72, 660, k => {
      k.V(k.h, 0, CAP);
      k.V(k.w - k.h, 0, CAP);
      k.H(0, CAP / 2, k.w);
    }], ['I', 73, 255, k => k.V(k.w / 2, 0, CAP)], ['J', 74, 490, k => {
      const r = (k.w - k.sw) / 2;
      k.V(k.w - k.h, r, CAP - r);
      k.arcRibbon(k.w / 2, r, r, r, 180, 340);
    }], ['K', 75, 610, k => {
      k.V(k.h, 0, CAP);
      k.seg(k.h, CAP * 0.46, k.w - k.h, CAP);
      k.seg(k.h, CAP * 0.46, k.w - k.h, 0);
    }], ['L', 76, 500, k => {
      k.V(k.h, 0, CAP);
      k.H(k.h, k.h, k.w - k.h);
    }], ['M', 77, 790, k => {
      k.V(k.h, 0, CAP);
      k.V(k.w - k.h, 0, CAP);
      k.seg(k.h, CAP, k.w / 2, CAP * 0.28);
      k.seg(k.w / 2, CAP * 0.28, k.w - k.h, CAP);
    }], ['N', 78, 670, k => {
      k.V(k.h, 0, CAP);
      k.V(k.w - k.h, 0, CAP);
      k.seg(k.h, CAP, k.w - k.h, 0);
    }], ['O', 79, 700, k => k.ring(k.w / 2, CAP / 2, (k.w - k.sw) / 2, (CAP - k.sw) / 2, k.sw)], ['P', 80, 610, k => {
      k.V(k.h, 0, CAP);
      k.bowl(k.sw, k.w, CAP * 0.47, CAP);
    }], ['Q', 81, 710, k => {
      k.ring(k.w / 2, CAP / 2, (k.w - k.sw) / 2, (CAP - k.sw) / 2, k.sw);
      k.seg(k.w * 0.62, CAP * 0.30, k.w * 0.94, CAP * 0.03, k.sw * 0.85);
    }], ['R', 82, 630, k => {
      k.V(k.h, 0, CAP);
      k.bowl(k.sw, k.w - k.sw * 0.3, CAP * 0.47, CAP);
      k.seg(k.w * 0.42, CAP * 0.49, k.w - k.h, 0);
    }], ['S', 83, 600, k => {
      const rx = (k.w - k.sw) / 2,
        ry = CAP / 4;
      // top bowl: aperture at lower-right — bottom bowl: aperture at upper-left
      k.arcRibbon(k.w / 2, CAP - ry, rx, ry, 30, 270);
      k.arcRibbon(k.w / 2, ry, rx, ry, 90, -180);
    }], ['T', 84, 570, k => {
      k.H(0, CAP - k.h, k.w);
      k.V(k.w / 2, 0, CAP - k.sw);
    }], ['U', 85, 660, k => {
      const r = (k.w - k.sw) / 2;
      k.V(k.h, r, CAP - r);
      k.V(k.w - k.h, r, CAP - r);
      k.arcRibbon(k.w / 2, r, r, r, 180, 360);
    }], ['V', 86, 660, k => {
      k.seg(k.h, CAP, k.w / 2, 0);
      k.seg(k.w / 2, 0, k.w - k.h, CAP);
    }], ['W', 87, 910, k => {
      k.seg(k.h, CAP, k.w * 0.26, 0);
      k.seg(k.w * 0.26, 0, k.w / 2, CAP * 0.62);
      k.seg(k.w / 2, CAP * 0.62, k.w * 0.74, 0);
      k.seg(k.w * 0.74, 0, k.w - k.h, CAP);
    }], ['X', 88, 640, k => {
      k.seg(k.h, 0, k.w - k.h, CAP);
      k.seg(k.h, CAP, k.w - k.h, 0);
    }], ['Y', 89, 640, k => {
      k.seg(k.h, CAP, k.w / 2, CAP * 0.44);
      k.seg(k.w / 2, CAP * 0.44, k.w - k.h, CAP);
      k.V(k.w / 2, 0, CAP * 0.44);
    }], ['Z', 90, 600, k => {
      k.H(0, CAP - k.h, k.w);
      k.H(0, k.h, k.w);
      k.seg(k.w - k.h, CAP - k.sw, k.h, k.sw);
    }]];
  }
  function digitTable() {
    return [['zero', 48, 580, k => k.ring(k.w / 2, CAP / 2, (k.w - k.sw) / 2, (CAP - k.sw) / 2, k.sw)], ['one', 49, 390, k => {
      k.V(k.w / 2, 0, CAP);
      k.seg(k.h, CAP * 0.78, k.w / 2, CAP);
      k.H(k.h, k.h, k.w - k.h);
    }], ['two', 50, 570, k => {
      const r = (k.w - k.sw) / 2;
      k.arcRibbon(k.w / 2, CAP - r, r, r, 0, 190);
      k.seg(k.w - k.h, CAP - r, k.h, k.sw * 1.2);
      k.H(0, k.h, k.w);
    }], ['three', 51, 560, k => {
      const ry = CAP / 4,
        rx = (k.w - k.sw) * 0.5;
      k.arcRibbon(k.w * 0.42, CAP - ry, rx, ry, -95, 150);
      k.arcRibbon(k.w * 0.42, ry, rx, ry, -150, 95);
    }], ['four', 52, 580, k => {
      k.V(k.w - k.h - k.sw * 0.75, 0, CAP);
      k.H(k.h, CAP * 0.30, k.w - k.h);
      k.seg(k.h, CAP * 0.30, k.w - k.h - k.sw * 0.75, CAP);
    }], ['five', 53, 560, k => {
      k.H(k.h, CAP - k.h, k.w - k.h);
      k.V(k.h, CAP * 0.52, CAP * 0.48 - k.h);
      const ry = CAP * 0.27,
        rx = (k.w - k.sw) / 2;
      k.arcRibbon(k.w / 2, ry, rx, ry, -150, 100);
      k.H(k.h, CAP * 0.52, k.w * 0.44);
    }], ['six', 54, 580, k => {
      const ry = CAP * 0.28,
        rx = (k.w - k.sw) / 2;
      k.ring(k.w / 2, ry, rx, ry, k.sw);
      k.arcRibbon(k.w / 2, ry, rx, CAP - ry, 95, 175);
    }], ['seven', 55, 540, k => {
      k.H(0, CAP - k.h, k.w);
      k.seg(k.w - k.h, CAP - k.sw, k.h + k.sw * 0.5, 0);
    }], ['eight', 56, 570, k => {
      const ry = CAP * 0.28;
      k.ring(k.w / 2, CAP - ry, (k.w - k.sw) / 2 - 25, ry, k.sw);
      k.ring(k.w / 2, ry, (k.w - k.sw) / 2, ry, k.sw);
    }], ['nine', 57, 580, k => {
      const ry = CAP * 0.28,
        rx = (k.w - k.sw) / 2;
      k.ring(k.w / 2, CAP - ry, rx, ry, k.sw);
      k.arcRibbon(k.w / 2, CAP - ry, rx, CAP - ry, 275, 355);
    }]];
  }
  function punctTable() {
    return [['period', 46, 245, k => k.dot(k.w / 2, k.h + k.sw * 0.4, k.sw * 0.6)], ['comma', 44, 245, k => {
      k.dot(k.w / 2, k.h + k.sw * 0.4, k.sw * 0.6);
      k.seg(k.w / 2, k.h * 0.4, k.w / 2 - 35, -110, k.sw * 0.7);
    }], ['exclam', 33, 255, k => {
      k.fill(R(k.w / 2 - k.h, CAP * 0.26, k.sw, CAP * 0.74));
      k.dot(k.w / 2, k.h + k.sw * 0.4, k.sw * 0.6);
    }], ['question', 63, 490, k => {
      const r = (k.w - k.sw) / 2;
      k.arcRibbon(k.w / 2, CAP - r, r, r, -15, 200);
      k.fill(R(k.w / 2 - k.h, CAP * 0.30, k.sw, CAP - r - CAP * 0.30));
      k.dot(k.w / 2, k.h + k.sw * 0.4, k.sw * 0.6);
    }], ['hyphen', 45, 380, k => k.H(k.h, CAP * 0.42, k.w - k.h)], ['colon', 58, 255, k => {
      k.dot(k.w / 2, k.h + k.sw * 0.4, k.sw * 0.6);
      k.dot(k.w / 2, CAP * 0.46, k.sw * 0.6);
    }], ['semicolon', 59, 255, k => {
      k.dot(k.w / 2, CAP * 0.46, k.sw * 0.6);
      k.dot(k.w / 2, k.h + k.sw * 0.4, k.sw * 0.6);
      k.seg(k.w / 2, k.h * 0.4, k.w / 2 - 35, -110, k.sw * 0.7);
    }], ['quotesingle', 39, 215, k => k.fill(R(k.w / 2 - k.h, CAP - 235, k.sw, 235))], ['quotedbl', 34, 350, k => {
      k.fill(R(k.w * 0.32 - k.h, CAP - 235, k.sw, 235));
      k.fill(R(k.w * 0.68 - k.h, CAP - 235, k.sw, 235));
    }], ['parenleft', 40, 305, k => k.arcRibbon(k.w, CAP / 2, k.w * 0.82, CAP / 2 + 70, 128, 232)], ['parenright', 41, 305, k => k.arcRibbon(0, CAP / 2, k.w * 0.82, CAP / 2 + 70, -52, 52)], ['ampersand', 38, 700, k => {
      // Ribbon strokes only — no hole contours, so the leg can overlap freely
      // (a fill laid inside another contour's hole would cancel to nothing).
      const cx = k.w * 0.42,
        rx = k.w * 0.30,
        ry = CAP * 0.30,
        cy = CAP * 0.34;
      k.arcRibbon(cx, cy, rx, ry, 20, 300); // main bowl, open lower-right
      k.arcRibbon(cx, CAP * 0.76, k.w * 0.21, CAP * 0.17, -25, 205); // upper story
      const a = 300 * Math.PI / 180;
      k.seg(cx + rx * Math.cos(a), cy + ry * Math.sin(a), k.w - k.h, k.h * 1.3, k.sw * 0.85);
    }], ['at', 64, 730, k => {
      k.ring(k.w / 2, CAP / 2, (k.w - k.sw) / 2, (CAP - k.sw) / 2, k.sw * 0.8);
      k.ring(k.w / 2, CAP / 2, k.w * 0.20, CAP * 0.20, k.sw * 0.8);
    }],
    // typographic punctuation — without these, curly quotes and dashes fall back
    // to another family mid-word and the text renders in two fonts.
    ['quoteleft', 0x2018, 215, k => k.seg(k.w / 2 - k.sw * 0.18, CAP - 235, k.w / 2 + k.sw * 0.18, CAP, k.sw)], ['quoteright', 0x2019, 215, k => k.seg(k.w / 2 + k.sw * 0.18, CAP - 235, k.w / 2 - k.sw * 0.18, CAP, k.sw)], ['quotedblleft', 0x201C, 350, k => {
      k.seg(k.w * 0.32 - k.sw * 0.18, CAP - 235, k.w * 0.32 + k.sw * 0.18, CAP, k.sw);
      k.seg(k.w * 0.68 - k.sw * 0.18, CAP - 235, k.w * 0.68 + k.sw * 0.18, CAP, k.sw);
    }], ['quotedblright', 0x201D, 350, k => {
      k.seg(k.w * 0.32 + k.sw * 0.18, CAP - 235, k.w * 0.32 - k.sw * 0.18, CAP, k.sw);
      k.seg(k.w * 0.68 + k.sw * 0.18, CAP - 235, k.w * 0.68 - k.sw * 0.18, CAP, k.sw);
    }], ['endash', 0x2013, 480, k => k.H(k.h, CAP * 0.42, k.w - k.sw)], ['emdash', 0x2014, 700, k => k.H(0, CAP * 0.42, k.w)]];
  }
  const XH = 500,
    ASCH = 725,
    DSCH = -190;

  // ─── lowercase (AB Sans only — AB Marquee is an all-caps display face) ─────
  function lowerTable() {
    return [['a', 97, 540, k => {
      k.V(k.w - k.h, 0, XH);
      k.bowlM(k.w - k.sw, 0, 0, XH * 0.68);
    }], ['b', 98, 555, k => {
      k.V(k.h, 0, ASCH);
      k.bowl(k.sw, k.w, 0, XH);
    }], ['c', 99, 520, k => k.arcRibbon(k.w / 2, XH / 2, (k.w - k.sw) / 2, (XH - k.sw) / 2, 55, 305)], ['d', 100, 555, k => {
      k.V(k.w - k.h, 0, ASCH);
      k.bowlM(k.w - k.sw, 0, 0, XH);
    }], ['e', 101, 530, k => {
      k.arcRibbon(k.w / 2, XH / 2, (k.w - k.sw) / 2, (XH - k.sw) / 2, 0, 312);
      k.H(k.h, XH / 2, k.w - k.sw * 0.7);
    }], ['f', 102, 360, k => {
      k.V(k.w * 0.66, 0, ASCH - k.sw * 0.9);
      k.arcRibbon(k.w * 0.30, ASCH - k.sw * 0.9, k.w * 0.36, k.sw * 0.9, 0, 95);
      k.H(0, XH, k.w);
    }], ['g', 103, 555, k => {
      const r = (k.w - k.sw) / 2;
      k.ring(k.w / 2, XH / 2, r, (XH - k.sw) / 2, k.sw);
      k.V(k.w - k.h, DSCH + r * 0.9, XH / 2);
      k.arcRibbon(k.w / 2, DSCH + r * 0.9, r, r * 0.9, 182, 340);
    }], ['h', 104, 555, k => {
      const r = (k.w - k.sw) / 2;
      k.V(k.h, 0, ASCH);
      k.V(k.w - k.h, 0, XH - r);
      k.arcRibbon(k.w / 2, XH - r, r, r, 0, 180);
    }], ['i', 105, 240, k => {
      k.V(k.w / 2, 0, XH);
      k.dot(k.w / 2, XH + k.sw * 1.25, k.sw * 0.6);
    }], ['j', 106, 270, k => {
      const r = k.w * 0.42;
      k.V(k.w - k.h - k.sw * 0.1, DSCH + r, XH - DSCH - r);
      k.arcRibbon(k.w * 0.34, DSCH + r, r, r, 196, 344);
      k.dot(k.w - k.h - k.sw * 0.1, XH + k.sw * 1.25, k.sw * 0.6);
    }], ['k', 107, 510, k => {
      k.V(k.h, 0, ASCH);
      k.seg(k.h, XH * 0.42, k.w - k.h, XH);
      k.seg(k.h, XH * 0.42, k.w - k.h, 0);
    }], ['l', 108, 240, k => k.V(k.w / 2, 0, ASCH)], ['m', 109, 820, k => {
      const r = (k.w / 2 - k.sw) / 2;
      k.V(k.h, 0, XH);
      k.V(k.w / 2, 0, XH - r);
      k.arcRibbon(k.w / 4 + k.h / 2, XH - r, r, r, 0, 180);
      k.V(k.w - k.h, 0, XH - r);
      k.arcRibbon(k.w * 0.75, XH - r, r, r, 0, 180);
    }], ['n', 110, 555, k => {
      const r = (k.w - k.sw) / 2;
      k.V(k.h, 0, XH);
      k.V(k.w - k.h, 0, XH - r);
      k.arcRibbon(k.w / 2, XH - r, r, r, 0, 180);
    }], ['o', 111, 560, k => k.ring(k.w / 2, XH / 2, (k.w - k.sw) / 2, (XH - k.sw) / 2, k.sw)], ['p', 112, 555, k => {
      k.V(k.h, DSCH, XH - DSCH);
      k.bowl(k.sw, k.w, 0, XH);
    }], ['q', 113, 555, k => {
      k.V(k.w - k.h, DSCH, XH - DSCH);
      k.bowlM(k.w - k.sw, 0, 0, XH);
    }], ['r', 114, 380, k => {
      const r = k.w * 0.5 - k.h;
      k.V(k.h, 0, XH);
      k.arcRibbon(k.h + r, XH - r, r, r, 10, 180);
    }], ['s', 115, 500, k => {
      const rx = (k.w - k.sw) / 2,
        ry = XH / 4;
      k.arcRibbon(k.w / 2, XH - ry, rx, ry, 30, 270);
      k.arcRibbon(k.w / 2, ry, rx, ry, 90, -180);
    }], ['t', 116, 370, k => {
      k.V(k.w * 0.42, 0, XH * 1.36);
      k.H(0, XH, k.w);
    }], ['u', 117, 555, k => {
      const r = (k.w - k.sw) / 2;
      k.V(k.h, r, XH - r);
      k.V(k.w - k.h, 0, XH);
      k.arcRibbon(k.w / 2, r, r, r, 180, 360);
    }], ['v', 118, 510, k => {
      k.seg(k.h, XH, k.w / 2, 0);
      k.seg(k.w / 2, 0, k.w - k.h, XH);
    }], ['w', 119, 760, k => {
      k.seg(k.h, XH, k.w * 0.27, 0);
      k.seg(k.w * 0.27, 0, k.w / 2, XH * 0.60);
      k.seg(k.w / 2, XH * 0.60, k.w * 0.73, 0);
      k.seg(k.w * 0.73, 0, k.w - k.h, XH);
    }], ['x', 120, 500, k => {
      k.seg(k.h, 0, k.w - k.h, XH);
      k.seg(k.h, XH, k.w - k.h, 0);
    }], ['y', 121, 510, k => {
      k.seg(k.h, XH, k.w * 0.54, 0);
      k.seg(k.w - k.h, XH, k.w * 0.22, DSCH);
    }], ['z', 122, 480, k => {
      k.H(0, XH - k.h, k.w);
      k.H(0, k.h, k.w);
      k.seg(k.w - k.h, XH - k.sw, k.h, k.sw);
    }]];
  }

  // ─── build one face ───────────────────────────────────────────────────────
  // opts: { sw, widen (width multiplier), bands:{c1,c2,cut}|null, apertureWiden }
  function buildFace(opts) {
    const g = [];
    g.push(new opentype.Glyph({
      name: '.notdef',
      unicode: 0,
      advanceWidth: 600,
      path: new opentype.Path()
    }));
    g.push(new opentype.Glyph({
      name: 'space',
      unicode: 32,
      advanceWidth: Math.round(280 * opts.widen),
      path: new opentype.Path()
    }));
    function glyph(name, code, baseW, draw) {
      const ctx = Ctx(opts.bands);
      const sw = opts.sw,
        h = sw / 2,
        w = baseW * opts.widen;
      const k = {
        w,
        sw,
        h,
        fill: ctx.fill,
        hole: ctx.hole,
        V: (x, y, ht) => ctx.fill(R(x - h, y, sw, ht)),
        H: (x, y, wd) => ctx.fill(R(x, y - h, wd, sw)),
        seg: (x1, y1, x2, y2, t) => {
          t = t || sw;
          const dx = x2 - x1,
            dy = y2 - y1,
            L = Math.hypot(dx, dy) || 1,
            nx = -dy / L * t / 2,
            ny = dx / L * t / 2;
          ctx.fill([[x1 + nx, y1 + ny], [x2 + nx, y2 + ny], [x2 - nx, y2 - ny], [x1 - nx, y1 - ny]]);
        },
        dot: (cx, cy, r) => ctx.fill(ellipsePts(cx, cy, r, r)),
        ring: (cx, cy, rxo, ryo, t) => {
          ctx.fill(ellipsePts(cx, cy, rxo, ryo));
          if (rxo - t > 3 && ryo - t > 3) ctx.hole(ellipsePts(cx, cy, rxo - t, ryo - t));
        },
        // bowl: flat left/top/bottom bars + rounded right arc. Counter is enclosed by
        // separate fill contours (winding 0), so no hole contour is needed at all.
        bowl: (stemX, right, yBot, yTop) => {
          const cy = (yBot + yTop) / 2;
          const ry = Math.max(sw * 0.35, (yTop - yBot) / 2 - sw / 2);
          const arcCx = Math.max(sw, right - sw / 2 - ry);
          const rx = Math.max(sw * 0.35, right - sw / 2 - arcCx);
          ctx.fill(R(0, yTop - sw, arcCx, sw));
          ctx.fill(R(0, yBot, arcCx, sw));
          ctx.ribbon(arc(arcCx, cy, rx + sw / 2, ry + sw / 2, -90, 90), arc(arcCx, cy, rx - sw / 2, ry - sw / 2, -90, 90));
        },
        // mirrored bowl: flat right, rounded left (for b/d/q counterparts)
        bowlM: (stemRight, left, yBot, yTop) => {
          const cy = (yBot + yTop) / 2;
          const ry = Math.max(sw * 0.35, (yTop - yBot) / 2 - sw / 2);
          const arcCx = Math.min(stemRight, left + sw / 2 + ry);
          const rx = Math.max(sw * 0.35, arcCx - left - sw / 2);
          ctx.fill(R(arcCx, yTop - sw, stemRight - arcCx + sw, sw));
          ctx.fill(R(arcCx, yBot, stemRight - arcCx + sw, sw));
          ctx.ribbon(arc(arcCx, cy, rx + sw / 2, ry + sw / 2, 90, 270), arc(arcCx, cy, rx - sw / 2, ry - sw / 2, 90, 270));
        },
        arcRibbon: (cx, cy, rx, ry, a0, a1) => ctx.ribbon(arc(cx, cy, rx + sw / 2, ry + sw / 2, a0, a1), arc(cx, cy, rx - sw / 2, ry - sw / 2, a0, a1)),
        // C/G aperture: open ring drawn as one continuous ribbon
        aperture: (a0, a1) => {
          const d = opts.apertureWiden || 0;
          const rx = (w - sw) / 2,
            ry = (CAP - sw) / 2;
          ctx.ribbon(arc(w / 2, CAP / 2, rx + sw / 2, ry + sw / 2, a0 + d, a1 - d), arc(w / 2, CAP / 2, rx - sw / 2, ry - sw / 2, a0 + d, a1 - d));
        }
      };
      draw(k);
      g.push(new opentype.Glyph({
        name,
        unicode: code,
        advanceWidth: Math.round(w + opts.sideBearing),
        path: ctx.path
      }));
    }
    const L = letterTable();
    for (const [ch, code, bw, draw] of L) glyph(ch, code, bw, draw);
    for (const [n, code, bw, draw] of digitTable()) glyph(n, code, bw, draw);
    for (const [n, code, bw, draw] of punctTable()) glyph(n, code, bw, draw);
    if (opts.lowercase) {
      for (const [n, code, bw, draw] of lowerTable()) glyph(n, code, bw, draw);
    } else {
      // all-caps display face: lowercase codepoints mirror the capitals
      for (let i = 0; i < 26; i++) {
        const [,, bw, draw] = L[i];
        glyph('uni' + (97 + i), 97 + i, bw, draw);
      }
    }
    return g;
  }
  const sansGlyphs = sw => buildFace({
    sw,
    widen: 1,
    bands: null,
    sideBearing: 70,
    lowercase: true
  });
  const marqueeGlyphs = sw => buildFace({
    sw,
    widen: 1.14,
    sideBearing: 95,
    apertureWiden: 8,
    lowercase: false,
    bands: {
      c1: CAP * 0.33,
      c2: CAP * 0.665,
      cut: Math.max(24, sw * 0.30)
    }
  });
  window.AB_FONT_GEN = {
    sansGlyphs,
    marqueeGlyphs,
    buildFace,
    UPM,
    CAP,
    ASC,
    DESC
  };
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "tools/build-fonts.js", error: String((e && e.message) || e) }); }

// ui_kits/website/events-grid.jsx
try { (() => {
// AB Entertainment — Events Grid Component
// EventsGrid.jsx

const EVENTS = [{
  id: 1,
  title: 'Arya Ambekar Live in Concert',
  category: 'Concert',
  date: 'Dec 14, 2025',
  venue: 'Palais Theatre, Melbourne',
  price: 45,
  image: '../../assets/events/arya-ambekar.jpg',
  status: 'available',
  desc: 'An enchanting evening of classical and contemporary Indian music with the celebrated vocalist.'
}, {
  id: 2,
  title: 'Shikayla Gelo Ek!',
  category: 'Theatre',
  date: 'Jan 18, 2026',
  venue: 'Arts Centre Melbourne',
  price: 55,
  image: '../../assets/events/shikayla-gelo-ek.jpg',
  status: 'selling_fast',
  desc: 'A hilarious comedy of errors — Marathi theatre at its most vibrant and entertaining best.'
}, {
  id: 3,
  title: 'Shrimant Damodar Pant',
  category: 'Theatre',
  date: 'Feb 22, 2026',
  venue: 'Regent Theatre, Melbourne',
  price: 60,
  image: '../../assets/events/shrimant-damodar-pant.jpg',
  status: 'available',
  desc: 'A timeless classic of Marathi stage reimagined for Melbourne audiences with world-class production.'
}, {
  id: 4,
  title: 'Diwali Spectacular 2026',
  category: 'Cultural',
  date: 'Oct 20, 2026',
  venue: 'Melbourne Convention Centre',
  price: 40,
  image: '../../assets/events/diwali-spectacular.jpg',
  status: 'available',
  desc: "Celebrate Diwali with Melbourne's most spectacular fusion of dance, music and cultural performance."
}];
const EventCard = ({
  event,
  onClick
}) => {
  const statusMap = {
    available: {
      label: 'On Sale Now',
      bg: '#22C55E',
      color: '#fff'
    },
    selling_fast: {
      label: 'Selling Fast',
      bg: '#F59E0B',
      color: '#000'
    },
    sold_out: {
      label: 'Sold Out',
      bg: '#DC2626',
      color: '#fff'
    }
  };
  const badge = statusMap[event.status];
  const [hov, setHov] = React.useState(false);
  return React.createElement('div', {
    onClick,
    onMouseEnter: () => setHov(true),
    onMouseLeave: () => setHov(false),
    style: {
      background: 'rgba(255,255,255,0.02)',
      backdropFilter: 'blur(12px)',
      WebkitBackdropFilter: 'blur(12px)',
      border: hov ? '1px solid rgba(var(--accent-rgb),0.25)' : '1px solid rgba(var(--accent-rgb),0.08)',
      boxShadow: hov ? '0 8px 32px rgba(0,0,0,0.4),0 0 0 1px rgba(var(--accent-rgb),0.1)' : 'none',
      transform: hov ? 'translateY(-4px)' : 'translateY(0)',
      transition: 'all 600ms cubic-bezier(0.25,1,0.5,1)',
      overflow: 'hidden',
      cursor: 'pointer',
      borderRadius: '0.75rem'
    }
  },
  // Image
  React.createElement('div', {
    style: {
      position: 'relative',
      height: '180px',
      overflow: 'hidden',
      background: '#111'
    }
  }, React.createElement('img', {
    src: event.image,
    alt: event.title,
    style: {
      width: '100%',
      height: '100%',
      objectFit: 'cover',
      display: 'block',
      filter: 'saturate(0.9) contrast(1.05)',
      transform: hov ? 'scale(1.08)' : 'scale(1)',
      transition: 'transform 700ms cubic-bezier(0.25,1,0.5,1)'
    }
  }), React.createElement('div', {
    style: {
      position: 'absolute',
      inset: 0,
      background: 'linear-gradient(to top,#0A0A0A,rgba(10,10,10,0.25) 60%,transparent)'
    }
  }),
  // Category badge
  React.createElement('div', {
    style: {
      position: 'absolute',
      top: 10,
      right: 10,
      padding: '4px 10px',
      background: 'linear-gradient(90deg,var(--accent),var(--accent-light))',
      color: '#000',
      fontSize: '9px',
      fontWeight: 700,
      letterSpacing: '0.08em',
      textTransform: 'uppercase'
    }
  }, event.category),
  // Status badge
  badge && React.createElement('div', {
    style: {
      position: 'absolute',
      top: 10,
      left: 10,
      padding: '4px 10px',
      background: badge.bg,
      color: badge.color,
      fontSize: '9px',
      fontWeight: 700,
      letterSpacing: '0.08em',
      textTransform: 'uppercase'
    }
  }, badge.label)),
  // Body
  React.createElement('div', {
    style: {
      padding: '20px'
    }
  }, React.createElement('h3', {
    style: {
      fontFamily: 'var(--font-display)',
      fontSize: '1rem',
      fontWeight: 700,
      lineHeight: 1.25,
      color: hov ? 'var(--accent)' : '#fff',
      margin: '0 0 8px',
      transition: 'color 400ms'
    }
  }, event.title), React.createElement('p', {
    style: {
      fontSize: '0.75rem',
      color: 'rgba(255,255,255,0.5)',
      lineHeight: 1.55,
      margin: '0 0 14px'
    }
  }, event.desc), React.createElement('div', {
    style: {
      borderTop: '1px solid rgba(var(--accent-rgb),0.08)',
      paddingTop: '14px'
    }
  }, React.createElement('div', {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: '8px',
      fontSize: '0.73rem',
      color: 'rgba(255,255,255,0.5)',
      marginBottom: '5px'
    }
  }, React.createElement('svg', {
    width: 12,
    height: 12,
    fill: 'none',
    stroke: 'rgba(var(--accent-rgb),0.5)',
    viewBox: '0 0 24 24',
    strokeWidth: 1.5
  }, React.createElement('path', {
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
    d: 'M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z'
  })), event.date), React.createElement('div', {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: '8px',
      fontSize: '0.73rem',
      color: 'rgba(255,255,255,0.5)',
      marginBottom: '10px'
    }
  }, React.createElement('svg', {
    width: 12,
    height: 12,
    fill: 'none',
    stroke: 'rgba(var(--accent-rgb),0.5)',
    viewBox: '0 0 24 24',
    strokeWidth: 1.5
  }, React.createElement('path', {
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
    d: 'M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0zM15 11a3 3 0 11-6 0 3 3 0 016 0z'
  })), event.venue), React.createElement('div', {
    style: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between'
    }
  }, React.createElement('span', {
    style: {
      fontFamily: 'var(--font-display)',
      fontSize: '0.85rem',
      fontWeight: 700,
      color: 'var(--accent)'
    }
  }, `From $${event.price} AUD`), React.createElement('svg', {
    width: 14,
    height: 14,
    fill: 'none',
    stroke: hov ? 'var(--accent)' : 'rgba(var(--accent-rgb),0.3)',
    viewBox: '0 0 24 24',
    strokeWidth: 1.5,
    style: {
      transform: hov ? 'translateX(4px)' : 'translateX(0)',
      transition: 'all 400ms'
    }
  }, React.createElement('path', {
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
    d: 'M9 5l7 7-7 7'
  }))))));
};
const EventsGrid = ({
  onNavigate
}) => {
  const categories = ['All Events', 'Theatre', 'Concert', 'Cultural'];
  const [active, setActive] = React.useState('All Events');
  const filtered = active === 'All Events' ? EVENTS : EVENTS.filter(e => e.category === active);
  return React.createElement('section', {
    style: {
      position: 'relative',
      padding: '112px 0',
      background: '#0A0A0A',
      overflow: 'hidden'
    }
  },
  // Ambient
  React.createElement('div', {
    style: {
      position: 'absolute',
      top: 0,
      right: 0,
      width: 500,
      height: 500,
      background: 'radial-gradient(ellipse,rgba(var(--accent-rgb),0.03),transparent 60%)',
      pointerEvents: 'none'
    }
  }), React.createElement('div', {
    style: {
      position: 'absolute',
      top: 0,
      left: 0,
      right: 0,
      height: 1,
      background: 'linear-gradient(90deg,transparent,rgba(var(--accent-rgb),0.2),transparent)'
    }
  }), React.createElement('div', {
    className: 'container-eu'
  },
  // Header
  React.createElement('div', {
    style: {
      textAlign: 'center',
      marginBottom: '32px'
    }
  }, React.createElement(SectionEyebrow, null, 'Our Productions'), React.createElement('h2', {
    style: {
      fontFamily: 'var(--font-display)',
      fontSize: 'clamp(2rem,4vw,3.5rem)',
      fontWeight: 700,
      color: '#fff',
      margin: '0 0 16px'
    }
  }, 'Signature ', React.createElement('span', {
    className: 'gold-shimmer'
  }, 'Events')), React.createElement('p', {
    style: {
      fontFamily: 'var(--font-body)',
      fontSize: '1rem',
      color: 'rgba(255,255,255,0.5)',
      maxWidth: 480,
      margin: '0 auto 20px'
    }
  }, 'From classical Marathi theatre to spectacular live concerts'), React.createElement(OrnamentDivider, null)),
  // Category filters
  React.createElement('div', {
    style: {
      display: 'flex',
      justifyContent: 'center',
      gap: '10px',
      marginBottom: '56px',
      flexWrap: 'wrap'
    }
  }, categories.map(cat => React.createElement('button', {
    key: cat,
    onClick: () => setActive(cat),
    style: {
      padding: '9px 22px',
      background: active === cat ? 'linear-gradient(90deg,var(--accent),var(--accent-light))' : 'transparent',
      border: active === cat ? '1px solid transparent' : '1px solid rgba(var(--accent-rgb),0.15)',
      color: active === cat ? '#000' : 'rgba(255,255,255,0.5)',
      fontFamily: 'var(--font-body)',
      fontSize: '0.68rem',
      fontWeight: 700,
      letterSpacing: '0.12em',
      textTransform: 'uppercase',
      cursor: 'pointer',
      boxShadow: active === cat ? '0 0 20px rgba(var(--accent-rgb),0.3)' : 'none',
      transition: 'all 400ms cubic-bezier(0.25,1,0.5,1)'
    }
  }, cat))),
  // Grid
  React.createElement('div', {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fill,minmax(260px,1fr))',
      gap: '24px'
    }
  }, filtered.map(event => React.createElement(EventCard, {
    key: event.id,
    event
  }))),
  // Bottom CTA
  React.createElement('div', {
    style: {
      textAlign: 'center',
      marginTop: '64px'
    }
  }, React.createElement(BtnPrimary, {
    onClick: () => onNavigate && onNavigate('Events')
  }, 'View All Events'))));
};
Object.assign(window, {
  EventsGrid
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/website/events-grid.jsx", error: String((e && e.message) || e) }); }

// ui_kits/website/footer.jsx
try { (() => {
// AB Entertainment — Footer Component
// Footer.jsx

const Footer = ({
  onNavigate
}) => {
  const [email, setEmail] = React.useState('');
  const [subscribed, setSubscribed] = React.useState(false);
  const year = new Date().getFullYear();
  const cols = {
    'Quick Links': [['Home', '/'], ['About', '/about'], ['Events', '/events'], ['Gallery', '/gallery'], ['Sponsors', '/sponsors'], ['Contact', '/contact']],
    'Events': [['Upcoming Events', '/events'], ['Past Events', '/events'], ['Gallery', '/gallery'], ['Sponsors', '/sponsors']],
    'Contact': [['(+61) 430082646', 'tel:'], ['abhi@abentertainment.com.au', 'mailto:'], ['Melbourne, VIC', '#']]
  };
  return React.createElement('footer', {
    style: {
      background: '#070707',
      borderTop: '1px solid rgba(var(--accent-rgb),0.08)',
      position: 'relative',
      overflow: 'hidden'
    }
  },
  // Ambient
  React.createElement('div', {
    style: {
      position: 'absolute',
      top: 0,
      left: '50%',
      transform: 'translateX(-50%)',
      width: 600,
      height: 200,
      background: 'radial-gradient(ellipse,rgba(var(--accent-rgb),0.03),transparent 70%)',
      pointerEvents: 'none'
    }
  }),
  // Newsletter
  React.createElement('div', {
    style: {
      borderBottom: '1px solid rgba(var(--accent-rgb),0.08)'
    }
  }, React.createElement('div', {
    className: 'container-eu',
    style: {
      padding: '48px 0'
    }
  }, React.createElement('div', {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 24
    }
  }, React.createElement('div', null, React.createElement('h3', {
    style: {
      fontFamily: 'var(--font-display)',
      fontSize: '1.2rem',
      fontWeight: 700,
      color: '#fff',
      margin: '0 0 4px'
    }
  }, 'Stay Updated'), React.createElement('p', {
    style: {
      fontFamily: 'var(--font-body)',
      fontSize: '0.82rem',
      color: 'rgba(255,255,255,0.5)',
      margin: 0
    }
  }, 'Get notified about upcoming events and exclusive offers.')), subscribed ? React.createElement('p', {
    style: {
      color: 'var(--accent)',
      fontFamily: 'var(--font-body)',
      fontSize: '0.85rem',
      fontWeight: 500
    }
  }, 'Thank you for subscribing!') : React.createElement('div', {
    style: {
      display: 'flex',
      gap: 10
    }
  }, React.createElement('input', {
    type: 'email',
    value: email,
    onChange: e => setEmail(e.target.value),
    placeholder: 'Enter your email',
    style: {
      padding: '11px 16px',
      background: 'rgba(255,255,255,0.05)',
      border: '1px solid rgba(var(--accent-rgb),0.2)',
      color: '#fff',
      fontFamily: 'var(--font-body)',
      fontSize: '0.82rem',
      outline: 'none',
      width: 240
    }
  }), React.createElement('button', {
    onClick: () => {
      if (email) setSubscribed(true);
    },
    style: {
      padding: '11px 22px',
      background: 'linear-gradient(90deg,var(--accent),var(--accent-light))',
      color: '#000',
      fontFamily: 'var(--font-body)',
      fontSize: '0.72rem',
      fontWeight: 700,
      letterSpacing: '0.1em',
      textTransform: 'uppercase',
      border: 'none',
      cursor: 'pointer'
    }
  }, 'Subscribe'))))),
  // CTA row
  React.createElement('div', {
    style: {
      borderBottom: '1px solid rgba(var(--accent-rgb),0.08)'
    }
  }, React.createElement('div', {
    className: 'container-eu',
    style: {
      padding: '64px 0'
    }
  }, React.createElement('div', {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 32
    }
  }, React.createElement('div', null, React.createElement('h3', {
    style: {
      fontFamily: 'var(--font-display)',
      fontSize: 'clamp(1.5rem,3vw,2.25rem)',
      fontWeight: 700,
      color: '#fff',
      margin: '0 0 8px'
    }
  }, 'Get in ', React.createElement('span', {
    className: 'gold-shimmer'
  }, 'Touch')), React.createElement('p', {
    style: {
      color: 'rgba(255,255,255,0.5)',
      fontFamily: 'var(--font-body)',
      fontSize: '0.85rem',
      margin: 0
    }
  }, "Have a question or want to collaborate? We'd love to hear from you.")), React.createElement('div', {
    style: {
      display: 'flex',
      gap: 12
    }
  }, React.createElement(BtnPrimary, {
    onClick: () => onNavigate && onNavigate('Contact')
  }, 'Contact Us'), React.createElement(BtnOutline, {
    style: {
      padding: '14px 28px'
    }
  }, 'Call Us'))))),
  // Main grid
  React.createElement('div', {
    className: 'container-eu',
    style: {
      padding: '72px 0'
    }
  }, React.createElement('div', {
    style: {
      display: 'grid',
      gridTemplateColumns: '1.4fr 1.8fr 1fr',
      gap: 48
    }
  },
  // Company info
  React.createElement('div', null, React.createElement('div', {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 12,
      marginBottom: 20
    }
  }, React.createElement('div', {
    style: {
      position: 'relative',
      width: 52,
      height: 52
    }
  }, React.createElement('div', {
    style: {
      position: 'absolute',
      inset: 0,
      background: 'rgba(var(--accent-rgb),0.05)',
      filter: 'blur(12px)',
      borderRadius: '50%'
    }
  }), React.createElement('img', {
    src: '../../assets/AB_Logo_transparent.png',
    alt: 'AB Entertainment',
    style: {
      width: 52,
      height: 52,
      objectFit: 'contain'
    }
  })), React.createElement('div', null, React.createElement('h2', {
    style: {
      fontFamily: 'var(--font-display)',
      fontSize: '1rem',
      fontWeight: 600,
      color: '#fff',
      margin: '0 0 2px'
    }
  }, 'AB Entertainment'), React.createElement('p', {
    style: {
      fontSize: '9px',
      letterSpacing: '0.15em',
      textTransform: 'uppercase',
      color: 'rgba(var(--accent-rgb),0.4)',
      margin: 0
    }
  }, 'Experience events like no other'))), React.createElement('p', {
    style: {
      color: 'rgba(255,255,255,0.55)',
      fontFamily: 'var(--font-body)',
      fontSize: '0.8rem',
      lineHeight: 1.8,
      marginBottom: 24
    }
  }, 'AB Entertainment where every detail is meticulously crafted to create unforgettable experiences. With a passion for perfection and a commitment to excellence.'),
  // Social
  React.createElement('div', {
    style: {
      display: 'flex',
      gap: 10
    }
  }, [{
    label: 'Instagram',
    path: 'M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zM12 0C8.741 0 8.333.014 7.053.072 2.695.272.273 2.69.073 7.052.014 8.333 0 8.741 0 12c0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98C8.333 23.986 8.741 24 12 24c3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98C15.668.014 15.259 0 12 0zm0 5.838a6.162 6.162 0 100 12.324 6.162 6.162 0 000-12.324zM12 16a4 4 0 110-8 4 4 0 010 8zm6.406-11.845a1.44 1.44 0 100 2.881 1.44 1.44 0 000-2.881z'
  }, {
    label: 'Facebook',
    path: 'M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z'
  }].map(s => React.createElement('div', {
    key: s.label,
    style: {
      width: 38,
      height: 38,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      border: '1px solid rgba(var(--accent-rgb),0.12)',
      color: 'rgba(var(--accent-rgb),0.4)',
      cursor: 'pointer',
      transition: 'all 400ms'
    },
    onMouseEnter: e => {
      e.currentTarget.style.background = 'linear-gradient(135deg,var(--accent),var(--accent-light))';
      e.currentTarget.style.color = '#000';
      e.currentTarget.style.borderColor = 'var(--accent)';
    },
    onMouseLeave: e => {
      e.currentTarget.style.background = 'transparent';
      e.currentTarget.style.color = 'rgba(var(--accent-rgb),0.4)';
      e.currentTarget.style.borderColor = 'rgba(var(--accent-rgb),0.12)';
    }
  }, React.createElement('svg', {
    width: 14,
    height: 14,
    fill: 'currentColor',
    viewBox: '0 0 24 24'
  }, React.createElement('path', {
    d: s.path
  })))))),
  // Link columns
  React.createElement('div', {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(3,1fr)',
      gap: 32
    }
  }, Object.entries(cols).map(([heading, links]) => React.createElement('div', {
    key: heading
  }, React.createElement('h3', {
    style: {
      fontFamily: 'var(--font-body)',
      fontSize: '0.65rem',
      fontWeight: 600,
      color: 'rgba(var(--accent-rgb),0.8)',
      letterSpacing: '0.25em',
      textTransform: 'uppercase',
      margin: '0 0 20px',
      paddingBottom: 10,
      borderBottom: '1px solid rgba(var(--accent-rgb),0.08)'
    }
  }, heading), React.createElement('ul', {
    style: {
      listStyle: 'none',
      margin: 0,
      padding: 0
    }
  }, links.map(([label, href]) => React.createElement('li', {
    key: label,
    style: {
      marginBottom: 12
    }
  }, React.createElement('a', {
    href: '#',
    onClick: e => {
      e.preventDefault();
    },
    style: {
      fontFamily: 'var(--font-body)',
      fontSize: '0.8rem',
      color: 'rgba(255,255,255,0.55)',
      textDecoration: 'none',
      transition: 'color 300ms'
    },
    onMouseEnter: e => {
      e.currentTarget.style.color = 'var(--accent)';
    },
    onMouseLeave: e => {
      e.currentTarget.style.color = 'rgba(255,255,255,0.55)';
    }
  }, label))))))),
  // Sitemap
  React.createElement('div', null, React.createElement('h3', {
    style: {
      fontFamily: 'var(--font-body)',
      fontSize: '0.65rem',
      fontWeight: 600,
      color: 'rgba(var(--accent-rgb),0.8)',
      letterSpacing: '0.25em',
      textTransform: 'uppercase',
      margin: '0 0 20px',
      paddingBottom: 10,
      borderBottom: '1px solid rgba(var(--accent-rgb),0.08)'
    }
  }, 'Sitemap'), React.createElement('ul', {
    style: {
      listStyle: 'none',
      margin: 0,
      padding: 0
    }
  }, ['Home', 'About', 'Events', 'Gallery', 'Sponsors', 'Contact', 'Privacy Policy', 'Terms of Service'].map(l => React.createElement('li', {
    key: l,
    style: {
      marginBottom: 12
    }
  }, React.createElement('a', {
    href: '#',
    style: {
      fontFamily: 'var(--font-body)',
      fontSize: '0.8rem',
      color: 'rgba(255,255,255,0.55)',
      textDecoration: 'none',
      transition: 'color 300ms'
    },
    onMouseEnter: e => {
      e.currentTarget.style.color = 'var(--accent)';
    },
    onMouseLeave: e => {
      e.currentTarget.style.color = 'rgba(255,255,255,0.55)';
    }
  }, l))))))),
  // Copyright
  React.createElement('div', {
    style: {
      borderTop: '1px solid rgba(var(--accent-rgb),0.06)'
    }
  }, React.createElement('div', {
    className: 'container-eu',
    style: {
      padding: '24px 0',
      display: 'flex',
      flexWrap: 'wrap',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 16
    }
  }, React.createElement('p', {
    style: {
      fontFamily: 'var(--font-body)',
      fontSize: '0.72rem',
      color: 'rgba(255,255,255,0.4)',
      margin: 0
    }
  }, `© ${year} AB Entertainment. All rights reserved.`), React.createElement('div', {
    style: {
      display: 'flex',
      gap: 16,
      alignItems: 'center'
    }
  }, ['Privacy Policy', 'Terms of Service'].map((l, i) => React.createElement(React.Fragment, {
    key: l
  }, i > 0 && React.createElement('span', {
    style: {
      color: 'rgba(255,255,255,0.3)',
      fontSize: '0.72rem'
    }
  }, '|'), React.createElement('a', {
    href: '#',
    style: {
      fontFamily: 'var(--font-body)',
      fontSize: '0.72rem',
      color: 'rgba(255,255,255,0.4)',
      textDecoration: 'none',
      transition: 'color 300ms'
    },
    onMouseEnter: e => e.currentTarget.style.color = 'var(--accent)',
    onMouseLeave: e => e.currentTarget.style.color = 'rgba(255,255,255,0.4)'
  }, l)))), React.createElement('p', {
    style: {
      fontFamily: 'var(--font-body)',
      fontSize: '0.72rem',
      color: 'rgba(255,255,255,0.35)',
      margin: 0
    }
  }, 'Created by Vikram Deshpande'))));
};
Object.assign(window, {
  Footer
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/website/footer.jsx", error: String((e && e.message) || e) }); }

// ui_kits/website/hero-section.jsx
try { (() => {
// AB Entertainment — Hero Section
// HeroSection.jsx

const slides = [{
  badge: 'Welcome to',
  title: 'AB ENTERTAINMENT',
  sub: "Melbourne's Legendary Indian & Marathi Performing Arts Experience",
  bg: '../../assets/hero-bg.jpg'
}, {
  badge: 'Celebrating',
  title: 'CULTURAL EXCELLENCE',
  sub: 'Indian & Marathi Performing Arts in Melbourne',
  bg: '../../assets/hero-bg-2.jpg'
}, {
  badge: 'Discover',
  title: 'UNFORGETTABLE MOMENTS',
  sub: '6+ Events · 25+ Team · 25,000+ Audience Reach',
  bg: '../../assets/hero-bg.jpg'
}];
const HeroSection = ({
  onNavigate,
  autoplay = true,
  slideMs = 7000
}) => {
  const [current, setCurrent] = React.useState(0);
  const [fade, setFade] = React.useState(true);
  React.useEffect(() => {
    if (!autoplay) return;
    const t = setInterval(() => {
      setFade(false);
      setTimeout(() => {
        setCurrent(c => (c + 1) % slides.length);
        setFade(true);
      }, 400);
    }, slideMs);
    return () => clearInterval(t);
  }, [autoplay, slideMs]);
  const slide = slides[current];
  return React.createElement('section', {
    style: {
      position: 'relative',
      width: '100%',
      height: '100vh',
      overflow: 'hidden',
      background: '#000',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center'
    }
  },
  // BG Image
  React.createElement('div', {
    style: {
      position: 'absolute',
      inset: 0,
      opacity: fade ? 1 : 0,
      transition: 'opacity 800ms cubic-bezier(0.25,1,0.5,1)'
    }
  }, React.createElement('img', {
    src: slide.bg,
    alt: '',
    'aria-hidden': 'true',
    style: {
      width: '100%',
      height: '115%',
      objectFit: 'cover',
      filter: 'saturate(0.85) contrast(1.1)'
    }
  })),
  // Cinematic overlays
  React.createElement('div', {
    style: {
      position: 'absolute',
      inset: 0,
      background: 'linear-gradient(180deg,rgba(0,0,0,0.65) 0%,rgba(0,0,0,0.35) 50%,rgba(0,0,0,0.85) 100%)',
      zIndex: 1
    }
  }), React.createElement('div', {
    style: {
      position: 'absolute',
      inset: 0,
      background: 'linear-gradient(90deg,rgba(0,0,0,0.45),transparent,rgba(0,0,0,0.45))',
      zIndex: 1
    }
  }), React.createElement('div', {
    style: {
      position: 'absolute',
      inset: 0,
      background: 'radial-gradient(ellipse at 50% 50%,transparent 30%,rgba(0,0,0,0.65) 100%)',
      zIndex: 2
    }
  }), React.createElement('div', {
    style: {
      position: 'absolute',
      inset: 0,
      background: 'radial-gradient(ellipse at 50% 80%,rgba(var(--accent-rgb),0.04),transparent 60%)',
      zIndex: 2
    }
  }),
  // Content
  React.createElement('div', {
    style: {
      position: 'relative',
      zIndex: 10,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      textAlign: 'center',
      padding: '0 24px',
      opacity: fade ? 1 : 0,
      transition: 'opacity 500ms cubic-bezier(0.25,1,0.5,1)'
    }
  },
  // Logo
  React.createElement('div', {
    style: {
      position: 'relative',
      marginBottom: '36px'
    }
  }, React.createElement('div', {
    style: {
      position: 'absolute',
      inset: 0,
      borderRadius: '50%',
      background: 'rgba(var(--accent-rgb),0.1)',
      filter: 'blur(24px)'
    }
  }), React.createElement('img', {
    src: '../../assets/AB_Logo_transparent.png',
    alt: 'AB Entertainment',
    style: {
      width: 120,
      height: 120,
      objectFit: 'contain',
      filter: 'drop-shadow(0 0 30px rgba(var(--accent-rgb),0.4))'
    }
  })),
  // Badge
  React.createElement('div', {
    style: {
      marginBottom: '20px',
      display: 'inline-block',
      padding: '10px 24px',
      background: 'linear-gradient(90deg,rgba(var(--accent-rgb),0.1),rgba(var(--accent-rgb),0.2),rgba(var(--accent-rgb),0.1))',
      border: '1px solid rgba(var(--accent-rgb),0.25)',
      fontFamily: 'var(--font-body)',
      fontSize: '0.78rem',
      fontWeight: 500,
      letterSpacing: '0.2em',
      textTransform: 'uppercase',
      color: 'var(--accent)',
      backdropFilter: 'blur(8px)'
    }
  }, slide.badge),
  // Title
  React.createElement('h1', {
    className: 'gold-shimmer',
    style: {
      fontFamily: 'var(--font-display)',
      fontSize: 'clamp(3rem,7vw,7rem)',
      fontWeight: 900,
      lineHeight: 0.88,
      letterSpacing: '-0.025em',
      textTransform: 'uppercase',
      margin: '0 0 24px',
      maxWidth: '900px'
    }
  }, slide.title),
  // Ornament
  React.createElement('div', {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: '12px',
      marginBottom: '24px'
    }
  }, React.createElement('div', {
    style: {
      width: 64,
      height: 1,
      background: 'linear-gradient(90deg,transparent,rgba(var(--accent-rgb),0.5))'
    }
  }), React.createElement('div', {
    style: {
      width: 6,
      height: 6,
      transform: 'rotate(45deg)',
      background: 'rgba(var(--accent-rgb),0.6)'
    }
  }), React.createElement('div', {
    style: {
      width: 64,
      height: 1,
      background: 'linear-gradient(90deg,rgba(var(--accent-rgb),0.5),transparent)'
    }
  })),
  // Subtitle
  React.createElement('p', {
    style: {
      fontFamily: 'var(--font-body)',
      fontSize: 'clamp(1rem,1.5vw,1.25rem)',
      fontWeight: 300,
      color: 'rgba(255,255,255,0.7)',
      letterSpacing: '0.02em',
      maxWidth: '560px',
      lineHeight: 1.6,
      margin: '0 0 40px'
    }
  }, slide.sub),
  // CTAs
  React.createElement('div', {
    style: {
      display: 'flex',
      gap: '16px',
      flexWrap: 'wrap',
      justifyContent: 'center',
      marginBottom: '48px'
    }
  }, React.createElement(BtnPrimary, {
    onClick: () => onNavigate && onNavigate('Events')
  }, 'Buy Tickets'), React.createElement(BtnOutline, {
    onClick: () => onNavigate && onNavigate('Contact')
  }, 'Contact Us')),
  // Slide dots
  React.createElement('div', {
    style: {
      display: 'flex',
      gap: '10px',
      alignItems: 'center'
    }
  }, slides.map((_, i) => React.createElement('button', {
    key: i,
    onClick: () => setCurrent(i),
    style: {
      height: '2px',
      border: 'none',
      cursor: 'pointer',
      padding: 0,
      background: i === current ? 'rgba(var(--accent-rgb),0.3)' : 'rgba(255,255,255,0.5)',
      width: i === current ? '48px' : '12px',
      transition: 'all 600ms cubic-bezier(0.25,1,0.5,1)',
      position: 'relative',
      overflow: 'hidden'
    }
  }, i === current && React.createElement('div', {
    style: {
      position: 'absolute',
      inset: 0,
      background: 'var(--accent)',
      animation: 'slideProgress 7s linear forwards'
    }
  }))))),
  // Scroll indicator
  React.createElement('div', {
    style: {
      position: 'absolute',
      bottom: 32,
      left: '50%',
      transform: 'translateX(-50%)',
      zIndex: 20,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      gap: '8px',
      animation: 'scrollBounce 2.5s ease-in-out infinite'
    }
  }, React.createElement('span', {
    style: {
      fontFamily: 'var(--font-body)',
      fontSize: '8px',
      letterSpacing: '0.3em',
      textTransform: 'uppercase',
      color: 'rgba(var(--accent-rgb),0.7)'
    }
  }, 'Scroll'), React.createElement('div', {
    style: {
      width: '1px',
      height: '32px',
      background: 'linear-gradient(180deg,rgba(var(--accent-rgb),0.4),var(--accent))'
    }
  })),
  // Bottom fade
  React.createElement('div', {
    style: {
      position: 'absolute',
      bottom: 0,
      left: 0,
      right: 0,
      height: '120px',
      background: 'linear-gradient(transparent,#0A0A0A)',
      zIndex: 15,
      pointerEvents: 'none'
    }
  }));
};
Object.assign(window, {
  HeroSection
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/website/hero-section.jsx", error: String((e && e.message) || e) }); }

// ui_kits/website/navigation.jsx
try { (() => {
// AB Entertainment — Navigation Component
// Navigation.jsx

const Navigation = ({
  activePage,
  onNavigate
}) => {
  const [scrolled, setScrolled] = React.useState(false);
  const [menuOpen, setMenuOpen] = React.useState(false);
  React.useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 40);
    window.addEventListener('scroll', onScroll);
    return () => window.removeEventListener('scroll', onScroll);
  }, []);
  const links = ['Home', 'About', 'Events', 'Gallery', 'Sponsors', 'Contact'];
  const navStyle = {
    position: 'fixed',
    top: 0,
    left: 0,
    right: 0,
    zIndex: 40,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '14px 6%',
    background: scrolled ? 'rgba(0,0,0,0.92)' : 'rgba(0,0,0,0)',
    backdropFilter: scrolled ? 'blur(24px)' : 'blur(0px)',
    WebkitBackdropFilter: scrolled ? 'blur(24px)' : 'blur(0px)',
    borderBottom: scrolled ? '1px solid rgba(var(--accent-rgb),0.1)' : '1px solid transparent',
    transition: 'all 500ms cubic-bezier(0.25,1,0.5,1)'
  };
  return React.createElement(React.Fragment, null, React.createElement('nav', {
    style: navStyle
  },
  // Logo
  React.createElement('div', {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: '10px',
      cursor: 'pointer'
    },
    onClick: () => onNavigate && onNavigate('Home')
  }, React.createElement('img', {
    src: '../../assets/AB_Logo_transparent.png',
    alt: 'AB Entertainment',
    style: {
      width: 40,
      height: 40,
      objectFit: 'contain',
      filter: 'drop-shadow(0 0 8px rgba(var(--accent-rgb),0.3))'
    }
  }), React.createElement('div', {
    style: {
      display: 'flex',
      flexDirection: 'column'
    }
  }, React.createElement('span', {
    style: {
      fontFamily: 'var(--font-body)',
      fontSize: '10px',
      fontWeight: 600,
      letterSpacing: '0.22em',
      textTransform: 'uppercase',
      color: '#fff',
      lineHeight: 1.2
    }
  }, 'AB Entertainment'), React.createElement('span', {
    style: {
      fontSize: '8px',
      letterSpacing: '0.18em',
      textTransform: 'uppercase',
      color: 'rgba(var(--accent-rgb),0.45)'
    }
  }, 'Experience events like no other'))),
  // Desktop links
  React.createElement('div', {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: '32px'
    }
  }, links.map(l => React.createElement('a', {
    key: l,
    href: '#',
    onClick: e => {
      e.preventDefault();
      onNavigate && onNavigate(l);
    },
    style: {
      fontFamily: 'var(--font-body)',
      fontSize: '0.68rem',
      fontWeight: 500,
      letterSpacing: '0.05em',
      textTransform: 'uppercase',
      textDecoration: 'none',
      color: activePage === l ? 'var(--accent)' : 'rgba(255,255,255,0.6)',
      position: 'relative',
      paddingBottom: '4px',
      transition: 'color 300ms'
    }
  }, l, activePage === l && React.createElement('div', {
    style: {
      position: 'absolute',
      bottom: 0,
      left: 0,
      right: 0,
      height: '2px',
      background: 'linear-gradient(90deg,rgba(var(--accent-rgb),0.4),var(--accent),rgba(var(--accent-rgb),0.4))'
    }
  })))),
  // CTA
  React.createElement('div', {
    onClick: () => onNavigate && onNavigate('Contact'),
    style: {
      padding: '9px 22px',
      background: 'linear-gradient(90deg,var(--accent),var(--accent-light))',
      color: '#000',
      fontFamily: 'var(--font-body)',
      fontSize: '0.65rem',
      fontWeight: 700,
      letterSpacing: '0.12em',
      textTransform: 'uppercase',
      cursor: 'pointer'
    }
  }, 'Contact Us')));
};
Object.assign(window, {
  Navigation
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/website/navigation.jsx", error: String((e && e.message) || e) }); }

// ui_kits/website/shared.jsx
try { (() => {
// AB Entertainment — Shared UI Primitives
// Shared.jsx

const OrnamentDivider = () => React.createElement('div', {
  style: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '12px',
    margin: '0 auto'
  }
}, React.createElement('div', {
  style: {
    width: '64px',
    height: '1px',
    background: 'linear-gradient(90deg,transparent,rgba(var(--accent-rgb),0.4))'
  }
}), React.createElement('div', {
  style: {
    width: '8px',
    height: '8px',
    transform: 'rotate(45deg)',
    border: '1px solid rgba(var(--accent-rgb),0.5)'
  }
}), React.createElement('div', {
  style: {
    width: '64px',
    height: '1px',
    background: 'linear-gradient(90deg,rgba(var(--accent-rgb),0.4),transparent)'
  }
}));
const SectionEyebrow = ({
  children
}) => React.createElement('span', {
  style: {
    display: 'block',
    fontFamily: 'var(--font-body)',
    fontSize: '0.7rem',
    fontWeight: 600,
    letterSpacing: '0.25em',
    textTransform: 'uppercase',
    color: 'var(--accent)',
    marginBottom: '20px'
  }
}, children);
const SectionHeading = ({
  children,
  gold
}) => React.createElement('h2', {
  style: {
    fontFamily: 'var(--font-display)',
    fontSize: 'clamp(2rem,4vw,3.5rem)',
    fontWeight: 700,
    color: '#fff',
    lineHeight: 1.1,
    margin: '0 0 24px'
  }
}, typeof children === 'string' ? children : React.createElement(React.Fragment, null, gold ? React.createElement(React.Fragment, null, children[0], React.createElement('span', {
  className: 'gold-shimmer'
}, gold)) : children));
const StatusBadge = ({
  status
}) => {
  const map = {
    available: {
      label: 'On Sale Now',
      bg: '#22C55E',
      color: '#fff'
    },
    selling_fast: {
      label: 'Selling Fast',
      bg: '#F59E0B',
      color: '#000'
    },
    sold_out: {
      label: 'Sold Out',
      bg: '#DC2626',
      color: '#fff'
    },
    new_date: {
      label: 'New Date Added',
      bg: 'var(--accent)',
      color: '#000'
    }
  };
  const s = map[status];
  if (!s) return null;
  return React.createElement('div', {
    style: {
      position: 'absolute',
      top: 12,
      left: 12,
      padding: '4px 8px',
      background: s.bg,
      color: s.color,
      fontSize: '9px',
      fontWeight: 700,
      letterSpacing: '0.08em',
      textTransform: 'uppercase'
    }
  }, s.label);
};
const GlassCard = ({
  children,
  style,
  onClick
}) => React.createElement('div', {
  onClick,
  style: {
    background: 'rgba(255,255,255,0.02)',
    backdropFilter: 'blur(12px)',
    WebkitBackdropFilter: 'blur(12px)',
    border: '1px solid rgba(var(--accent-rgb),0.08)',
    transition: 'all 600ms cubic-bezier(0.25,1,0.5,1)',
    cursor: onClick ? 'pointer' : 'default',
    ...style
  },
  onMouseEnter: e => {
    e.currentTarget.style.background = 'rgba(255,255,255,0.04)';
    e.currentTarget.style.borderColor = 'rgba(var(--accent-rgb),0.25)';
    e.currentTarget.style.boxShadow = '0 8px 32px rgba(0,0,0,0.4),0 0 0 1px rgba(var(--accent-rgb),0.1)';
    e.currentTarget.style.transform = 'translateY(-4px)';
  },
  onMouseLeave: e => {
    e.currentTarget.style.background = 'rgba(255,255,255,0.02)';
    e.currentTarget.style.borderColor = 'rgba(var(--accent-rgb),0.08)';
    e.currentTarget.style.boxShadow = 'none';
    e.currentTarget.style.transform = 'translateY(0)';
  }
}, children);
const BtnPrimary = ({
  children,
  onClick,
  style
}) => {
  const [hov, setHov] = React.useState(false);
  return React.createElement('button', {
    onClick,
    style: {
      position: 'relative',
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '14px 40px',
      background: hov ? 'linear-gradient(135deg,var(--accent-light),var(--accent-pale) 50%,var(--accent-light))' : 'linear-gradient(135deg,var(--accent),var(--accent-light) 50%,var(--accent))',
      color: '#000',
      fontFamily: 'var(--font-body)',
      fontSize: '0.72rem',
      fontWeight: 700,
      letterSpacing: '0.12em',
      textTransform: 'uppercase',
      border: 'none',
      cursor: 'pointer',
      overflow: 'hidden',
      boxShadow: hov ? '0 0 40px rgba(var(--accent-rgb),0.4)' : 'none',
      transform: hov ? 'translateY(-1px)' : 'none',
      transition: 'all 400ms cubic-bezier(0.25,1,0.5,1)',
      ...style
    },
    onMouseEnter: () => setHov(true),
    onMouseLeave: () => setHov(false)
  }, children);
};
const BtnOutline = ({
  children,
  onClick,
  style
}) => {
  const [hov, setHov] = React.useState(false);
  return React.createElement('button', {
    onClick,
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '14px 40px',
      border: hov ? '1px solid var(--accent)' : '1px solid rgba(var(--accent-rgb),0.25)',
      background: hov ? 'var(--accent)' : 'transparent',
      color: hov ? '#000' : 'var(--accent)',
      fontFamily: 'var(--font-body)',
      fontSize: '0.72rem',
      fontWeight: 700,
      letterSpacing: '0.12em',
      textTransform: 'uppercase',
      cursor: 'pointer',
      backdropFilter: 'blur(4px)',
      boxShadow: hov ? '0 0 20px rgba(var(--accent-rgb),0.3)' : 'none',
      transition: 'all 400ms cubic-bezier(0.25,1,0.5,1)',
      ...style
    },
    onMouseEnter: () => setHov(true),
    onMouseLeave: () => setHov(false)
  }, children);
};
Object.assign(window, {
  OrnamentDivider,
  SectionEyebrow,
  SectionHeading,
  StatusBadge,
  GlassCard,
  BtnPrimary,
  BtnOutline
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/website/shared.jsx", error: String((e && e.message) || e) }); }

// ui_kits/website/testimonials.jsx
try { (() => {
// AB Entertainment — Testimonials Carousel
// Testimonials.jsx

const TESTIMONIALS = [{
  id: 1,
  name: 'Priya Sharma',
  role: 'Event Attendee',
  initials: 'PS',
  quote: "AB Entertainment transformed my understanding of Marathi theatre. The production quality rivals anything I've seen in Mumbai. Absolutely world-class.",
  stars: 5,
  event: 'Punha Sahi re Sahi'
}, {
  id: 2,
  name: 'Rajesh Kulkarni',
  role: 'Community Leader',
  initials: 'RK',
  quote: "They don't just organise events — they create cultural experiences. Every detail from lighting to sound is meticulously crafted. A gem for Melbourne's Indian community.",
  stars: 5,
  event: 'Shyamachi Aai'
}, {
  id: 3,
  name: 'Sneha Deshmukh',
  role: 'Regular Patron',
  initials: 'SD',
  quote: "I've attended every AB Entertainment show for the past three years. The consistency of quality and the passion behind every performance is truly inspiring.",
  stars: 5,
  event: 'Sankarshan via Spruha'
}, {
  id: 4,
  name: 'Michael Thompson',
  role: 'Arts Critic, The Age',
  initials: 'MT',
  quote: "AB Entertainment is doing something remarkable — bringing authentic Indian cultural performances to Melbourne with production values that rival our best theatre companies.",
  stars: 5,
  event: 'Arya Ambekar Live in Concert'
}];
const Stars = ({
  n
}) => React.createElement('div', {
  style: {
    display: 'flex',
    gap: 3,
    marginBottom: 16
  }
}, [1, 2, 3, 4, 5].map(i => React.createElement('svg', {
  key: i,
  width: 14,
  height: 14,
  fill: i <= n ? 'var(--accent)' : 'rgba(255,255,255,0.2)',
  viewBox: '0 0 24 24',
  style: {
    filter: i <= n ? 'drop-shadow(0 0 4px rgba(var(--accent-rgb),0.5))' : 'none'
  }
}, React.createElement('polygon', {
  points: '12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2'
}))));
const TestimonialsSection = () => {
  const [idx, setIdx] = React.useState(0);
  const [dir, setDir] = React.useState(0);
  const [visible, setVisible] = React.useState(true);
  const goTo = React.useCallback(newIdx => {
    setVisible(false);
    setTimeout(() => {
      setIdx((newIdx + TESTIMONIALS.length) % TESTIMONIALS.length);
      setVisible(true);
    }, 300);
  }, []);
  React.useEffect(() => {
    const t = setTimeout(() => goTo(idx + 1), 6000);
    return () => clearTimeout(t);
  }, [idx, goTo]);
  const t = TESTIMONIALS[idx];
  return React.createElement('section', {
    style: {
      position: 'relative',
      padding: '112px 0',
      background: '#0A0A0A',
      overflow: 'hidden'
    }
  }, React.createElement('div', {
    style: {
      position: 'absolute',
      top: '50%',
      left: '50%',
      transform: 'translate(-50%,-50%)',
      width: 600,
      height: 300,
      background: 'radial-gradient(ellipse,rgba(var(--accent-rgb),0.03),transparent 60%)',
      pointerEvents: 'none'
    }
  }), React.createElement('div', {
    style: {
      position: 'absolute',
      top: 0,
      left: 0,
      right: 0,
      height: 1,
      background: 'linear-gradient(90deg,transparent,rgba(var(--accent-rgb),0.2),transparent)'
    }
  }), React.createElement('div', {
    className: 'container-eu'
  },
  // Header
  React.createElement('div', {
    style: {
      textAlign: 'center',
      marginBottom: '72px'
    }
  }, React.createElement(SectionEyebrow, null, 'Testimonials'), React.createElement('h2', {
    style: {
      fontFamily: 'var(--font-display)',
      fontSize: 'clamp(2rem,4vw,3.5rem)',
      fontWeight: 700,
      color: '#fff',
      margin: '0 0 20px'
    }
  }, 'What People ', React.createElement('span', {
    className: 'gold-shimmer'
  }, 'Say')), React.createElement(OrnamentDivider, null)),
  // Carousel
  React.createElement('div', {
    style: {
      position: 'relative',
      maxWidth: 680,
      margin: '0 auto'
    }
  },
  // Card
  React.createElement('div', {
    style: {
      background: 'rgba(255,255,255,0.02)',
      backdropFilter: 'blur(12px)',
      border: '1px solid rgba(var(--accent-rgb),0.08)',
      padding: '40px 48px',
      position: 'relative',
      opacity: visible ? 1 : 0,
      transform: visible ? 'translateX(0)' : `translateX(${dir > 0 ? 30 : -30}px)`,
      transition: 'opacity 300ms, transform 300ms cubic-bezier(0.25,1,0.5,1)'
    }
  },
  // Big quote mark
  React.createElement('div', {
    style: {
      position: 'absolute',
      top: 16,
      left: 20,
      fontFamily: 'var(--font-display)',
      fontSize: '5rem',
      color: 'rgba(var(--accent-rgb),0.07)',
      lineHeight: 1
    }
  }, '\u201C'), React.createElement(Stars, {
    n: t.stars
  }), React.createElement('p', {
    style: {
      fontFamily: 'var(--font-body)',
      fontSize: '1rem',
      color: 'rgba(255,255,255,0.65)',
      lineHeight: 1.7,
      fontStyle: 'italic',
      margin: '0 0 8px',
      position: 'relative',
      zIndex: 1
    }
  }, t.quote), React.createElement('p', {
    style: {
      fontSize: '0.72rem',
      color: 'rgba(var(--accent-rgb),0.5)',
      fontStyle: 'italic',
      margin: '0 0 20px'
    }
  }, `— ${t.event}`), React.createElement('div', {
    style: {
      width: 48,
      height: 1,
      background: 'rgba(var(--accent-rgb),0.2)',
      marginBottom: 20
    }
  }), React.createElement('div', {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 14
    }
  }, React.createElement('div', {
    style: {
      width: 44,
      height: 44,
      borderRadius: '50%',
      background: 'linear-gradient(135deg,rgba(var(--accent-rgb),0.15),rgba(var(--accent-rgb),0.05))',
      border: '1px solid rgba(var(--accent-rgb),0.2)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: 'var(--font-display)',
      fontWeight: 700,
      fontSize: '0.8rem',
      color: 'var(--accent)'
    }
  }, t.initials), React.createElement('div', null, React.createElement('div', {
    style: {
      fontFamily: 'var(--font-body)',
      fontSize: '0.82rem',
      fontWeight: 600,
      color: '#fff'
    }
  }, t.name), React.createElement('div', {
    style: {
      fontSize: '0.68rem',
      color: 'rgba(var(--accent-rgb),0.5)',
      letterSpacing: '0.04em'
    }
  }, t.role)))),
  // Prev / Next
  [-1, 1].map((d, i) => React.createElement('button', {
    key: d,
    onClick: () => {
      setDir(d);
      goTo(idx + d);
    },
    style: {
      position: 'absolute',
      [d < 0 ? 'left' : 'right']: -52,
      top: '50%',
      transform: 'translateY(-50%)',
      zIndex: 10,
      width: 40,
      height: 40,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      border: '1px solid rgba(var(--accent-rgb),0.15)',
      background: 'transparent',
      color: 'rgba(var(--accent-rgb),0.6)',
      cursor: 'pointer',
      transition: 'all 400ms cubic-bezier(0.25,1,0.5,1)'
    },
    onMouseEnter: e => {
      e.currentTarget.style.background = 'var(--accent)';
      e.currentTarget.style.color = '#000';
    },
    onMouseLeave: e => {
      e.currentTarget.style.background = 'transparent';
      e.currentTarget.style.color = 'rgba(var(--accent-rgb),0.6)';
    }
  }, React.createElement('svg', {
    width: 14,
    height: 14,
    fill: 'none',
    stroke: 'currentColor',
    viewBox: '0 0 24 24',
    strokeWidth: 1.5
  }, React.createElement('path', {
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
    d: d < 0 ? 'M15 19l-7-7 7-7' : 'M9 5l7 7-7 7'
  })))),
  // Dots
  React.createElement('div', {
    style: {
      display: 'flex',
      justifyContent: 'center',
      gap: 10,
      marginTop: 32
    }
  }, TESTIMONIALS.map((_, i) => React.createElement('button', {
    key: i,
    onClick: () => {
      setDir(i > idx ? 1 : -1);
      goTo(i);
    },
    style: {
      height: 2,
      border: 'none',
      cursor: 'pointer',
      padding: 0,
      background: i === idx ? 'var(--accent)' : 'rgba(255,255,255,0.1)',
      width: i === idx ? 40 : 12,
      transition: 'all 500ms cubic-bezier(0.25,1,0.5,1)'
    }
  }))))));
};
Object.assign(window, {
  TestimonialsSection
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/website/testimonials.jsx", error: String((e && e.message) || e) }); }

// ui_kits/website/tweaks-panel.jsx
try { (() => {
// @ds-adherence-ignore -- omelette starter scaffold (raw elements/hex/px by design)
// Copied omelette starter. Re-running copy_starter_component with this kind overwrites this file with the latest version (page content is unaffected).

/* BEGIN USAGE */
// tweaks-panel.jsx
// Reusable Tweaks shell + form-control helpers.
// Exports (to window): useTweaks, TweaksPanel, TweakSection, TweakRow, TweakSlider,
//   TweakToggle, TweakRadio, TweakSelect, TweakText, TweakNumber, TweakColor, TweakButton.
//
// Owns the host protocol (listens for __activate_edit_mode / __deactivate_edit_mode,
// posts __edit_mode_available / __edit_mode_set_keys / __edit_mode_dismissed) so
// individual prototypes don't re-roll it. Ships a consistent set of controls so you
// don't hand-draw <input type="range">, segmented radios, steppers, etc.
//
// Usage (in an HTML file that loads React + Babel):
//
//   const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
//     "primaryColor": "#D97757",
//     "palette": ["#D97757", "#29261b", "#f6f4ef"],
//     "fontSize": 16,
//     "density": "regular",
//     "dark": false
//   }/*EDITMODE-END*/;
//
//   function App() {
//     const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
//     return (
//       <div style={{ fontSize: t.fontSize, color: t.primaryColor }}>
//         Hello
//         <TweaksPanel>
//           <TweakSection label="Typography" />
//           <TweakSlider label="Font size" value={t.fontSize} min={10} max={32} unit="px"
//                        onChange={(v) => setTweak('fontSize', v)} />
//           <TweakRadio  label="Density" value={t.density}
//                        options={['compact', 'regular', 'comfy']}
//                        onChange={(v) => setTweak('density', v)} />
//           <TweakSection label="Theme" />
//           <TweakColor  label="Primary" value={t.primaryColor}
//                        options={['#D97757', '#2A6FDB', '#1F8A5B', '#7A5AE0']}
//                        onChange={(v) => setTweak('primaryColor', v)} />
//           <TweakColor  label="Palette" value={t.palette}
//                        options={[['#D97757', '#29261b', '#f6f4ef'],
//                                  ['#475569', '#0f172a', '#f1f5f9']]}
//                        onChange={(v) => setTweak('palette', v)} />
//           <TweakToggle label="Dark mode" value={t.dark}
//                        onChange={(v) => setTweak('dark', v)} />
//         </TweaksPanel>
//       </div>
//     );
//   }
//
// TweakRadio is the segmented control for 2–3 short options (auto-falls-back to
// TweakSelect past ~16/~10 chars per label); reach for TweakSelect directly when
// options are many or long. For color tweaks always curate 3-4 options rather than
// a free picker; an option can also be a whole 2–5 color palette (the stored value
// is the array). The Tweak* controls are a floor, not a ceiling — build custom
// controls inside the panel if a tweak calls for UI they don't cover.
/* END USAGE */
// ─────────────────────────────────────────────────────────────────────────────

const __TWEAKS_STYLE = `
  .twk-panel{position:fixed;right:16px;bottom:16px;z-index:2147483646;width:280px;
    max-height:calc(100vh - 32px);display:flex;flex-direction:column;
    transform:scale(var(--dc-inv-zoom,1));transform-origin:bottom right;
    background:rgba(250,249,247,.78);color:#29261b;
    -webkit-backdrop-filter:blur(24px) saturate(160%);backdrop-filter:blur(24px) saturate(160%);
    border:.5px solid rgba(255,255,255,.6);border-radius:14px;
    box-shadow:0 1px 0 rgba(255,255,255,.5) inset,0 12px 40px rgba(0,0,0,.18);
    font:11.5px/1.4 ui-sans-serif,system-ui,-apple-system,sans-serif;overflow:hidden}
  .twk-hd{display:flex;align-items:center;justify-content:space-between;
    padding:10px 8px 10px 14px;cursor:move;user-select:none}
  .twk-hd b{font-size:12px;font-weight:600;letter-spacing:.01em}
  .twk-x{appearance:none;border:0;background:transparent;color:rgba(41,38,27,.55);
    width:22px;height:22px;border-radius:6px;cursor:default;font-size:13px;line-height:1}
  .twk-x:hover{background:rgba(0,0,0,.06);color:#29261b}
  .twk-body{padding:2px 14px 14px;display:flex;flex-direction:column;gap:10px;
    overflow-y:auto;overflow-x:hidden;min-height:0;
    scrollbar-width:thin;scrollbar-color:rgba(0,0,0,.15) transparent}
  .twk-body::-webkit-scrollbar{width:8px}
  .twk-body::-webkit-scrollbar-track{background:transparent;margin:2px}
  .twk-body::-webkit-scrollbar-thumb{background:rgba(0,0,0,.15);border-radius:4px;
    border:2px solid transparent;background-clip:content-box}
  .twk-body::-webkit-scrollbar-thumb:hover{background:rgba(0,0,0,.25);
    border:2px solid transparent;background-clip:content-box}
  .twk-row{display:flex;flex-direction:column;gap:5px}
  .twk-row-h{flex-direction:row;align-items:center;justify-content:space-between;gap:10px}
  .twk-lbl{display:flex;justify-content:space-between;align-items:baseline;
    color:rgba(41,38,27,.72)}
  .twk-lbl>span:first-child{font-weight:500}
  .twk-val{color:rgba(41,38,27,.5);font-variant-numeric:tabular-nums}

  .twk-sect{font-size:10px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
    color:rgba(41,38,27,.45);padding:10px 0 0}
  .twk-sect:first-child{padding-top:0}

  .twk-field{appearance:none;box-sizing:border-box;width:100%;min-width:0;height:26px;padding:0 8px;
    border:.5px solid rgba(0,0,0,.1);border-radius:7px;
    background:rgba(255,255,255,.6);color:inherit;font:inherit;outline:none}
  .twk-field:focus{border-color:rgba(0,0,0,.25);background:rgba(255,255,255,.85)}
  select.twk-field{padding-right:22px;
    background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'><path fill='rgba(0,0,0,.5)' d='M0 0h10L5 6z'/></svg>");
    background-repeat:no-repeat;background-position:right 8px center}

  .twk-slider{appearance:none;-webkit-appearance:none;width:100%;height:4px;margin:6px 0;
    border-radius:999px;background:rgba(0,0,0,.12);outline:none}
  .twk-slider::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;
    width:14px;height:14px;border-radius:50%;background:#fff;
    border:.5px solid rgba(0,0,0,.12);box-shadow:0 1px 3px rgba(0,0,0,.2);cursor:default}
  .twk-slider::-moz-range-thumb{width:14px;height:14px;border-radius:50%;
    background:#fff;border:.5px solid rgba(0,0,0,.12);box-shadow:0 1px 3px rgba(0,0,0,.2);cursor:default}

  .twk-seg{position:relative;display:flex;padding:2px;border-radius:8px;
    background:rgba(0,0,0,.06);user-select:none}
  .twk-seg-thumb{position:absolute;top:2px;bottom:2px;border-radius:6px;
    background:rgba(255,255,255,.9);box-shadow:0 1px 2px rgba(0,0,0,.12);
    transition:left .15s cubic-bezier(.3,.7,.4,1),width .15s}
  .twk-seg.dragging .twk-seg-thumb{transition:none}
  .twk-seg button{appearance:none;position:relative;z-index:1;flex:1;border:0;
    background:transparent;color:inherit;font:inherit;font-weight:500;min-height:22px;
    border-radius:6px;cursor:default;padding:4px 6px;line-height:1.2;
    overflow-wrap:anywhere}

  .twk-toggle{position:relative;width:32px;height:18px;border:0;border-radius:999px;
    background:rgba(0,0,0,.15);transition:background .15s;cursor:default;padding:0}
  .twk-toggle[data-on="1"]{background:#34c759}
  .twk-toggle i{position:absolute;top:2px;left:2px;width:14px;height:14px;border-radius:50%;
    background:#fff;box-shadow:0 1px 2px rgba(0,0,0,.25);transition:transform .15s}
  .twk-toggle[data-on="1"] i{transform:translateX(14px)}

  .twk-num{display:flex;align-items:center;box-sizing:border-box;min-width:0;height:26px;padding:0 0 0 8px;
    border:.5px solid rgba(0,0,0,.1);border-radius:7px;background:rgba(255,255,255,.6)}
  .twk-num-lbl{font-weight:500;color:rgba(41,38,27,.6);cursor:ew-resize;
    user-select:none;padding-right:8px}
  .twk-num input{flex:1;min-width:0;height:100%;border:0;background:transparent;
    font:inherit;font-variant-numeric:tabular-nums;text-align:right;padding:0 8px 0 0;
    outline:none;color:inherit;-moz-appearance:textfield}
  .twk-num input::-webkit-inner-spin-button,.twk-num input::-webkit-outer-spin-button{
    -webkit-appearance:none;margin:0}
  .twk-num-unit{padding-right:8px;color:rgba(41,38,27,.45)}

  .twk-btn{appearance:none;height:26px;padding:0 12px;border:0;border-radius:7px;
    background:rgba(0,0,0,.78);color:#fff;font:inherit;font-weight:500;cursor:default}
  .twk-btn:hover{background:rgba(0,0,0,.88)}
  .twk-btn.secondary{background:rgba(0,0,0,.06);color:inherit}
  .twk-btn.secondary:hover{background:rgba(0,0,0,.1)}

  .twk-swatch{appearance:none;-webkit-appearance:none;width:56px;height:22px;
    border:.5px solid rgba(0,0,0,.1);border-radius:6px;padding:0;cursor:default;
    background:transparent;flex-shrink:0}
  .twk-swatch::-webkit-color-swatch-wrapper{padding:0}
  .twk-swatch::-webkit-color-swatch{border:0;border-radius:5.5px}
  .twk-swatch::-moz-color-swatch{border:0;border-radius:5.5px}

  .twk-chips{display:flex;gap:6px}
  .twk-chip{position:relative;appearance:none;flex:1;min-width:0;height:46px;
    padding:0;border:0;border-radius:6px;overflow:hidden;cursor:default;
    box-shadow:0 0 0 .5px rgba(0,0,0,.12),0 1px 2px rgba(0,0,0,.06);
    transition:transform .12s cubic-bezier(.3,.7,.4,1),box-shadow .12s}
  .twk-chip:hover{transform:translateY(-1px);
    box-shadow:0 0 0 .5px rgba(0,0,0,.18),0 4px 10px rgba(0,0,0,.12)}
  .twk-chip[data-on="1"]{box-shadow:0 0 0 1.5px rgba(0,0,0,.85),
    0 2px 6px rgba(0,0,0,.15)}
  .twk-chip>span{position:absolute;top:0;bottom:0;right:0;width:34%;
    display:flex;flex-direction:column;box-shadow:-1px 0 0 rgba(0,0,0,.1)}
  .twk-chip>span>i{flex:1;box-shadow:0 -1px 0 rgba(0,0,0,.1)}
  .twk-chip>span>i:first-child{box-shadow:none}
  .twk-chip svg{position:absolute;top:6px;left:6px;width:13px;height:13px;
    filter:drop-shadow(0 1px 1px rgba(0,0,0,.3))}
`;

// ── useTweaks ───────────────────────────────────────────────────────────────
// Single source of truth for tweak values. setTweak persists via the host
// (__edit_mode_set_keys → host rewrites the EDITMODE block on disk).
function useTweaks(defaults) {
  const [values, setValues] = React.useState(defaults);
  // Accepts either setTweak('key', value) or setTweak({ key: value, ... }) so a
  // useState-style call doesn't write a "[object Object]" key into the persisted
  // JSON block.
  const setTweak = React.useCallback((keyOrEdits, val) => {
    const edits = typeof keyOrEdits === 'object' && keyOrEdits !== null ? keyOrEdits : {
      [keyOrEdits]: val
    };
    setValues(prev => ({
      ...prev,
      ...edits
    }));
    window.parent.postMessage({
      type: '__edit_mode_set_keys',
      edits
    }, '*');
    // Same-window signal so in-page listeners (deck-stage rail thumbnails)
    // can react — the parent message only reaches the host, not peers.
    window.dispatchEvent(new CustomEvent('tweakchange', {
      detail: edits
    }));
  }, []);
  return [values, setTweak];
}

// ── TweaksPanel ─────────────────────────────────────────────────────────────
// Floating shell. Registers the protocol listener BEFORE announcing
// availability — if the announce ran first, the host's activate could land
// before our handler exists and the toolbar toggle would silently no-op.
// The close button posts __edit_mode_dismissed so the host's toolbar toggle
// flips off in lockstep; the host echoes __deactivate_edit_mode back which
// is what actually hides the panel.
function TweaksPanel({
  title = 'Tweaks',
  children
}) {
  const [open, setOpen] = React.useState(false);
  const dragRef = React.useRef(null);
  const offsetRef = React.useRef({
    x: 16,
    y: 16
  });
  const PAD = 16;
  const clampToViewport = React.useCallback(() => {
    const panel = dragRef.current;
    if (!panel) return;
    const w = panel.offsetWidth,
      h = panel.offsetHeight;
    const maxRight = Math.max(PAD, window.innerWidth - w - PAD);
    const maxBottom = Math.max(PAD, window.innerHeight - h - PAD);
    offsetRef.current = {
      x: Math.min(maxRight, Math.max(PAD, offsetRef.current.x)),
      y: Math.min(maxBottom, Math.max(PAD, offsetRef.current.y))
    };
    panel.style.right = offsetRef.current.x + 'px';
    panel.style.bottom = offsetRef.current.y + 'px';
  }, []);
  React.useEffect(() => {
    if (!open) return;
    clampToViewport();
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', clampToViewport);
      return () => window.removeEventListener('resize', clampToViewport);
    }
    const ro = new ResizeObserver(clampToViewport);
    ro.observe(document.documentElement);
    return () => ro.disconnect();
  }, [open, clampToViewport]);
  React.useEffect(() => {
    const onMsg = e => {
      const t = e?.data?.type;
      if (t === '__activate_edit_mode') setOpen(true);else if (t === '__deactivate_edit_mode') setOpen(false);
    };
    window.addEventListener('message', onMsg);
    window.parent.postMessage({
      type: '__edit_mode_available'
    }, '*');
    return () => window.removeEventListener('message', onMsg);
  }, []);
  const dismiss = () => {
    setOpen(false);
    window.parent.postMessage({
      type: '__edit_mode_dismissed'
    }, '*');
  };
  const onDragStart = e => {
    const panel = dragRef.current;
    if (!panel) return;
    const r = panel.getBoundingClientRect();
    const sx = e.clientX,
      sy = e.clientY;
    const startRight = window.innerWidth - r.right;
    const startBottom = window.innerHeight - r.bottom;
    const move = ev => {
      offsetRef.current = {
        x: startRight - (ev.clientX - sx),
        y: startBottom - (ev.clientY - sy)
      };
      clampToViewport();
    };
    const up = () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  };

  // data-om-starter: inert presence marker — Claude Design's starter-usage
  // probe reads it. The closed panel renders nothing, so the marker rides
  // the <html> element as an attribute instead of a rendered node — zero
  // elements added, so page CSS (even structural selectors like
  // :nth-child) can never observe it. It records that the page WIRES a
  // tweaks panel, whether or not the panel is open. Keep this effect.
  React.useEffect(() => {
    document.documentElement.setAttribute('data-om-starter', 'tweaks-panel');
    return () => document.documentElement.removeAttribute('data-om-starter');
  }, []);
  if (!open) return null;
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("style", null, __TWEAKS_STYLE), /*#__PURE__*/React.createElement("div", {
    ref: dragRef,
    className: "twk-panel",
    "data-omelette-chrome": "",
    style: {
      right: offsetRef.current.x,
      bottom: offsetRef.current.y
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-hd",
    onMouseDown: onDragStart
  }, /*#__PURE__*/React.createElement("b", null, title), /*#__PURE__*/React.createElement("button", {
    className: "twk-x",
    "aria-label": "Close tweaks",
    onMouseDown: e => e.stopPropagation(),
    onClick: dismiss
  }, "\u2715")), /*#__PURE__*/React.createElement("div", {
    className: "twk-body"
  }, children)));
}

// ── Layout helpers ──────────────────────────────────────────────────────────

function TweakSection({
  label,
  children
}) {
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "twk-sect"
  }, label), children);
}
function TweakRow({
  label,
  value,
  children,
  inline = false
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: inline ? 'twk-row twk-row-h' : 'twk-row'
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-lbl"
  }, /*#__PURE__*/React.createElement("span", null, label), value != null && /*#__PURE__*/React.createElement("span", {
    className: "twk-val"
  }, value)), children);
}

// ── Controls ────────────────────────────────────────────────────────────────

function TweakSlider({
  label,
  value,
  min = 0,
  max = 100,
  step = 1,
  unit = '',
  onChange
}) {
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label,
    value: `${value}${unit}`
  }, /*#__PURE__*/React.createElement("input", {
    type: "range",
    className: "twk-slider",
    min: min,
    max: max,
    step: step,
    value: value,
    onChange: e => onChange(Number(e.target.value))
  }));
}
function TweakToggle({
  label,
  value,
  onChange
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "twk-row twk-row-h"
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-lbl"
  }, /*#__PURE__*/React.createElement("span", null, label)), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "twk-toggle",
    "data-on": value ? '1' : '0',
    role: "switch",
    "aria-checked": !!value,
    onClick: () => onChange(!value)
  }, /*#__PURE__*/React.createElement("i", null)));
}
function TweakRadio({
  label,
  value,
  options,
  onChange
}) {
  const trackRef = React.useRef(null);
  const [dragging, setDragging] = React.useState(false);
  // The active value is read by pointer-move handlers attached for the lifetime
  // of a drag — ref it so a stale closure doesn't fire onChange for every move.
  const valueRef = React.useRef(value);
  valueRef.current = value;

  // Segments wrap mid-word once per-segment width runs out. The track is
  // ~248px (280 panel − 28 body pad − 4 seg pad), each button loses 12px
  // to its own padding, and 11.5px system-ui averages ~6.3px/char — so 2
  // options fit ~16 chars each, 3 fit ~10. Past that (or >3 options), fall
  // back to a dropdown rather than wrap.
  const labelLen = o => String(typeof o === 'object' ? o.label : o).length;
  const maxLen = options.reduce((m, o) => Math.max(m, labelLen(o)), 0);
  const fitsAsSegments = maxLen <= ({
    2: 16,
    3: 10
  }[options.length] ?? 0);
  if (!fitsAsSegments) {
    // <select> emits strings — map back to the original option value so the
    // fallback stays type-preserving (numbers, booleans) like the segment path.
    const resolve = s => {
      const m = options.find(o => String(typeof o === 'object' ? o.value : o) === s);
      return m === undefined ? s : typeof m === 'object' ? m.value : m;
    };
    return /*#__PURE__*/React.createElement(TweakSelect, {
      label: label,
      value: value,
      options: options,
      onChange: s => onChange(resolve(s))
    });
  }
  const opts = options.map(o => typeof o === 'object' ? o : {
    value: o,
    label: o
  });
  const idx = Math.max(0, opts.findIndex(o => o.value === value));
  const n = opts.length;
  const segAt = clientX => {
    const r = trackRef.current.getBoundingClientRect();
    const inner = r.width - 4;
    const i = Math.floor((clientX - r.left - 2) / inner * n);
    return opts[Math.max(0, Math.min(n - 1, i))].value;
  };
  const onPointerDown = e => {
    setDragging(true);
    const v0 = segAt(e.clientX);
    if (v0 !== valueRef.current) onChange(v0);
    const move = ev => {
      if (!trackRef.current) return;
      const v = segAt(ev.clientX);
      if (v !== valueRef.current) onChange(v);
    };
    const up = () => {
      setDragging(false);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("div", {
    ref: trackRef,
    role: "radiogroup",
    onPointerDown: onPointerDown,
    className: dragging ? 'twk-seg dragging' : 'twk-seg'
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-seg-thumb",
    style: {
      left: `calc(2px + ${idx} * (100% - 4px) / ${n})`,
      width: `calc((100% - 4px) / ${n})`
    }
  }), opts.map(o => /*#__PURE__*/React.createElement("button", {
    key: o.value,
    type: "button",
    role: "radio",
    "aria-checked": o.value === value
  }, o.label))));
}
function TweakSelect({
  label,
  value,
  options,
  onChange
}) {
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("select", {
    className: "twk-field",
    value: value,
    onChange: e => onChange(e.target.value)
  }, options.map(o => {
    const v = typeof o === 'object' ? o.value : o;
    const l = typeof o === 'object' ? o.label : o;
    return /*#__PURE__*/React.createElement("option", {
      key: v,
      value: v
    }, l);
  })));
}
function TweakText({
  label,
  value,
  placeholder,
  onChange
}) {
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("input", {
    className: "twk-field",
    type: "text",
    value: value,
    placeholder: placeholder,
    onChange: e => onChange(e.target.value)
  }));
}
function TweakNumber({
  label,
  value,
  min,
  max,
  step = 1,
  unit = '',
  onChange
}) {
  const clamp = n => {
    if (min != null && n < min) return min;
    if (max != null && n > max) return max;
    return n;
  };
  const startRef = React.useRef({
    x: 0,
    val: 0
  });
  const onScrubStart = e => {
    e.preventDefault();
    startRef.current = {
      x: e.clientX,
      val: value
    };
    const decimals = (String(step).split('.')[1] || '').length;
    const move = ev => {
      const dx = ev.clientX - startRef.current.x;
      const raw = startRef.current.val + dx * step;
      const snapped = Math.round(raw / step) * step;
      onChange(clamp(Number(snapped.toFixed(decimals))));
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };
  return /*#__PURE__*/React.createElement("div", {
    className: "twk-num"
  }, /*#__PURE__*/React.createElement("span", {
    className: "twk-num-lbl",
    onPointerDown: onScrubStart
  }, label), /*#__PURE__*/React.createElement("input", {
    type: "number",
    value: value,
    min: min,
    max: max,
    step: step,
    onChange: e => onChange(clamp(Number(e.target.value)))
  }), unit && /*#__PURE__*/React.createElement("span", {
    className: "twk-num-unit"
  }, unit));
}

// Relative-luminance contrast pick — checkmarks drawn over a swatch need to
// read on both #111 and #fafafa without per-option configuration. Hex input
// only (#rgb / #rrggbb); named or rgb()/hsl() colors fall through to "light".
function __twkIsLight(hex) {
  const h = String(hex).replace('#', '');
  const x = h.length === 3 ? h.replace(/./g, c => c + c) : h.padEnd(6, '0');
  const n = parseInt(x.slice(0, 6), 16);
  if (Number.isNaN(n)) return true;
  const r = n >> 16 & 255,
    g = n >> 8 & 255,
    b = n & 255;
  return r * 299 + g * 587 + b * 114 > 148000;
}
const __TwkCheck = ({
  light
}) => /*#__PURE__*/React.createElement("svg", {
  viewBox: "0 0 14 14",
  "aria-hidden": "true"
}, /*#__PURE__*/React.createElement("path", {
  d: "M3 7.2 5.8 10 11 4.2",
  fill: "none",
  strokeWidth: "2.2",
  strokeLinecap: "round",
  strokeLinejoin: "round",
  stroke: light ? 'rgba(0,0,0,.78)' : '#fff'
}));

// TweakColor — curated color/palette picker. Each option is either a single
// hex string or an array of 1-5 hex strings; the card adapts — a lone color
// renders solid, a palette renders colors[0] as the hero (left ~2/3) with the
// rest stacked in a sharp column on the right. onChange emits the
// option in the shape it was passed (string stays string, array stays array).
// Without options it falls back to the native color input for back-compat.
function TweakColor({
  label,
  value,
  options,
  onChange
}) {
  if (!options || !options.length) {
    return /*#__PURE__*/React.createElement("div", {
      className: "twk-row twk-row-h"
    }, /*#__PURE__*/React.createElement("div", {
      className: "twk-lbl"
    }, /*#__PURE__*/React.createElement("span", null, label)), /*#__PURE__*/React.createElement("input", {
      type: "color",
      className: "twk-swatch",
      value: value,
      onChange: e => onChange(e.target.value)
    }));
  }
  // Native <input type=color> emits lowercase hex per the HTML spec, so
  // compare case-insensitively. String() guards JSON.stringify(undefined),
  // which returns the primitive undefined (no .toLowerCase).
  const key = o => String(JSON.stringify(o)).toLowerCase();
  const cur = key(value);
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-chips",
    role: "radiogroup"
  }, options.map((o, i) => {
    const colors = Array.isArray(o) ? o : [o];
    const [hero, ...rest] = colors;
    const sup = rest.slice(0, 4);
    const on = key(o) === cur;
    return /*#__PURE__*/React.createElement("button", {
      key: i,
      type: "button",
      className: "twk-chip",
      role: "radio",
      "aria-checked": on,
      "data-on": on ? '1' : '0',
      "aria-label": colors.join(', '),
      title: colors.join(' · '),
      style: {
        background: hero
      },
      onClick: () => onChange(o)
    }, sup.length > 0 && /*#__PURE__*/React.createElement("span", null, sup.map((c, j) => /*#__PURE__*/React.createElement("i", {
      key: j,
      style: {
        background: c
      }
    }))), on && /*#__PURE__*/React.createElement(__TwkCheck, {
      light: __twkIsLight(hero)
    }));
  })));
}
function TweakButton({
  label,
  onClick,
  secondary = false
}) {
  return /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: secondary ? 'twk-btn secondary' : 'twk-btn',
    onClick: onClick
  }, label);
}
Object.assign(window, {
  useTweaks,
  TweaksPanel,
  TweakSection,
  TweakRow,
  TweakSlider,
  TweakToggle,
  TweakRadio,
  TweakSelect,
  TweakText,
  TweakNumber,
  TweakColor,
  TweakButton
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/website/tweaks-panel.jsx", error: String((e && e.message) || e) }); }

__ds_ns.Button = __ds_scope.Button;

__ds_ns.GlassCard = __ds_scope.GlassCard;

__ds_ns.OrnamentDivider = __ds_scope.OrnamentDivider;

__ds_ns.StatusBadge = __ds_scope.StatusBadge;

})();
