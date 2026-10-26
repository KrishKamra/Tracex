// Real payloads captured from the FastAPI backend (deterministic hashing
// embedder over backend/eval/corpora/billing_service).
import type { GraphResponse, IndexSummary, SearchResponse, SymbolDetail } from "@/lib/types";

import graphJson from "./fixtures/graph.json";
import graphCheckLimitJson from "./fixtures/graph_check_limit.json";
import indexJson from "./fixtures/index.json";
import searchJson from "./fixtures/search.json";
import symbolJson from "./fixtures/symbol.json";

export const indexFixture = indexJson as IndexSummary;
export const searchFixture = searchJson as SearchResponse;
export const symbolFixture = symbolJson as SymbolDetail;
export const graphFixture = graphJson as GraphResponse;
export const graphCheckLimitFixture = graphCheckLimitJson as GraphResponse;

export const CHARGE = "billing/payments.py::charge_customer";
export const CHECK_LIMIT = "billing/limits.py::check_limit";
