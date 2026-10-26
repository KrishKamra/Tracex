import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { describeToken } from "@/components/code-inspector/CodeInspector";
import { QueryMirror } from "@/components/command-bar/CommandBar";
import { RRFPopover } from "@/components/search-stream/RRFPopover";
import { HitCard } from "@/components/search-stream/SearchStream";
import { handleShortcut } from "@/components/Workspace";
import type { CallSite, SearchHit } from "@/lib/types";
import { createWorkspaceStore } from "@/store/workspace";

import { CHARGE, CHECK_LIMIT, searchFixture, symbolFixture } from "./fixtures";

const top = searchFixture.hits[0] as SearchHit;

describe("command bar", () => {
  it("highlights prefix tokens live", () => {
    const { container } = render(<QueryMirror value="@save #/webhooks /billing/ refund" />);
    expect(container.querySelector(".q-sym")?.textContent).toBe("@save");
    expect(container.querySelector(".q-route")?.textContent).toBe("#/webhooks");
    expect(container.querySelector(".q-path")?.textContent).toBe("/billing/");
    expect(container.textContent).toBe("@save #/webhooks /billing/ refund");
  });
});

describe("search stream", () => {
  it("renders a hit card with its origin badge and location", () => {
    const onOpen = vi.fn();
    render(<HitCard hit={top} current onOpen={onOpen} />);
    expect(screen.getByText("Exact")).toBeTruthy();
    expect(screen.getByText(/billing\/limits.py:\d+-\d+/)).toBeTruthy();
    screen.getByRole("button", { name: /check_limit/ }).click();
    expect(onOpen).toHaveBeenCalled();
  });

  it("explains the RRF score per pillar", () => {
    render(<RRFPopover hit={top} open />);
    const tooltip = screen.getByRole("tooltip");
    expect(tooltip.textContent).toContain(top.rrf_score.toFixed(4));
    expect(tooltip.textContent).toContain(`#${top.dense_rank}`);
    expect(tooltip.textContent).toMatch(/Dense.*BM25.*Graph/);
    expect(tooltip.textContent).toContain("Σ w·1/(60 + rank)");
  });
});

describe("code inspector token hover", () => {
  const sites = new Map<number, CallSite[]>();
  for (const s of symbolFixture.call_sites) sites.set(s.line, [...(sites.get(s.line) ?? []), s]);

  it("resolves call sites on the same line independently", () => {
    const resolved = describeToken(symbolFixture, 46, "check_limit", sites);
    expect(resolved?.target).toBe(CHECK_LIMIT);
    const external = describeToken(symbolFixture, 46, "get", sites);
    expect(external?.target).toBeNull();
    expect(external?.detail).toMatch(/external/);
  });

  it("explains parameters and locals inside the focus", () => {
    expect(describeToken(symbolFixture, 45, "gateway", sites)?.title).toBe("parameter gateway: PaymentGateway");
    expect(describeToken(symbolFixture, 48, "charge", sites)?.title).toBe("local charge");
    expect(describeToken(symbolFixture, 44, "charge_customer", sites)?.title).toMatch(/function charge_customer/);
    expect(describeToken(symbolFixture, 3, "gateway", sites)).toBeNull(); // outside the symbol
  });
});

describe("keyboard model", () => {
  const press = (key: string, store = createWorkspaceStore(), chord = { pendingG: false }, mods = {}) => {
    const focusInput = vi.fn();
    const handled = handleShortcut(
      { key, metaKey: false, ctrlKey: false, altKey: false, ...mods },
      false,
      store.getState(),
      chord,
      focusInput,
    );
    return { handled, focusInput, store, chord };
  };

  it("toggles panels with [ and ]", () => {
    const { store } = press("[");
    expect(store.getState().panels.left).toBe(false);
    press("]", store);
    expect(store.getState().panels.right).toBe(false);
  });

  it("focuses the command bar with / and Cmd+K", () => {
    expect(press("/").focusInput).toHaveBeenCalled();
    expect(press("k", undefined, undefined, { metaKey: true }).focusInput).toHaveBeenCalled();
  });

  it("opens the shortcut modal with ? and closes it with Esc", () => {
    const { store } = press("?");
    expect(store.getState().shortcutsOpen).toBe(true);
    press("Escape", store);
    expect(store.getState().shortcutsOpen).toBe(false);
  });

  it("supports the g d chord", () => {
    const store = createWorkspaceStore();
    store.getState().select({ kind: "callee", id: CHARGE });
    const goToDefinition = vi.spyOn(store.getState(), "goToDefinition").mockImplementation(() => undefined);
    const chord = { pendingG: false };
    press("g", store, chord);
    expect(chord.pendingG).toBe(true);
    press("d", store, chord);
    expect(goToDefinition).toHaveBeenCalled();
    expect(chord.pendingG).toBe(false);
  });

  it("ignores single-key shortcuts while typing", () => {
    const store = createWorkspaceStore();
    const handled = handleShortcut(
      { key: "[", metaKey: false, ctrlKey: false, altKey: false },
      true,
      store.getState(),
      { pendingG: false },
      vi.fn(),
    );
    expect(handled).toBe(false);
    expect(store.getState().panels.left).toBe(true);
  });
});
