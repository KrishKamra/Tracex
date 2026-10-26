export type LineRange = readonly [start: number, end: number];

export function normalizeRange(a: number, b: number): LineRange {
  return a <= b ? [a, b] : [b, a];
}

export function rangeLabel([start, end]: LineRange): string {
  return start === end ? `L${start}` : `L${start}–${end}`;
}

export function rangeHash([start, end]: LineRange): string {
  return start === end ? `#L${start}` : `#L${start}-L${end}`;
}

/** Parse `#L12` or `#L12-L18` (also tolerates `#L12-18`). */
export function parseRangeHash(hash: string): LineRange | null {
  const match = /^#?L(\d+)(?:-L?(\d+))?$/.exec(hash.trim());
  if (!match) return null;
  const start = Number(match[1]);
  const end = match[2] ? Number(match[2]) : start;
  return normalizeRange(start, end);
}

export function permalink(origin: string, symbolId: string, range: LineRange): string {
  return `${origin}/?symbol=${encodeURIComponent(symbolId)}${rangeHash(range)}`;
}

/**
 * Line selection with Click / Shift+Click semantics: a plain click anchors a
 * single line; shift-click extends from the existing anchor.
 */
export function extendSelection(current: LineRange | null, line: number, shift: boolean): LineRange {
  if (!shift || !current) return [line, line];
  return normalizeRange(current[0], line);
}
