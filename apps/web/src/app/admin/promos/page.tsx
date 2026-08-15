"use client";

/**
 * /admin/promos — Stripe coupons and their customer-facing promotion codes.
 *
 * STRIPE IS THE SOURCE OF TRUTH. There is no local mirror of these objects, so
 * this list is literally what `GET /admin/promos` read back from Stripe and
 * cannot drift from the Dashboard.
 *
 * CREATING A DISCOUNT CHARGES NOBODY. A Coupon plus a PromotionCode are
 * catalogue entries; money only moves when a customer redeems the code at their
 * own checkout. The page says so where the create button is, because "create"
 * on a billing screen is exactly the word an operator hesitates over.
 *
 * REMOVAL IS DEACTIVATION, NOT DELETION, and the label must not lie about it:
 * `DELETE /admin/promos/{id}` sets `active=false` on the promotion code. That is
 * reversible in the Stripe Dashboard and it preserves the redemption history of
 * everyone who already used the code — a coupon delete would not.
 *
 * A 503 IS NOT AN EMPTY LIST. "Billing is not configured on this deployment"
 * and "this Stripe account has no promotions" look identical if both render as
 * an empty table, so they are kept visibly distinct.
 */
import { useCallback, useEffect, useState } from "react";

import { AdminPageHeader } from "../../../components/admin/admin-shell";
import {
  ConfirmPanel,
  CopyButton,
  FIELD,
  Panel,
  PRIMARY_BTN,
  QUIET_BTN,
  StatusPill,
} from "../../../components/admin/admin-ui";
import { formatDate } from "../../../lib/format";
import {
  createPromo,
  deactivatePromo,
  describeDiscount,
  fetchPromos,
  PROMO_DURATIONS,
  type AdminPromo,
  type CreatedPromo,
  type PromoDuration,
} from "../../../lib/api/adminPromos";

const DURATION_LABEL: Record<PromoDuration, string> = {
  once: "First invoice only",
  repeating: "Repeating (choose months)",
  forever: "Every invoice, forever",
};

export default function AdminPromosPage() {
  const [promos, setPromos] = useState<AdminPromo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<CreatedPromo | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);

  // Create form
  const [kind, setKind] = useState<"percent" | "amount">("percent");
  const [value, setValue] = useState("");
  const [duration, setDuration] = useState<PromoDuration>("once");
  const [months, setMonths] = useState("");
  const [code, setCode] = useState("");
  const [maxRedemptions, setMaxRedemptions] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchPromos();
      setPromos(res.promos);
      setError(null);
    } catch (e) {
      // Kept in `error` and NOT turned into an empty list: "Stripe is not
      // configured here" is a different fact from "there are no promotions".
      setPromos([]);
      setError(e instanceof Error ? e.message : "Failed to load promotions");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const onCreate = () => {
    const amount = Number(value);
    if (value.trim() === "" || !Number.isFinite(amount) || amount <= 0) {
      setError("Enter a discount greater than 0.");
      return;
    }
    if (kind === "percent" && amount > 100) {
      setError("A percentage discount cannot exceed 100.");
      return;
    }
    let durationInMonths: number | undefined;
    if (duration === "repeating") {
      const m = Number(months);
      if (months.trim() === "" || !Number.isInteger(m) || m < 1) {
        setError("A repeating discount needs a whole number of months (1 or more).");
        return;
      }
      durationInMonths = m;
    }
    setBusy(true);
    setError(null);
    setCreated(null);
    void (async () => {
      try {
        const result = await createPromo({
          // Exactly one of the two — the backend 422s both or neither.
          ...(kind === "percent"
            ? { percentOff: Math.round(amount * 100) / 100 }
            : { amountOffAud: Math.round(amount * 100) / 100 }),
          duration,
          ...(durationInMonths !== undefined ? { durationInMonths } : {}),
          // Stripe stores codes uppercase; send the canonical form so the admin
          // sees the same string the customer will type.
          ...(code.trim() ? { code: code.trim().toUpperCase() } : {}),
          ...(maxRedemptions.trim() ? { maxRedemptions: Number(maxRedemptions) } : {}),
        });
        setCreated(result);
        setValue("");
        setCode("");
        setMonths("");
        setMaxRedemptions("");
        await load();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Could not create the promotion");
      } finally {
        setBusy(false);
      }
    })();
  };

  const onDeactivate = (promo: AdminPromo) => {
    setBusy(true);
    setError(null);
    void (async () => {
      try {
        await deactivatePromo(promo.id);
        setConfirmingId(null);
        await load();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Could not deactivate the promotion");
      } finally {
        setBusy(false);
      }
    })();
  };

  return (
    <div>
      <AdminPageHeader
        title="Promotions"
        subtitle="Stripe coupons and the codes customers type at checkout. Stripe is the source of truth — there is no local copy."
      />

      {error ? (
        <p role="alert" data-testid="admin-promos-error" className="mb-3 text-sm text-red-300">
          {error}
        </p>
      ) : null}

      <Panel
        title="Create a promotion"
        caption="A coupon plus its customer-facing code."
        testId="admin-promo-form"
      >
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <label className="text-xs text-aether-muted">
            Discount type
            <select
              aria-label="Discount type"
              value={kind}
              onChange={(e) => setKind(e.target.value === "amount" ? "amount" : "percent")}
              className={`${FIELD} mt-1`}
            >
              <option value="percent">Percentage off</option>
              <option value="amount">Fixed amount off (AUD)</option>
            </select>
          </label>
          <label className="text-xs text-aether-muted">
            {kind === "percent" ? "Percent off" : "Amount off (AUD)"}
            <input
              aria-label="Discount value"
              inputMode="decimal"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              className={`${FIELD} mt-1`}
            />
          </label>
          <label className="text-xs text-aether-muted">
            Duration
            <select
              aria-label="Duration"
              value={duration}
              onChange={(e) => setDuration(e.target.value as PromoDuration)}
              className={`${FIELD} mt-1`}
            >
              {PROMO_DURATIONS.map((d) => (
                <option key={d} value={d}>
                  {DURATION_LABEL[d]}
                </option>
              ))}
            </select>
          </label>
          {duration === "repeating" ? (
            <label className="text-xs text-aether-muted">
              Repeats for (months)
              <input
                aria-label="Repeats for (months)"
                inputMode="numeric"
                value={months}
                onChange={(e) => setMonths(e.target.value)}
                className={`${FIELD} mt-1`}
              />
            </label>
          ) : null}
          <label className="text-xs text-aether-muted">
            Code (optional)
            <input
              aria-label="Promotion code (optional)"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="left blank, Stripe generates one"
              className={`${FIELD} mono mt-1`}
            />
          </label>
          <label className="text-xs text-aether-muted">
            Max redemptions (optional)
            <input
              aria-label="Max redemptions (optional)"
              inputMode="numeric"
              value={maxRedemptions}
              onChange={(e) => setMaxRedemptions(e.target.value)}
              className={`${FIELD} mt-1`}
            />
          </label>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button
            type="button"
            data-testid="admin-promo-create"
            onClick={onCreate}
            disabled={busy}
            className={PRIMARY_BTN}
          >
            Create promotion
          </button>
          <span data-testid="admin-promos-money-note" className="type-meta max-w-prose">
            Creating a discount charges nobody — a coupon is a catalogue entry. Money
            only moves when a customer redeems the code at their own checkout.
          </span>
        </div>

        {created ? (
          <div
            data-testid="admin-promo-created"
            className="mt-3 flex flex-wrap items-center gap-2 rounded-xl border border-aether-green/40 bg-aether-green/[0.07] p-3"
          >
            <span className="text-sm text-aether-text">Created:</span>
            <code className="mono text-sm font-semibold text-aether-text">{created.code}</code>
            <span className="type-meta">
              {describeDiscount({
                percentOff: created.percentOff,
                amountOffAud: created.amountOffAud,
                duration: created.duration,
              })}
            </span>
            <CopyButton
              value={created.code}
              label="Copy code"
              ariaLabel={`Copy promotion code ${created.code}`}
            />
          </div>
        ) : null}
      </Panel>

      <div className="mt-4">
        <Panel title="Promotion codes" caption="As Stripe holds them." testId="admin-promos-list">
          {loading ? (
            <p className="text-sm text-aether-muted">Loading…</p>
          ) : promos.length === 0 && !error ? (
            <p data-testid="admin-promos-empty" className="text-sm text-aether-muted">
              No promotion codes exist in this Stripe account yet.
            </p>
          ) : promos.length === 0 ? null : (
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead className="text-left text-xs uppercase tracking-wide text-aether-muted-dim">
                  <tr>
                    <th className="py-2 pr-4">Code</th>
                    <th className="py-2 pr-4">Discount</th>
                    <th className="py-2 pr-4 text-right">Redeemed</th>
                    <th className="py-2 pr-4">Expires</th>
                    <th className="py-2 pr-4">Status</th>
                    <th className="py-2 pr-4" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {promos.map((p) => (
                    <tr key={p.id} data-testid={`admin-promo-row-${p.id}`}>
                      <td className="py-2.5 pr-4 align-top">
                        <div className="flex flex-wrap items-center gap-2">
                          <code className="mono text-sm text-aether-text">{p.code}</code>
                          <CopyButton
                            value={p.code}
                            testId={`admin-promo-copy-${p.id}`}
                            ariaLabel={`Copy promotion code ${p.code}`}
                          />
                        </div>
                      </td>
                      <td className="py-2.5 pr-4 align-top text-aether-muted">
                        {describeDiscount(p)}
                      </td>
                      <td className="mono py-2.5 pr-4 text-right align-top tabular-nums text-aether-text">
                        {p.timesRedeemed ?? 0}
                        {p.maxRedemptions ? ` / ${p.maxRedemptions}` : ""}
                      </td>
                      <td className="py-2.5 pr-4 align-top text-aether-muted">
                        {p.expiresAt ? formatDate(p.expiresAt) : "no expiry"}
                      </td>
                      <td className="py-2.5 pr-4 align-top">
                        <StatusPill
                          testId={`admin-promo-status-${p.id}`}
                          state={p.active ? "active" : "inactive"}
                          tone={p.active ? "good" : "neutral"}
                        >
                          {p.active ? "active" : "inactive"}
                        </StatusPill>
                      </td>
                      <td className="py-2.5 pr-4 text-right align-top">
                        {p.active ? (
                          <button
                            type="button"
                            data-testid={`admin-promo-deactivate-${p.id}`}
                            onClick={() => setConfirmingId(p.id)}
                            disabled={busy}
                            className={`${QUIET_BTN} px-2 py-1 text-xs`}
                          >
                            Deactivate
                          </button>
                        ) : (
                          <span className="type-meta">no longer redeemable</span>
                        )}
                        {confirmingId === p.id ? (
                          <ConfirmPanel
                            testId="admin-promo-deactivate-panel"
                            confirmTestId="admin-promo-deactivate-confirm"
                            cancelTestId="admin-promo-deactivate-cancel"
                            title={`Deactivate ${p.code}?`}
                            confirmLabel="Deactivate the code"
                            busy={busy}
                            onConfirm={() => onDeactivate(p)}
                            onCancel={() => setConfirmingId(null)}
                            body={
                              <>
                                The code stops working at checkout from now on. It is not
                                deleted: the redemption history of everyone who already
                                used it survives, and the code can be switched back on in
                                the Stripe Dashboard.
                              </>
                            }
                          />
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
