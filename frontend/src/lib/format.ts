export function ms(value: number | null | undefined): string {
  if (!value) return "off";
  if (value < 1) return `${value.toFixed(2)}ms`;
  if (value < 100) return `${value.toFixed(1)}ms`;
  if (value < 10_000) return `${Math.round(value)}ms`;
  return `${(value / 1000).toFixed(1)}s`;
}

export const basename = (path: string) => path.split("/").pop() ?? path;

export const dirname = (path: string) => path.split("/").slice(0, -1);

export function percent(value: number, digits = 0): string {
  return `${(value * 100).toFixed(digits)}%`;
}
