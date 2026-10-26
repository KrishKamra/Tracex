// Client-side mirror of backend/app/api/query_parser.py, used for live
// syntax highlighting in the command bar. It never decides results: the
// server re-parses the raw query.

export type SegmentKind = "symbol" | "route" | "path" | "text" | "space";

export interface Segment {
  kind: SegmentKind;
  text: string;
}

export function classifyToken(token: string): Exclude<SegmentKind, "space"> {
  if (token.length > 1) {
    if (token[0] === "@") return "symbol";
    if (token[0] === "#") return "route";
    if (token[0] === "/") return "path";
  }
  return "text";
}

/** Split a query into tokens and the whitespace between them, preserving every character. */
export function segmentQuery(query: string): Segment[] {
  const segments: Segment[] = [];
  for (const match of query.matchAll(/(\s+)|(\S+)/g)) {
    const [text, space] = match;
    segments.push({ kind: space ? "space" : classifyToken(text), text });
  }
  return segments;
}

export const PREFIX_HELP: { prefix: string; kind: Exclude<SegmentKind, "space" | "text">; label: string; example: string }[] = [
  { prefix: "@", kind: "symbol", label: "Symbol", example: "@check_limit" },
  { prefix: "#", kind: "route", label: "Route", example: "#/webhooks/stripe" },
  { prefix: "/", kind: "path", label: "Path", example: "/billing/ refund" },
];
