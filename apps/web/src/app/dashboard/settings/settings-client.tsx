"use client";

/**
 * Settings — profile, resume management, portfolio sync, agent configuration,
 * job board integrations, connected accounts, and billing. Backed by
 * GET/PUT /settings (wireframe: settings.html). The Save button validates and
 * persists via PUT.
 *
 * MV-settings-003 (HIGH): this screen's own endpoint matrix names
 * GET /billing/subscription, POST /billing/checkout and POST /billing/portal,
 * but none were ever called from here (GET /billing/entitlement fires from the
 * dashboard-wide SubscriptionGate, but that response is only used to decide
 * gate/no-gate — never rendered). The Billing & Subscription section below
 * fetches GET /billing/subscription directly and renders the real plan,
 * status and quota, plus a "Manage subscription" action wired to the real
 * POST /billing/portal endpoint (falls back to an honest contact-support
 * message when the account has no Stripe billing profile to manage yet).
 *
 * PAY-R3-05 (post-checkout success UX): Stripe's `success_url` sends a
 * completed checkout back to `/dashboard/settings?checkout=success`
 * (apps/api/app/services/stripe_gateway.py) — this was previously silently
 * dropped, so a paying customer saw no acknowledgment at all. We read the
 * query param directly off `window.location.search` (no `useSearchParams` ->
 * no Suspense boundary needed, same convention as the Gmail-connect callback
 * on /dashboard/email) and show a banner. Because the plan upgrade only
 * lands once the `checkout.session.completed` webhook processes (async, not
 * guaranteed to beat the browser redirect here), the banner starts in an
 * honest "activating" state and only claims success once GET
 * /billing/subscription actually confirms an active paid plan — it never
 * fabricates a success message ahead of the real data.
 *
 * PAY-R3-06 (billing display completeness): `subscription.currentPeriodEnd`
 * (the real Stripe renewal/next-charge date) and the plan's price were
 * fetched-but-never-rendered before this fix. The price isn't on
 * `GET /billing/subscription` itself, so we cross-reference the plan
 * catalog from the PUBLIC `GET /billing/plans` (fetchPlans) by
 * `subscription.plan.id` + `subscription.interval` to show the actual
 * amount being charged, alongside an explicit "Next billing date" (distinct
 * from the agent-run quota's own reset date, a different underlying field).
 */
import { useEffect, useMemo, useRef, useState } from "react";

import { apiBaseUrl, ApiError, describeApiError, formatRetryAfter, getToken } from "../../../lib/api/client";
import {
  fetchPlans,
  fetchSubscription,
  openBillingPortal,
  type Plan,
  type SubscriptionState,
} from "../../../lib/api/billing";
import {
  fetchCareerData,
  fetchSettings,
  refreshCareerData,
  saveSettings,
  type CareerData,
  type CareerDataSource,
  type SettingsPayload,
} from "../../../lib/api/workspaces";
import { runScoutAgent } from "../../../lib/api/jobs";
import {
  bySource,
  buildRefreshPayload,
  careerStatusLabel,
  careerStatusStyle,
  deriveInputs,
  type CareerDataInputs,
} from "../../../components/settings/career-data";
import { SECTIONS } from "./sections";
import { formatAud } from "../../../lib/format";
import { emailLooksValid } from "../../../components/auth/validation";


/** Matches the AUD formatter on /pricing (apps/web/src/app/pricing/page.tsx)
 * so the same plan price reads identically everywhere it's shown. */
const STATUS_STYLE: Record<string, string> = {
  connected: "bg-aether-green/15 text-aether-green border-aether-green/25",
  syncing: "bg-aether-amber/15 text-aether-amber border-aether-amber/25",
  not_configured: "bg-white/5 text-aether-muted-dim border-white/10",
  disconnected: "bg-red-500/10 text-red-300 border-red-500/25",
};

export default function SettingsClient({
  supportEmail,
  supportPhone,
}: {
  supportEmail: string | null;
  supportPhone: string | null;
}) {
  const [data, setData] = useState<SettingsPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState<string>("profile");
  const [profile, setProfile] = useState({ fullName: "", email: "", targetRole: "", location: "" });
  const [agentConfig, setAgentConfig] = useState({ autoApply: false, approvalGate: true, matchThreshold: 80 });
  const [saving, setSaving] = useState(false);
  const [savedNotice, setSavedNotice] = useState<string | null>(null);
  // Job Board Integrations sync (MV-settings-002): a single, real "Sync All"
  // wired to POST /agents/scout/run — the backend (ScoutAgent.run()) always
  // fans out over every registered adapter in one call, so there is no
  // honest way to sync just one board; the previous per-row "Sync" buttons
  // and their client-only setTimeout theater are gone.
  const [jobBoardSyncing, setJobBoardSyncing] = useState(false);
  const [jobBoardSyncNotice, setJobBoardSyncNotice] = useState<string | null>(null);
  const [jobBoardSyncError, setJobBoardSyncError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadNotice, setUploadNotice] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Career Data (GAP-P4-047 · ADR D-0031): real GitHub + portfolio ingestion
  // and a workspace-stored LinkedIn paste, all feeding tailoring context.
  const [career, setCareer] = useState<CareerData | null>(null);
  const [careerInputs, setCareerInputs] = useState<CareerDataInputs>({
    githubUsername: "",
    portfolioUrl: "",
    linkedinSummary: "",
  });
  const [linkedinDirty, setLinkedinDirty] = useState(false);
  const [careerSyncing, setCareerSyncing] = useState(false);
  const [careerError, setCareerError] = useState<string | null>(null);
  const [careerNotice, setCareerNotice] = useState<string | null>(null);

  // Billing & Subscription (MV-settings-003 / MV-pricing-003): the real plan,
  // status and usage quota, rendered from GET /billing/subscription (not just
  // fetched-and-discarded, as it was before this fix).
  const [subscription, setSubscription] = useState<SubscriptionState | null>(null);
  const [billingError, setBillingError] = useState<string | null>(null);
  const [portalLoading, setPortalLoading] = useState(false);
  const [portalMessage, setPortalMessage] = useState<string | null>(null);
  // PAY-R3-06: the public plan catalog, cross-referenced against
  // subscription.plan.id + subscription.interval to show the actual price
  // being charged (GET /billing/subscription itself has no price field).
  // Optional enrichment only — a failure here must never block the rest of
  // the billing section from rendering.
  const [plans, setPlans] = useState<Plan[] | null>(null);

  // PAY-R3-05: post-checkout success acknowledgment. "idle" = no checkout
  // just happened; "activating" = ?checkout=success was present but the
  // webhook-driven plan upgrade hasn't been confirmed by GET
  // /billing/subscription yet; "active" = confirmed. Never claims success
  // ahead of what the real subscription data shows.
  const [checkoutBanner, setCheckoutBanner] = useState<"idle" | "activating" | "active">("idle");
  const [checkoutBannerDismissed, setCheckoutBannerDismissed] = useState(false);
  const [checkoutRefreshing, setCheckoutRefreshing] = useState(false);

  // Composed once so both fallback messages below (409, 503) share the same
  // "Email X" / "Email X or call Y" / "Call Y" phrasing — honest about
  // whichever contact channel(s) are actually configured for this
  // deployment, never a placeholder.
  const contactLine =
    supportEmail && supportPhone
      ? `Email ${supportEmail} or call ${supportPhone}`
      : supportEmail
        ? `Email ${supportEmail}`
        : supportPhone
          ? `Call ${supportPhone}`
          : null;

  const manageSubscription = async () => {
    setPortalLoading(true);
    setPortalMessage(null);
    try {
      const { portalUrl } = await openBillingPortal();
      window.location.href = portalUrl;
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 401) return; // shared client already sent us to /login
        if (e.status === 409) {
          // No Stripe customer on this account (Free plan, or an
          // operator-granted entitlement bypassing real checkout) — the
          // portal has nothing to manage. Honest fallback, no fake success.
          setPortalMessage(
            contactLine
              ? `Your account isn't linked to a Stripe billing profile yet, so the self-service portal isn't available. ${contactLine} to manage or cancel your subscription.`
              : "Your account isn't linked to a Stripe billing profile yet, so the self-service portal isn't available. A support contact hasn't been published for this deployment yet.",
          );
        } else if (e.status === 503) {
          setPortalMessage(
            contactLine
              ? `Billing management isn't configured on this deployment yet. ${contactLine} for help with your subscription.`
              : "Billing management isn't configured on this deployment yet, and no support contact has been published.",
          );
        } else if (e.status === 429) {
          setPortalMessage(
            e.retryAfterSeconds !== undefined
              ? `Too many requests — please try again in about ${formatRetryAfter(e.retryAfterSeconds)}.`
              : "Too many requests — please wait a moment and try again.",
          );
        } else {
          setPortalMessage("Could not open the billing portal. Please try again.");
        }
      } else {
        setPortalMessage("Could not open the billing portal. Please try again.");
      }
    } finally {
      setPortalLoading(false);
    }
  };

  // Gate "Sync now" on the initial GET having resolved: until `career` is
  // populated, `careerInputs` still holds its un-loaded default (empty
  // strings), and submitting that verbatim would send an implicit clear of
  // a githubUsername/portfolioUrl the server already has configured
  // (GAP-P4-047 Wave-1 regression).
  const careerLoaded = career !== null;

  const refreshCareer = async () => {
    if (!careerLoaded) return;
    setCareerSyncing(true);
    setCareerError(null);
    setCareerNotice(null);
    try {
      const updated = await refreshCareerData(
        buildRefreshPayload(careerInputs, linkedinDirty, careerLoaded),
      );
      setCareer(updated);
      setCareerInputs(deriveInputs(updated));
      setLinkedinDirty(false);
      const failed = updated.sources.filter((s) => s.status === "error");
      setCareerNotice(
        failed.length > 0
          ? `Synced with ${failed.length} source error${failed.length > 1 ? "s" : ""} — see below.`
          : "Career data synced ✓",
      );
    } catch (e) {
      setCareerError(e instanceof Error ? e.message : "Career data refresh failed");
    } finally {
      setCareerSyncing(false);
    }
  };

  const uploadResume = async (file: File) => {
    setUploading(true);
    setUploadNotice(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(`${apiBaseUrl()}/resumes/upload`, {
        method: "POST",
        headers: { Authorization: `Bearer ${await getToken()}` },
        body: form,
      });
      if (!res.ok) {
        const detail = await res.text().catch(() => "");
        throw new Error(`Upload failed (${res.status}): ${detail.slice(0, 160)}`);
      }
      const created = (await res.json()) as { label?: string; version?: number };
      setUploadNotice(
        `Uploaded and parsed — registered as v${created.version} (“${created.label}”); story extraction ran.`,
      );
      setData(await fetchSettings());
    } catch (e) {
      setUploadNotice(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  useEffect(() => {
    fetchSettings()
      .then((s) => {
        setData(s);
        setProfile(s.profile);
        setAgentConfig(s.agentConfig);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Failed to load settings"));
  }, []);

  useEffect(() => {
    fetchSubscription()
      .then((s) => setSubscription(s))
      .catch((e: unknown) =>
        setBillingError(e instanceof Error ? e.message : "Failed to load billing/subscription"),
      );
  }, []);

  // PAY-R3-06: the public plan catalog, purely for its price breakdown —
  // optional display enrichment, so a failure here is silently swallowed
  // (the billing section still renders plan/status/quota either way).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetchPlans();
        if (!cancelled) setPlans(res.plans);
      } catch {
        // Price display falls back to an honest "—" below; never blocks.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // PAY-R3-05: read ?checkout=success directly off the query string (no
  // useSearchParams -> no Suspense boundary needed, mirrors the Gmail-connect
  // callback convention on /dashboard/email), then strip it so a refresh
  // doesn't re-show the banner.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("checkout") === "success") {
      setCheckoutBanner("activating");
      window.history.replaceState(null, "", "/dashboard/settings");
    }
  }, []);

  // Once a checkout just completed, flip the banner from "activating" to
  // "active" the moment GET /billing/subscription actually confirms an
  // active paid plan (webhook already processed) — never before, since the
  // upgrade is applied asynchronously by checkout.session.completed and may
  // not have landed yet when the browser redirects back here.
  useEffect(() => {
    if (checkoutBanner !== "activating" || subscription === null) return;
    const isPaidActive =
      subscription.status === "active" && subscription.plan !== null && subscription.plan.id !== "free";
    if (isPaidActive) setCheckoutBanner("active");
  }, [checkoutBanner, subscription]);

  const refreshBillingAfterCheckout = async () => {
    setCheckoutRefreshing(true);
    try {
      setSubscription(await fetchSubscription());
    } catch {
      // Best-effort manual refresh only — leave the "activating" banner up
      // so the user can try again rather than surfacing a new error state.
    } finally {
      setCheckoutRefreshing(false);
    }
  };

  useEffect(() => {
    fetchCareerData()
      .then((c) => {
        setCareer(c);
        setCareerInputs(deriveInputs(c));
      })
      .catch((e: unknown) =>
        setCareerError(e instanceof Error ? e.message : "Failed to load career data"),
      );
  }, []);

  const validation = useMemo(() => {
    const errors: Record<string, string> = {};
    if (!profile.fullName.trim()) errors.fullName = "Full name is required";
    if (!emailLooksValid(profile.email)) errors.email = "Enter a valid email address";
    if (!profile.targetRole.trim()) errors.targetRole = "Target role is required";
    if (!profile.location.trim()) errors.location = "Location is required";
    return errors;
  }, [profile]);

  const save = async () => {
    if (Object.keys(validation).length > 0) {
      setSavedNotice(null);
      setError("Fix the highlighted fields before saving.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await saveSettings(profile, agentConfig);
      setData(updated);
      setSavedNotice("Settings saved ✓");
      setTimeout(() => setSavedNotice(null), 4000);
    } catch (e) {
      // ML-settings-001: a raw 422 from FastAPI/Pydantic echoes the ENTIRE
      // invalid input back in ApiError.message — describeApiError() renders
      // a bounded, field-specific sentence instead of that raw payload.
      setError(describeApiError(e, "Save failed"));
    } finally {
      setSaving(false);
    }
  };

  // A real sync needs somewhere to search — the same targetRole/location the
  // scout agent's own profile-derived defaults use elsewhere in the app
  // (app/routers/agents.py `_user_search_defaults`). Gate the button rather
  // than firing a call we know the honest fallback would have to guess at.
  const jobBoardSyncReady = profile.targetRole.trim().length > 0 && profile.location.trim().length > 0;

  // PAY-R3-06: the current plan's price, cross-referenced from the public
  // plan catalog by id + billing interval. `null` when the catalog hasn't
  // loaded (or failed to), or when the current plan/interval isn't found
  // there — the render falls back to an honest "Price unavailable" rather
  // than a fabricated $0.
  const currentPlanDef = plans?.find((p) => p.id === subscription?.plan?.id) ?? null;
  const currentPriceBreakdown = currentPlanDef
    ? subscription?.interval === "year" && currentPlanDef.annual
      ? currentPlanDef.annual
      : currentPlanDef.monthly
    : null;

  const syncAllJobBoards = async () => {
    if (!jobBoardSyncReady || jobBoardSyncing) return;
    setJobBoardSyncing(true);
    setJobBoardSyncError(null);
    setJobBoardSyncNotice(null);
    try {
      const token = await getToken();
      await runScoutAgent(profile.targetRole, profile.location, { token, baseUrl: apiBaseUrl() });
      setData(await fetchSettings());
      setJobBoardSyncNotice("Job boards synced ✓");
      setTimeout(() => setJobBoardSyncNotice(null), 4000);
    } catch (e) {
      setJobBoardSyncError(e instanceof Error ? e.message : "Job board sync failed");
    } finally {
      setJobBoardSyncing(false);
    }
  };

  if (error && data === null) {
    return <p className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">{error}</p>;
  }

  if (data === null) {
    return (
      <div className="space-y-4" aria-busy="true" data-testid="settings-skeleton">
        {[0, 1].map((i) => (
          <div key={i} className="glass h-56 animate-pulse rounded-2xl border border-white/10" />
        ))}
      </div>
    );
  }

  const avatarInitials = profile.fullName
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <div className="space-y-6" data-testid="settings-page">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Settings &amp; Profile</h1>
          <p className="text-sm text-aether-muted">Profile, agent behaviour and integrations.</p>
        </div>
        <div className="flex items-center gap-3">
          {savedNotice ? (
            <span role="status" data-testid="settings-saved-notice" className="text-sm text-aether-green">
              {savedNotice}
            </span>
          ) : null}
          <button
            type="button"
            data-testid="save-settings-btn"
            onClick={() => void save()}
            disabled={saving}
            className="rounded-xl bg-aether-coral px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save Changes"}
          </button>
        </div>
      </header>

      {checkoutBanner !== "idle" && !checkoutBannerDismissed ? (
        <div
          role="status"
          data-testid="checkout-success-banner"
          className={`flex flex-wrap items-center justify-between gap-3 rounded-xl border p-3 text-sm ${
            checkoutBanner === "active"
              ? "border-aether-green/30 bg-aether-green/10 text-aether-green"
              : "border-white/10 bg-white/5 text-aether-muted"
          }`}
        >
          <span>
            {checkoutBanner === "active"
              ? `Subscription active — welcome to ${subscription?.plan?.name ?? "your new plan"}!`
              : "Payment received — your subscription is being activated. This can take a few seconds."}
          </span>
          <div className="flex items-center gap-3">
            {checkoutBanner === "activating" ? (
              <button
                type="button"
                data-testid="checkout-banner-refresh"
                onClick={() => void refreshBillingAfterCheckout()}
                disabled={checkoutRefreshing}
                className="rounded-lg border border-white/15 px-3 py-1 text-xs font-semibold text-aether-muted hover:border-white/30 hover:text-white disabled:opacity-50"
              >
                {checkoutRefreshing ? "Checking…" : "Refresh now"}
              </button>
            ) : null}
            <button
              type="button"
              aria-label="Dismiss"
              data-testid="checkout-banner-dismiss"
              onClick={() => setCheckoutBannerDismissed(true)}
              className="text-aether-muted-dim hover:text-white"
            >
              <i className="fa-solid fa-xmark" aria-hidden="true" />
            </button>
          </div>
        </div>
      ) : null}

      {error ? (
        // break-words (defense-in-depth, ML-settings-001): even a bounded
        // message could in principle contain one long unbroken token — this
        // guarantees it wraps inside the banner instead of ever forcing page
        // width, regardless of what produced the message.
        <p className="break-words rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
          {error}
        </p>
      ) : null}

      {/* min-w-0 (ML-adv-003, reopen of ML-settings-001): this grid is
          display:grid at every breakpoint (a single implicit auto column
          below xl, 4 explicit columns at xl+). Grid ITEMS get a
          content-based automatic minimum size on BOTH axes by default (the
          CSS Grid analogue of the flexbox min-width:auto trap) — an
          unbroken-token descendant's huge min-content width becomes this
          container's effective column-track floor, which visually overflows
          the container's own (correctly viewport-bounded) box instead of
          shrinking to it. min-w-0 here is defense-in-depth alongside the
          grid-item min-w-0 below, which is where that automatic minimum
          actually needs neutralising. */}
      <div className="grid min-w-0 gap-6 xl:grid-cols-4">
        {/* Subnav */}
        <nav className="glass h-fit rounded-2xl border border-white/10 p-2 xl:col-span-1" aria-label="Settings sections">
          {SECTIONS.map((s) => (
            <button
              key={s.id}
              type="button"
              data-testid={`settings-nav-${s.id}`}
              onClick={() => setActive(s.id)}
              aria-pressed={active === s.id}
              className={`block w-full rounded-lg px-3 py-2 text-left text-sm transition ${
                active === s.id ? "bg-aether-coral/15 font-semibold text-aether-coral" : "text-aether-muted hover:text-white"
              }`}
            >
              {s.label}
            </button>
          ))}
        </nav>

        {/* Sections */}
        {/* min-w-0 (ML-adv-003): this is the grid ITEM that actually carries
            the automatic-minimum-size trap — without it, this div's resolved
            min-width defaults to its content's min-content (which, for an
            unbroken 5000-char token nested inside, is ~tens of thousands of
            px), forcing the single mobile column track that wide and
            overflowing the page regardless of what the container above is
            sized to. min-w-0 drops that floor to 0 so the track can shrink
            to the viewport, letting the break-all fix below actually wrap
            the text instead of merely being ready to. */}
        <div className="min-w-0 space-y-6 xl:col-span-3">
          {(active === "profile" || active === "privacy") && (
            <section className="glass rounded-2xl border border-white/10 p-5" data-testid="settings-profile">
              <h2 className="mb-4 text-[15px] font-semibold">Profile</h2>
              <div className="mb-5 flex items-center gap-4">
                <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-aether-violet/20 text-lg font-bold text-aether-violet">
                  {avatarInitials || "?"}
                </span>
                {/* min-w-0 + overflow-hidden (ML-settings-001 / ML-adv-003):
                    this live preview echoes whatever is currently typed into
                    the Full name / Target role fields, unvalidated — an
                    in-progress oversized value must wrap here too, not just
                    in the post-save error banner, or it blows the page width
                    out on its own regardless of what the server says.
                    overflow-hidden is belt-and-suspenders: even if some future
                    edit reintroduces an unbreakable descendant here, this box
                    clips rather than leaking scrollable overflow up the page.
                    See the two grid-ancestor min-w-0s below (ML-adv-003) for
                    why min-w-0 alone here was insufficient for an UNBROKEN
                    token — this div's own min-w-0 only stops IT from being
                    the automatic-minimum-size floor; its ancestors need the
                    same treatment, and the text itself needs a wrap mode that
                    actually reduces min-content (see break-all below). */}
                <div className="min-w-0 overflow-hidden">
                  {/* break-all, not break-words (ML-adv-003): overflow-wrap:
                      break-word (Tailwind's break-words) only inserts a break
                      opportunity when normal line-breaking would otherwise
                      overflow an ALREADY width-constrained box — it does not
                      reduce the element's min-content contribution used by
                      flex/grid ancestors' automatic-minimum-size sizing. A
                      single unbroken token (e.g. 5000 'X's, no spaces) has
                      no normal break opportunities, so with break-words its
                      min-content is still the full unbroken run (~tens of
                      thousands of px), which is exactly what propagated
                      through the un-neutralised grid ancestors and blew out
                      document.scrollWidth on prod. word-break: break-all
                      (Tailwind: break-all) permits a break between ANY two
                      characters, which collapses the min-content contribution
                      down to a single character — combined with min-w-0 on
                      every grid ancestor above, the browser now has both a
                      track that's free to shrink to the viewport AND a text
                      node that's willing to wrap into it. */}
                  <p className="break-all text-sm font-semibold">{profile.fullName || "Your name"}</p>
                  <p className="break-all text-xs text-aether-muted-dim">{profile.targetRole || "Target role"}</p>
                </div>
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <Input label="Full name" value={profile.fullName} error={validation.fullName} testId="settings-fullname"
                  onChange={(v) => setProfile((p) => ({ ...p, fullName: v }))} />
                <Input label="Email" value={profile.email} error={validation.email} testId="settings-email"
                  onChange={(v) => setProfile((p) => ({ ...p, email: v }))} />
                <Input label="Target role" value={profile.targetRole} error={validation.targetRole} testId="settings-targetrole"
                  onChange={(v) => setProfile((p) => ({ ...p, targetRole: v }))} />
                <Input label="Location" value={profile.location} error={validation.location} testId="settings-location"
                  onChange={(v) => setProfile((p) => ({ ...p, location: v }))} />
              </div>
              {active === "privacy" ? (
                <p className="mt-4 rounded-xl border border-white/10 bg-white/5 p-3 text-xs text-aether-muted">
                  <i className="fa-solid fa-shield-halved mr-2 text-aether-green" aria-hidden="true" />
                  Aether stores your data locally to this workspace. Agents never submit an application, send an
                  email, or share your profile without an explicit approval. You can correct your profile here at
                  any time and disconnect a connected Gmail account from the Email Center whenever you like —
                  there is no self-service &ldquo;export all data&rdquo; or &ldquo;delete all data&rdquo; button
                  yet; contact us to request a full data export or deletion and we will process it manually.
                </p>
              ) : null}
            </section>
          )}

          {(active === "resume" || active === "portfolio" || active === "profile") && (
            <div className="space-y-6">
              <section className="glass rounded-2xl border border-white/10 p-5" data-testid="settings-resume">
                <h2 className="mb-3 text-[15px] font-semibold">Resume Management</h2>
                <div className="flex items-center justify-between rounded-xl border border-aether-green/25 bg-aether-green/5 p-3">
                  <div className="flex items-center gap-2.5">
                    <i className="fa-solid fa-file-pdf text-aether-coral" aria-hidden="true" />
                    <div>
                      <p className="text-xs font-semibold">{data.resume.activeFile}</p>
                      <p className="mono text-[10px] text-aether-muted-dim">
                        uploaded {data.resume.uploadedAt} · {data.resume.versions} versions
                      </p>
                    </div>
                  </div>
                  <span className="rounded-md bg-aether-green/15 px-2 py-0.5 text-[10px] font-medium text-aether-green">
                    Active
                  </span>
                </div>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf,.txt,.md,application/pdf,text/plain"
                  className="hidden"
                  data-testid="resume-upload-input"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) void uploadResume(f);
                    e.target.value = "";
                  }}
                />
                <button
                  type="button"
                  data-testid="resume-upload-btn"
                  disabled={uploading}
                  onClick={() => fileInputRef.current?.click()}
                  className="mt-3 w-full rounded-lg border border-dashed border-white/15 py-2 text-xs text-aether-muted hover:border-white/30 hover:text-white disabled:opacity-50"
                >
                  <i
                    className={`fa-solid ${uploading ? "fa-spinner fa-spin" : "fa-upload"} mr-2`}
                    aria-hidden="true"
                  />
                  {uploading ? "Parsing…" : "Upload new version"}
                </button>
                {uploadNotice ? (
                  <p
                    className="mt-2 text-[11px] text-aether-muted"
                    data-testid="resume-upload-notice"
                    role="status"
                  >
                    {uploadNotice}
                  </p>
                ) : null}
              </section>

              <section
                className="glass rounded-2xl border border-white/10 p-5"
                data-testid="settings-portfolio"
                aria-labelledby="career-data-heading"
              >
                <div className="mb-1 flex flex-wrap items-center justify-between gap-3">
                  <h2 id="career-data-heading" className="text-[15px] font-semibold">
                    Career Data
                  </h2>
                  {careerNotice ? (
                    <span role="status" data-testid="career-data-notice" className="text-[11px] text-aether-green">
                      {careerNotice}
                    </span>
                  ) : null}
                </div>
                <p className="mb-4 text-[11px] text-aether-muted-dim">
                  Aether consolidates your public GitHub, portfolio site and LinkedIn summary into the
                  evidence your tailoring and cover-letter agents draw on. Update a source and press
                  “Sync now” to re-ingest it.
                </p>

                {careerError ? (
                  <p
                    className="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 p-2.5 text-[11px] text-red-300"
                    role="alert"
                    data-testid="career-data-error"
                  >
                    {careerError}
                  </p>
                ) : null}

                <div className="space-y-4">
                  <div>
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <label
                        htmlFor="career-github"
                        className="text-[11px] font-medium uppercase tracking-wide text-aether-muted"
                      >
                        GitHub username
                      </label>
                      <SourceStatusChip source={bySource(career, "github")} />
                    </div>
                    <input
                      id="career-github"
                      type="text"
                      data-testid="career-github-input"
                      value={careerInputs.githubUsername}
                      onChange={(e) => setCareerInputs((c) => ({ ...c, githubUsername: e.target.value }))}
                      placeholder="e.g. octocat"
                      autoComplete="off"
                      className="mono w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm outline-none focus:border-aether-coral/50"
                    />
                    <SourceError source={bySource(career, "github")} />
                  </div>

                  <div>
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <label
                        htmlFor="career-portfolio"
                        className="text-[11px] font-medium uppercase tracking-wide text-aether-muted"
                      >
                        Portfolio URL
                      </label>
                      <SourceStatusChip source={bySource(career, "portfolio")} />
                    </div>
                    <input
                      id="career-portfolio"
                      type="url"
                      data-testid="career-portfolio-input"
                      value={careerInputs.portfolioUrl}
                      onChange={(e) => setCareerInputs((c) => ({ ...c, portfolioUrl: e.target.value }))}
                      placeholder="https://your-portfolio.example"
                      autoComplete="off"
                      className="mono w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm outline-none focus:border-aether-coral/50"
                    />
                    <SourceError source={bySource(career, "portfolio")} />
                  </div>

                  <div>
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <label
                        htmlFor="career-linkedin"
                        className="text-[11px] font-medium uppercase tracking-wide text-aether-muted"
                      >
                        Paste your LinkedIn summary
                      </label>
                      <SourceStatusChip source={bySource(career, "linkedin")} />
                    </div>
                    <textarea
                      id="career-linkedin"
                      data-testid="career-linkedin-input"
                      value={careerInputs.linkedinSummary}
                      onChange={(e) => {
                        setCareerInputs((c) => ({ ...c, linkedinSummary: e.target.value }));
                        setLinkedinDirty(true);
                      }}
                      rows={4}
                      placeholder="Paste the text from your LinkedIn ‘About’ / summary section…"
                      className="w-full resize-y rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm outline-none focus:border-aether-coral/50"
                    />
                    <p className="mt-1 text-[10px] text-aether-muted-dim">
                      {career?.linkedinNote ??
                        "LinkedIn has no public profile API — paste your summary to include it in tailoring."}
                    </p>
                    <SourceError source={bySource(career, "linkedin")} />
                  </div>
                </div>

                <button
                  type="button"
                  data-testid="career-sync-btn"
                  onClick={() => void refreshCareer()}
                  disabled={careerSyncing || !careerLoaded}
                  title={careerLoaded ? undefined : "Loading your career data…"}
                  className="mt-4 w-full rounded-lg border border-white/15 py-2 text-xs font-semibold text-aether-muted hover:border-white/30 hover:text-white disabled:opacity-50"
                >
                  {careerSyncing ? "Syncing…" : "Sync now"}
                </button>
              </section>
            </div>
          )}

          {(active === "agents" || active === "profile") && (
            <section className="glass rounded-2xl border border-white/10 p-5" data-testid="settings-agents">
              <h2 className="mb-4 text-[15px] font-semibold">Agent Configuration</h2>
              <div className="space-y-4">
                <Toggle
                  label="Auto-apply"
                  description="Let agents submit applications without a manual approval step"
                  value={agentConfig.autoApply}
                  testId="toggle-autoapply"
                  onChange={(v) => setAgentConfig((c) => ({ ...c, autoApply: v }))}
                />
                <Toggle
                  label="Approval gate"
                  description="Require explicit approval for anything that leaves the system"
                  value={agentConfig.approvalGate}
                  testId="toggle-approvalgate"
                  onChange={(v) => setAgentConfig((c) => ({ ...c, approvalGate: v }))}
                />
                <div>
                  <div className="mb-1 flex justify-between text-xs">
                    <span className="text-aether-muted">Match threshold — only surface jobs above</span>
                    <span className="mono font-semibold">{agentConfig.matchThreshold}%</span>
                  </div>
                  <input
                    type="range"
                    min={50}
                    max={100}
                    step={5}
                    value={agentConfig.matchThreshold}
                    data-testid="threshold-slider"
                    onChange={(e) => setAgentConfig((c) => ({ ...c, matchThreshold: Number(e.target.value) }))}
                    className="w-full accent-[#FF6B35]"
                    aria-label="Match threshold"
                  />
                </div>
              </div>
            </section>
          )}

          {active === "notifications" && (
            <section className="glass rounded-2xl border border-white/10 p-5" data-testid="settings-notifications">
              <h2 className="mb-4 text-[15px] font-semibold">Notifications</h2>
              <p
                role="status"
                data-testid="notifications-unavailable-notice"
                className="mb-4 rounded-xl border border-white/10 bg-white/5 p-3 text-xs text-aether-muted"
              >
                <i className="fa-solid fa-circle-info mr-2 text-aether-muted-dim" aria-hidden="true" />
                Notification delivery isn&rsquo;t built yet — these preferences aren&rsquo;t functional and
                aren&rsquo;t saved by &ldquo;Save Changes&rdquo;. Coming soon.
              </p>
              <div className="space-y-4">
                <Toggle label="Approval requests" description="Notify me when an agent needs my approval"
                  value={true} testId="toggle-notif-approvals" onChange={() => undefined} disabled />
                <Toggle label="Application updates" description="Status changes, recruiter views and responses"
                  value={true} testId="toggle-notif-apps" onChange={() => undefined} disabled />
                <Toggle label="Weekly digest" description="Summary of agent activity every Monday morning"
                  value={false} testId="toggle-notif-digest" onChange={() => undefined} disabled />
              </div>
            </section>
          )}

          {(active === "integrations" || active === "profile") && (
            <>
              <section className="glass rounded-2xl border border-white/10 p-5" data-testid="settings-integrations">
                <div className="mb-4 flex items-center justify-between">
                  <h2 className="text-[15px] font-semibold">Job Board Integrations</h2>
                  <button
                    type="button"
                    data-testid="sync-all-btn"
                    onClick={() => void syncAllJobBoards()}
                    disabled={jobBoardSyncing || !jobBoardSyncReady}
                    title={jobBoardSyncReady ? undefined : "Set your target role and location in Profile before syncing job boards"}
                    className="rounded-lg border border-white/15 px-3 py-1.5 text-xs font-semibold text-aether-muted hover:border-white/30 hover:text-white disabled:opacity-50"
                  >
                    {jobBoardSyncing ? "Syncing…" : "Sync All"}
                  </button>
                </div>
                {jobBoardSyncNotice ? (
                  <p role="status" data-testid="jobboard-sync-notice" className="mb-3 text-[11px] text-aether-green">
                    {jobBoardSyncNotice}
                  </p>
                ) : null}
                {jobBoardSyncError ? (
                  <p
                    role="alert"
                    data-testid="jobboard-sync-error"
                    className="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 p-2.5 text-[11px] text-red-300"
                  >
                    {jobBoardSyncError}
                  </p>
                ) : null}
                <div className="space-y-2.5">
                  {data.integrations.map((i) => (
                    <div key={i.name} className="flex items-center justify-between rounded-xl border border-white/10 bg-white/5 p-3">
                      <div>
                        <p className="text-xs font-semibold">{i.name}</p>
                        <p className="text-[11px] text-aether-muted-dim">{i.detail}</p>
                      </div>
                      <span className={`rounded-md border px-2 py-0.5 text-[10px] font-medium ${STATUS_STYLE[i.status] ?? STATUS_STYLE.not_configured}`}>
                        {i.status.replace("_", " ")}
                      </span>
                    </div>
                  ))}
                </div>
                <p className="mt-3 text-[10px] text-aether-muted-dim">
                  <i className="fa-solid fa-circle-info mr-1.5" aria-hidden="true" />
                  Job boards are synced together — per-source sync isn&rsquo;t available yet.
                </p>
              </section>

              <section className="glass rounded-2xl border border-white/10 p-5" data-testid="settings-accounts">
                <h2 className="mb-3 text-[15px] font-semibold">Connected Accounts &amp; API Keys</h2>
                <div className="space-y-2.5">
                  {data.connectedAccounts.map((a) => (
                    <div key={a.name} className="flex items-center justify-between rounded-xl border border-white/10 bg-white/5 p-3">
                      <div>
                        <p className="text-xs font-semibold">
                          {a.name} <span className="ml-1 rounded-md border border-aether-green/25 bg-aether-green/15 px-2 py-0.5 text-[10px] font-medium text-aether-green">Connected</span>
                        </p>
                        <p className="mono mt-1 text-[11px] text-aether-muted-dim">{a.detail}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            </>
          )}

          {(active === "billing" || active === "profile") && (
            <section className="glass rounded-2xl border border-white/10 p-5" data-testid="settings-billing">
              <h2 className="mb-4 text-[15px] font-semibold">Billing &amp; Subscription</h2>

              {billingError ? (
                <p
                  role="alert"
                  data-testid="billing-load-error"
                  className="rounded-lg border border-red-500/30 bg-red-500/10 p-2.5 text-[11px] text-red-300"
                >
                  {billingError}
                </p>
              ) : subscription === null ? (
                <p data-testid="billing-loading" className="text-xs text-aether-muted">
                  Loading your plan…
                </p>
              ) : (
                <>
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold" data-testid="billing-plan-name">
                        Current plan: {subscription.plan?.name ?? "No plan on record"}
                      </p>
                      <p className="text-xs text-aether-muted-dim" data-testid="billing-plan-status">
                        Status: {subscription.status ?? "no active subscription"}
                        {subscription.cancelAtPeriodEnd ? " · cancels at period end" : ""}
                      </p>
                    </div>
                    <span className="rounded-md border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] font-medium text-aether-muted">
                      {subscription.interval ? `${subscription.interval}ly billing` : "no billing cycle"}
                    </span>
                  </div>

                  <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-xs">
                    <span className="text-aether-muted" data-testid="billing-plan-price">
                      Price:{" "}
                      <span className="mono font-semibold text-aether-text">
                        {currentPriceBreakdown
                          ? `${formatAud(currentPriceBreakdown.total)} / ${
                              subscription.interval === "year" ? "year" : "month"
                            }`
                          : "Price unavailable"}
                      </span>
                    </span>
                    <span className="text-aether-muted" data-testid="billing-next-date">
                      Next billing date:{" "}
                      <span className="mono font-semibold text-aether-text">
                        {subscription.currentPeriodEnd
                          ? new Date(subscription.currentPeriodEnd).toLocaleDateString()
                          : "No upcoming charge"}
                      </span>
                    </span>
                  </div>

                  {subscription.quota ? (
                    <div className="mt-4 space-y-2" data-testid="billing-quota">
                      <div className="flex justify-between text-xs">
                        <span className="text-aether-muted">Agent runs this period</span>
                        <span className="mono font-semibold" data-testid="billing-quota-runs">
                          {subscription.quota.runsUsed} / {subscription.quota.runsAllowed}
                        </span>
                      </div>
                      <div className="h-2 w-full overflow-hidden rounded-full bg-white/10">
                        <div
                          className="h-full rounded-full bg-aether-coral"
                          style={{
                            width: `${Math.min(
                              100,
                              subscription.quota.runsAllowed > 0
                                ? (subscription.quota.runsUsed / subscription.quota.runsAllowed) * 100
                                : 0,
                            )}%`,
                          }}
                        />
                      </div>
                      <div className="flex justify-between text-xs">
                        <span className="text-aether-muted">Spend this period</span>
                        <span className="mono font-semibold" data-testid="billing-quota-spend">
                          ${subscription.quota.spendUsedUsd.toFixed(2)} / $
                          {subscription.quota.spendCapUsd.toFixed(2)} USD
                        </span>
                      </div>
                      {subscription.quota.periodEnd ? (
                        <p className="text-[11px] text-aether-muted-dim">
                          {/* Distinct from "Next billing date" above (PAY-R3-06)
                             — this is the agent-run usage quota's own reset
                             date, not necessarily the Stripe renewal date
                             (e.g. an annual plan still resets its run quota
                             monthly). */}
                          Usage quota resets {new Date(subscription.quota.periodEnd).toLocaleDateString()}
                        </p>
                      ) : null}
                    </div>
                  ) : (
                    <p className="mt-3 text-xs text-aether-muted-dim" data-testid="billing-no-quota">
                      No usage quota on record for this account yet.
                    </p>
                  )}

                  <button
                    type="button"
                    data-testid="manage-subscription-btn"
                    onClick={() => void manageSubscription()}
                    disabled={portalLoading}
                    className="mt-5 rounded-xl border border-white/15 px-4 py-2 text-xs font-semibold text-aether-muted hover:border-white/30 hover:text-white disabled:opacity-50"
                  >
                    {portalLoading ? "Opening billing portal…" : "Manage subscription"}
                  </button>

                  {portalMessage ? (
                    <p
                      role="status"
                      data-testid="manage-subscription-message"
                      className="mt-3 text-[11px] text-aether-muted"
                    >
                      {portalMessage}
                    </p>
                  ) : null}
                </>
              )}
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

/** Status chip for one career-data source (GAP-P4-047). */
function SourceStatusChip({ source }: { source?: CareerDataSource }) {
  const status = source?.status ?? "not_configured";
  return (
    <span
      data-testid={`career-${source?.source ?? "unknown"}-status`}
      className={`rounded-md border px-2 py-0.5 text-[10px] font-medium ${careerStatusStyle(status)}`}
    >
      {careerStatusLabel(status)}
      {source?.lastSynced ? (
        <span className="ml-1 text-aether-muted-dim">· {source.lastSynced.slice(0, 10)}</span>
      ) : null}
    </span>
  );
}

/**
 * Honest per-source detail line: red for a true error, muted guidance for an
 * "empty"/"not configured" source, nothing once the source is synced.
 */
function SourceError({ source }: { source?: CareerDataSource }) {
  if (!source || source.status === "ok" || !source.error) return null;
  const tone = source.status === "error" ? "text-red-300" : "text-aether-muted-dim";
  return (
    <p className={`mt-1 text-[10px] ${tone}`} data-testid={`career-${source.source}-detail`}>
      {source.error}
    </p>
  );
}

function Input({
  label,
  value,
  onChange,
  error,
  testId,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  error?: string;
  testId: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs text-aether-muted">{label}</span>
      <input
        type="text"
        value={value}
        data-testid={testId}
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={Boolean(error)}
        className={`w-full rounded-lg border bg-white/5 px-3 py-2 text-sm outline-none ${
          error ? "border-red-500/50" : "border-white/10 focus:border-aether-coral/50"
        }`}
      />
      {error ? <span className="mt-1 block text-[11px] text-red-300">{error}</span> : null}
    </label>
  );
}

function Toggle({
  label,
  description,
  value,
  onChange,
  testId,
  disabled,
}: {
  label: string;
  description: string;
  value: boolean;
  onChange: (v: boolean) => void;
  testId: string;
  /** Honestly non-functional (e.g. no backing persistence yet) — renders
   * genuinely inert via the native `disabled` attribute, not just a
   * no-op `onChange`, so it can never look interactive while doing nothing. */
  disabled?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div>
        <p className="text-sm font-semibold">
          {label}
          {disabled ? (
            <span className="ml-2 rounded-md border border-white/10 bg-white/5 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide text-aether-muted-dim">
              Coming soon
            </span>
          ) : null}
        </p>
        <p className="text-xs text-aether-muted-dim">{description}</p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={value}
        aria-disabled={disabled ? "true" : undefined}
        disabled={disabled}
        data-testid={testId}
        onClick={() => {
          if (disabled) return;
          onChange(!value);
        }}
        className={`relative h-6 w-11 shrink-0 rounded-full transition ${value ? "bg-aether-green" : "bg-white/15"} ${
          disabled ? "cursor-not-allowed opacity-50" : ""
        }`}
      >
        <span
          className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all ${value ? "left-[22px]" : "left-0.5"}`}
        />
      </button>
    </div>
  );
}
