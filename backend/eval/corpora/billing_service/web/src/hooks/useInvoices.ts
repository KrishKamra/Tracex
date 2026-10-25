import { useEffect, useState } from "react";
import { ApiClient, InvoiceSummary } from "../api/client";

const client = new ApiClient("/api/v1");

/** React hook that loads an account's invoices and exposes loading / error state. */
export function useInvoices(accountId: string) {
  const [invoices, setInvoices] = useState<InvoiceSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let cancelled = false;
    client
      .getInvoices(accountId)
      .then((data) => !cancelled && setInvoices(data))
      .catch((err) => !cancelled && setError(err))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [accountId]);

  return { invoices, loading, error };
}
