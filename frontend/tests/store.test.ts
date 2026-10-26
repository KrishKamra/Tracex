import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Api } from "@/lib/api";
import { createWorkspaceStore, currentHighlight, toRanges } from "@/store/workspace";

import {
  CHARGE,
  CHECK_LIMIT,
  graphCheckLimitFixture,
  graphFixture,
  indexFixture,
  searchFixture,
  symbolFixture,
} from "./fixtures";

function mockApi(overrides: Partial<Api> = {}): Api {
  return {
    health: vi.fn().mockResolvedValue({ status: "ok", indexed: true, version: "0.3.0" }),
    index: vi.fn().mockResolvedValue(indexFixture),
    reindex: vi.fn().mockResolvedValue(indexFixture),
    search: vi.fn().mockResolvedValue(searchFixture),
    symbol: vi.fn().mockImplementation(async (id: string) => ({ ...symbolFixture, symbol_id: id })),
    graph: vi.fn().mockImplementation(async (id: string) => (id === CHECK_LIMIT ? graphCheckLimitFixture : graphFixture)),
    ...overrides,
  };
}

describe("workspace store", () => {
  let api: Api;
  beforeEach(() => {
    api = mockApi();
  });

  it("boots from health and index", async () => {
    const store = createWorkspaceStore(api);
    await store.getState().init();
    expect(store.getState().index?.symbols).toBe(65);
  });

  it("reports an unreachable backend", async () => {
    const store = createWorkspaceStore(mockApi({ health: vi.fn().mockRejectedValue(new Error("fetch failed")) }));
    await store.getState().init();
    expect(store.getState().connectionError).toMatch(/Cannot reach the Tracex API/);
  });

  it("search focuses the top hit and loads its symbol and graph together", async () => {
    const store = createWorkspaceStore(api);
    await store.getState().runSearch("check spending limit");
    const s = store.getState();
    expect(api.search).toHaveBeenCalledWith(
      "check spending limit",
      expect.objectContaining({ dense: true, bm25: true, graph: true }),
      expect.anything(),
    );
    expect(s.focusId).toBe(CHECK_LIMIT);
    expect(api.symbol).toHaveBeenCalledWith(CHECK_LIMIT);
    expect(api.graph).toHaveBeenCalledWith(CHECK_LIMIT, 1);
    expect(s.centerRequest).toBe(1); // the canvas recenters on the new focus
  });

  it("ignores stale focus responses (last click wins)", async () => {
    let release!: () => void;
    const slow = new Promise<void>((resolve) => (release = resolve));
    const store = createWorkspaceStore(
      mockApi({
        symbol: vi.fn().mockImplementation(async (id: string) => {
          if (id === "slow") await slow;
          return { ...symbolFixture, symbol_id: id };
        }),
      }),
    );
    const first = store.getState().focusSymbol("slow");
    await store.getState().focusSymbol(CHARGE);
    release();
    await first;
    expect(store.getState().focus?.symbol_id).toBe(CHARGE);
  });

  it("traces a selected callee to its exact call-site lines", async () => {
    const store = createWorkspaceStore(api);
    await store.getState().focusSymbol(CHARGE);
    store.getState().select({ kind: "callee", id: "billing/storage.py::PaymentRepository.save" });
    expect(currentHighlight(store.getState())).toEqual({ ranges: [[50, 50]], traced: true });
    store.getState().select({ kind: "callee", id: CHECK_LIMIT });
    expect(currentHighlight(store.getState())?.ranges).toEqual([[46, 46]]);
  });

  it("traces a selected caller to the focus header, and line anchors override", async () => {
    const store = createWorkspaceStore(api);
    await store.getState().focusSymbol(CHARGE);
    store.getState().select({ kind: "caller", id: "x" });
    expect(currentHighlight(store.getState())).toEqual({ ranges: [[44, 44]], traced: true });

    store.getState().anchorLine(48, false);
    store.getState().anchorLine(46, true);
    expect(currentHighlight(store.getState())).toEqual({ ranges: [[46, 48]], traced: false });
    expect(store.getState().selection).toEqual({ kind: "focus" });

    store.getState().select({ kind: "focus" });
    expect(currentHighlight(store.getState())).toEqual({ ranges: [[44, 53]], traced: false });
  });

  it("groups non-contiguous call lines into separate bands", () => {
    expect(toRanges([52, 46, 47, 52, 60])).toEqual([
      [46, 47],
      [52, 52],
      [60, 60],
    ]);
  });

  it("refuses to turn off both seed pillars and re-runs search on toggle", async () => {
    const store = createWorkspaceStore(api);
    await store.getState().runSearch("check spending limit");
    store.getState().togglePillar("dense");
    await vi.waitFor(() => expect(api.search).toHaveBeenCalledTimes(2));
    expect(store.getState().pillars.dense).toBe(false);
    store.getState().togglePillar("bm25");
    expect(store.getState().pillars.bm25).toBe(true);
    expect(store.getState().toast?.message).toMatch(/graph expansion needs seed/);
  });

  it("refuses rerank when the server has no cross-encoder", async () => {
    const store = createWorkspaceStore(api);
    await store.getState().init();
    store.getState().togglePillar("rerank");
    expect(store.getState().pillars.rerank).toBe(false);
    expect(store.getState().toast?.message).toMatch(/TRACEX_RERANKER/);
  });

  it("steps through hits with j / k and supports g d", async () => {
    const store = createWorkspaceStore(api);
    await store.getState().runSearch("check spending limit");
    store.getState().stepHit(1);
    await vi.waitFor(() => expect(store.getState().focusId).toBe(searchFixture.hits[1]?.symbol_id));
    store.getState().stepHit(-1);
    await vi.waitFor(() => expect(store.getState().focusId).toBe(CHECK_LIMIT));

    store.getState().goToDefinition();
    expect(store.getState().toast?.message).toMatch(/g d/);
    store.getState().select({ kind: "callee", id: CHARGE });
    store.getState().goToDefinition();
    await vi.waitFor(() => expect(store.getState().focusId).toBe(CHARGE));
  });

  it("merges +N expansions into the canvas", async () => {
    const store = createWorkspaceStore(api);
    await store.getState().focusSymbol(CHECK_LIMIT);
    const before = store.getState().graph!.nodes.length;
    await store.getState().expandNode(CHARGE, "callees");
    expect(store.getState().graph!.nodes.length).toBeGreaterThan(before);
  });
});
