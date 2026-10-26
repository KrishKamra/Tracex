import { describe, expect, it } from "vitest";

import { encodeSymbolId, searchUrl } from "@/lib/api";
import { ms } from "@/lib/format";
import { callLinesTo, FOCUS_W, fromResponse, mergeExpansion, NODE_H, nodeWidth } from "@/lib/graph-layout";
import { extendSelection, parseRangeHash, permalink, rangeHash, rangeLabel } from "@/lib/permalink";
import { classifyToken, segmentQuery } from "@/lib/query-syntax";
import { contributionBreakdown, justification, originLabel, splitIdentifier } from "@/lib/rrf";
import type { SearchHit } from "@/lib/types";

import { CHARGE, CHECK_LIMIT, graphCheckLimitFixture, graphFixture, searchFixture } from "./fixtures";

describe("query syntax", () => {
  it("classifies prefixes like the backend parser", () => {
    expect(classifyToken("@save")).toBe("symbol");
    expect(classifyToken("#/webhooks")).toBe("route");
    expect(classifyToken("/billing/")).toBe("path");
    expect(classifyToken("@")).toBe("text"); // bare sigil is text
    expect(classifyToken("refund")).toBe("text");
  });

  it("preserves every character, including whitespace runs", () => {
    const query = "@handle  verify /api ";
    const segments = segmentQuery(query);
    expect(segments.map((s) => s.text).join("")).toBe(query);
    expect(segments.map((s) => s.kind)).toEqual(["symbol", "space", "text", "space", "path", "space"]);
  });
});

describe("api urls", () => {
  it("builds search URLs with pillar toggles", () => {
    const url = new URL(searchUrl("@save refund", { dense: false, bm25: true, graph: true, rerank: false }), "http://x");
    expect(url.pathname).toBe("/api/v1/search");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      q: "@save refund",
      dense: "false",
      bm25: "true",
      graph: "true",
      rerank: "false",
      top_k: "20",
    });
  });

  it("keeps slashes in symbol ids but encodes everything else", () => {
    expect(encodeSymbolId("web/src/a b.ts::Foo.bar")).toBe("web/src/a%20b.ts%3A%3AFoo.bar");
  });
});

describe("permalinks and line selection", () => {
  it("round-trips range hashes", () => {
    expect(rangeHash([12, 18])).toBe("#L12-L18");
    expect(rangeHash([7, 7])).toBe("#L7");
    expect(parseRangeHash("#L12-L18")).toEqual([12, 18]);
    expect(parseRangeHash("#L18-12")).toEqual([12, 18]);
    expect(parseRangeHash("#L5")).toEqual([5, 5]);
    expect(parseRangeHash("#nope")).toBeNull();
    expect(rangeLabel([3, 9])).toBe("L3–9");
  });

  it("implements click to anchor and shift+click to extend", () => {
    expect(extendSelection(null, 10, true)).toEqual([10, 10]);
    expect(extendSelection([10, 10], 4, true)).toEqual([4, 10]);
    expect(extendSelection([4, 10], 20, false)).toEqual([20, 20]);
  });

  it("builds shareable links", () => {
    expect(permalink("http://localhost:3000", CHARGE, [44, 53])).toBe(
      "http://localhost:3000/?symbol=billing%2Fpayments.py%3A%3Acharge_customer#L44-L53",
    );
  });
});

describe("RRF explainability", () => {
  const top = searchFixture.hits[0] as SearchHit;

  it("splits the fused score into per-pillar shares that sum to one", () => {
    const parts = contributionBreakdown(top);
    expect(parts.map((p) => p.pillar)).toEqual(["dense", "bm25", "graph"]);
    expect(parts.reduce((a, p) => a + p.share, 0)).toBeCloseTo(1, 10);
    expect(parts.reduce((a, p) => a + p.value, 0)).toBeCloseTo(top.rrf_score, 10);
    expect(parts[0]?.rank).toBe(top.dense_rank);
  });

  it("labels exact identifier matches and explains ranks", () => {
    expect(originLabel(top)).toBe("Exact"); // "check" and "limit" cover check_limit
    expect(originLabel(searchFixture.hits[2] as SearchHit)).toBe("Keyword"); // charge_customer
    expect(originLabel({ ...top, name: "other" })).toBe("Keyword");
    expect(splitIdentifier("parseHTTPResponse2xx")).toEqual(["parse", "http", "response", "2", "xx"]);
    expect(originLabel({ ...top, match_origin: ["graph"] })).toBe("Call Graph");
    expect(originLabel({ ...top, match_origin: ["filter"] })).toBe("Filter");
    expect(justification(top).join(" ")).toMatch(/embedding similarity.*BM25 on check, spending, limit/);
  });
});

describe("graph layout", () => {
  it("converts API graphs and derives +N counts from fan-in / fan-out", () => {
    const flow = fromResponse(graphCheckLimitFixture);
    const fetchUsage = flow.nodes.find((n) => n.id === "billing/limits.py::fetch_usage");
    expect(fetchUsage?.data.hidden_callees).toBe(fetchUsage?.data.fan_out); // its callees are off-canvas
    const focus = flow.nodes.find((n) => n.id === CHECK_LIMIT);
    expect(focus?.data.hidden_callers).toBe(0);
    expect(callLinesTo(flow, CHECK_LIMIT, "billing/limits.py::fetch_usage").length).toBeGreaterThan(0);
  });

  it("lays out callers above, focus centred, callees below in a two-column grid", () => {
    const flow = fromResponse(graphFixture); // charge_customer: 0 callers, 8 callees
    const focus = flow.nodes.find((n) => n.data.role === "focus")!;
    expect(focus.position.x).toBe(-FOCUS_W / 2);
    const callees = flow.nodes.filter((n) => n.data.role === "callee");
    expect(callees.every((n) => n.position.y > focus.position.y)).toBe(true);
    expect(new Set(callees.map((n) => n.position.x)).size).toBe(2); // two columns
    const caller = fromResponse(graphCheckLimitFixture).nodes.find((n) => n.data.role === "caller")!;
    const checkFocus = fromResponse(graphCheckLimitFixture).nodes.find((n) => n.data.role === "focus")!;
    expect(caller.position.y).toBeLessThan(checkFocus.position.y);
  });

  it("merges a +N expansion into the next layer without collisions", () => {
    const flow = fromResponse(graphCheckLimitFixture);
    const anchor = flow.nodes.find((n) => n.data.role === "caller");
    expect(anchor?.id).toBe(CHARGE);
    // charge_customer's callees (besides check_limit) are off-canvas; expanding adds them one layer below it.
    const merged = mergeExpansion(flow, CHARGE, graphFixture, "callees");
    const added = merged.nodes.filter((n) => !flow.nodes.some((o) => o.id === n.id));
    expect(added.length).toBeGreaterThan(0);
    const mergedAnchor = merged.nodes.find((n) => n.id === CHARGE)!;
    for (const n of added) {
      expect(n.data.depth).toBe(anchor!.data.depth + 1);
      expect(n.data.role).toBe("callee");
      expect(n.position.y).toBeGreaterThan(mergedAnchor.position.y);
    }
    const overlaps = merged.nodes.some((a, i) =>
      merged.nodes.some(
        (b, j) =>
          i < j &&
          Math.abs(a.position.y - b.position.y) < NODE_H &&
          a.position.x < b.position.x + nodeWidth(b) &&
          b.position.x < a.position.x + nodeWidth(a),
      ),
    );
    expect(overlaps).toBe(false);
    // Edges from charge_customer to its new callees now exist, so its +N shrinks to zero.
    const after = merged.nodes.find((n) => n.id === CHARGE);
    expect(after?.data.hidden_callees).toBe(0);
    expect(mergeExpansion(merged, CHARGE, graphFixture, "callees").nodes.length).toBe(merged.nodes.length);
  });
});

describe("format", () => {
  it("formats latencies", () => {
    expect(ms(0)).toBe("off");
    expect(ms(0.42)).toBe("0.42ms");
    expect(ms(86.3)).toBe("86.3ms");
    expect(ms(666.3)).toBe("666ms");
    expect(ms(12_500)).toBe("12.5s");
  });
});
