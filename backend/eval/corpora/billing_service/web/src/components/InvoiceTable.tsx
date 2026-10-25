import { useMemo, useState } from "react";
import { useInvoices } from "../hooks/useInvoices";
import { formatCurrency } from "../utils/currency";
import { InvoiceSummary } from "../api/client";

type SortKey = "period" | "totalCents";

export function sortInvoices(invoices: InvoiceSummary[], key: SortKey, descending: boolean): InvoiceSummary[] {
  const sorted = [...invoices].sort((a, b) => (a[key] < b[key] ? -1 : a[key] > b[key] ? 1 : 0));
  return descending ? sorted.reverse() : sorted;
}

/** Table of the account's invoices with click-to-sort column headers. */
export function InvoiceTable({ accountId }: { accountId: string }) {
  const { invoices, loading, error } = useInvoices(accountId);
  const [sortKey, setSortKey] = useState<SortKey>("period");
  const [descending, setDescending] = useState(true);
  const rows = useMemo(() => sortInvoices(invoices, sortKey, descending), [invoices, sortKey, descending]);

  const toggleSort = (key: SortKey) => {
    setDescending(key === sortKey ? !descending : true);
    setSortKey(key);
  };

  if (loading) return <p>Loading invoices…</p>;
  if (error) return <p role="alert">Could not load invoices: {error.message}</p>;
  return (
    <table>
      <thead>
        <tr>
          <th onClick={() => toggleSort("period")}>Period</th>
          <th onClick={() => toggleSort("totalCents")}>Total</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((inv) => (
          <tr key={inv.id}>
            <td>{inv.period}</td>
            <td>{formatCurrency(inv.totalCents)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
