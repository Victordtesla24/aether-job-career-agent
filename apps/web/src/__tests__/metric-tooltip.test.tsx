// @vitest-environment jsdom
/**
 * GAP-E3 regression guard. Analytics metrics must expose a hover/focus
 * accessible tooltip via MetricTooltip: the metric value renders alongside
 * an (i) info trigger that is aria-described-by the popover, the popover
 * text becomes visible on hover/focus activation, and Escape closes it
 * while returning focus to the trigger.
 */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import MetricTooltip from "../components/MetricTooltip";

afterEach(() => {
  cleanup();
});

describe("MetricTooltip", () => {
  it("renders the value and an info trigger", () => {
    render(<MetricTooltip label="Interview Rate" value="42%" tooltip="Share of applications that reached an interview." />);
    expect(screen.getByText("42%")).not.toBeNull();
    expect(screen.getByRole("button", { name: /interview rate/i })).not.toBeNull();
  });

  it("associates the trigger with the popover via aria-describedby", () => {
    render(<MetricTooltip label="Market Pulse" value="72" tooltip="A blended read of hiring-market momentum." />);
    const trigger = screen.getByRole("button", { name: /market pulse/i });
    const describedBy = trigger.getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    const tooltip = document.getElementById(describedBy as string);
    expect(tooltip).not.toBeNull();
    expect(tooltip?.getAttribute("role")).toBe("tooltip");
    expect(tooltip?.textContent).toMatch(/blended read of hiring-market momentum/i);
  });

  it("shows the popover content on hover activation and hides it on mouse leave", () => {
    render(<MetricTooltip label="Job Probability Score" value="88%" tooltip="Likelihood of landing an offer given current activity." />);
    const trigger = screen.getByRole("button", { name: /job probability score/i });
    const describedBy = trigger.getAttribute("aria-describedby") as string;
    const tooltip = document.getElementById(describedBy) as HTMLElement;

    expect(tooltip.className).toMatch(/opacity-0/);
    fireEvent.mouseEnter(trigger);
    expect(tooltip.className).toMatch(/opacity-100/);
    fireEvent.mouseLeave(trigger);
    expect(tooltip.className).toMatch(/opacity-0/);
  });

  it("shows the popover on keyboard focus and closes on Escape, returning focus to the trigger", () => {
    render(<MetricTooltip label="ATS distribution" value="120 jobs" tooltip="Distribution of ATS match scores across scored jobs." />);
    const trigger = screen.getByRole("button", { name: /ats distribution/i });
    const describedBy = trigger.getAttribute("aria-describedby") as string;
    const tooltip = document.getElementById(describedBy) as HTMLElement;

    act(() => {
      trigger.focus();
    });
    expect(tooltip.className).toMatch(/opacity-100/);

    fireEvent.keyDown(trigger, { key: "Escape" });
    expect(tooltip.className).toMatch(/opacity-0/);
    expect(document.activeElement).toBe(trigger);
  });
});
