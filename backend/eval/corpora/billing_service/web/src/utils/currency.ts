/** Format an integer amount of cents as a localized currency string, e.g. 1999 -> "$19.99". */
export function formatCurrency(amountCents: number, currency = "USD", locale = "en-US"): string {
  return new Intl.NumberFormat(locale, { style: "currency", currency }).format(amountCents / 100);
}

/** Parse user-typed money like "1,234.50" into integer cents; returns null when invalid. */
export function parseAmount(input: string): number | null {
  const cleaned = input.replace(/[^0-9.]/g, "");
  if (!/^\d+(\.\d{1,2})?$/.test(cleaned)) {
    return null;
  }
  return Math.round(parseFloat(cleaned) * 100);
}
