"use client";

import { useCallback, useEffect, useState } from "react";

import { AdminPageHeader } from "../../../components/admin/admin-shell";
import { ConfirmPanel, FIELD, Panel, PRIMARY_BTN, QUIET_BTN, formatAudExact } from "../../../components/admin/admin-ui";
import { DecisionGuidance } from "../../../components/ui/decision-guidance";
import { describeApiError } from "../../../lib/api/client";
import {
  fetchAdminPlans,
  updatePlanPricing,
  type AdminPlan,
  type PlanPricingUpdate,
} from "../../../lib/api/adminPlans";

function formatInputPrice(value: number | null): string {
  return value === null ? "" : String(value);
}

function parsePrice(value: string, label: string): number {
  if (value.trim() === "") {
    throw new Error(`${label} must be zero or more.`);
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) {
    throw new Error(`${label} must be zero or more.`);
  }
  return parsed;
}

function PlanRow({ plan, onSaved }: { plan: AdminPlan; onSaved: (plan: AdminPlan) => void }) {
  const [monthly, setMonthly] = useState(formatInputPrice(plan.priceAudMonthly));
  const [annual, setAnnual] = useState(formatInputPrice(plan.priceAudAnnual));
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<PlanPricingUpdate | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setMonthly(formatInputPrice(plan.priceAudMonthly));
    setAnnual(formatInputPrice(plan.priceAudAnnual));
  }, [plan.priceAudAnnual, plan.priceAudMonthly]);

  const beginSave = () => {
    try {
      const update: PlanPricingUpdate = {};
      if (monthly !== formatInputPrice(plan.priceAudMonthly)) {
        update.priceAudMonthly = parsePrice(monthly, "Monthly price");
      }
      if (annual !== formatInputPrice(plan.priceAudAnnual)) {
        update.priceAudAnnual = parsePrice(annual, "Annual price");
      }
      if (Object.keys(update).length === 0) {
        setError("Change a price before saving.");
        return;
      }
      setError(null);
      setPending(update);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Enter valid prices.");
    }
  };

  const confirmSave = () => {
    if (!pending) return;
    setBusy(true);
    setError(null);
    void (async () => {
      try {
        const saved = await updatePlanPricing(plan.id, pending);
        onSaved({ ...plan, ...saved });
        setPending(null);
      } catch (caught) {
        setError(describeApiError(caught, "Could not update this plan's prices."));
      } finally {
        setBusy(false);
      }
    })();
  };

  return (
    <tr data-testid={`admin-plan-row-${plan.id}`} className="border-t border-white/5 align-top">
      <td className="py-3 pr-4">
        <p className="font-medium text-aether-text">{plan.name}</p>
        <p className="type-meta">{plan.active ? "Active" : "Inactive"} · Future checkout catalog</p>
      </td>
      <td className="py-3 pr-4">
        <label className="sr-only" htmlFor={`plan-${plan.id}-monthly`}>
          {plan.name} monthly price (AUD)
        </label>
        <input id={`plan-${plan.id}-monthly`} className={FIELD} inputMode="decimal" value={monthly} onChange={(event) => setMonthly(event.target.value)} />
        <p className="type-meta mt-1">Current: {formatAudExact(plan.priceAudMonthly)}</p>
      </td>
      <td className="py-3 pr-4">
        <label className="sr-only" htmlFor={`plan-${plan.id}-annual`}>
          {plan.name} annual price (AUD)
        </label>
        <input id={`plan-${plan.id}-annual`} className={FIELD} inputMode="decimal" value={annual} onChange={(event) => setAnnual(event.target.value)} />
        <p className="type-meta mt-1">Current: {formatAudExact(plan.priceAudAnnual)}</p>
      </td>
      <td className="py-3">
        <button type="button" data-testid={`admin-plan-save-${plan.id}`} onClick={beginSave} disabled={busy} className={PRIMARY_BTN}>
          Save prices
        </button>
        {error ? <p data-testid={`admin-plan-error-${plan.id}`} role="alert" className="mt-2 text-sm text-red-300">{error}</p> : null}
        {pending ? (
          <ConfirmPanel
            testId={`admin-plan-save-panel-${plan.id}`}
            confirmTestId={`admin-plan-save-confirm-${plan.id}`}
            cancelTestId={`admin-plan-save-cancel-${plan.id}`}
            title={`Save ${plan.name} catalog pricing?`}
            confirmLabel="Save future checkout prices"
            busy={busy}
            onConfirm={confirmSave}
            onCancel={() => setPending(null)}
            body="This changes the local catalog for future checkout only. Existing subscriptions keep their current Stripe Price and are not repriced."
          />
        ) : null}
      </td>
    </tr>
  );
}

export default function AdminBillingPage() {
  const [plans, setPlans] = useState<AdminPlan[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await fetchAdminPlans();
      setPlans(result.plans);
      setError(null);
    } catch (caught) {
      setError(describeApiError(caught, "Could not load the catalog plans."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  return (
    <div>
      <AdminPageHeader title="Billing catalog" subtitle="Set AUD catalog prices for future checkout. Existing subscribers are not repriced." />
      {error ? <p role="alert" className="mb-3 text-sm text-red-300">{error}</p> : null}
      <Panel title="Plan prices" caption="Stripe price IDs are shown nowhere here and are never changed by this editor." testId="admin-plan-pricing">
        {loading ? <p className="text-sm text-aether-muted">Loading catalog…</p> : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-aether-muted-dim"><tr><th className="pb-2 pr-4">Plan</th><th className="pb-2 pr-4">Monthly (AUD)</th><th className="pb-2 pr-4">Annual (AUD)</th><th className="pb-2">Action</th></tr></thead>
              <tbody>{plans.map((plan) => <PlanRow key={plan.id} plan={plan} onSaved={(saved) => setPlans((current) => current.map((item) => item.id === saved.id ? saved : item))} />)}</tbody>
            </table>
          </div>
        )}
      </Panel>
      {/* R1.2 — decision affordance for the catalog surface. */}
      <DecisionGuidance
        tellsYou="the AUD catalog prices new checkouts will be charged — saving here never reprices an existing subscriber or touches Stripe price IDs."
        next="before changing a price, check the plan's current subscriber spend on /admin/spend so the new price still covers real LLM cost."
      />
      <button type="button" onClick={() => void load()} disabled={loading} className={`${QUIET_BTN} mt-4`}>Reload catalog</button>
    </div>
  );
}