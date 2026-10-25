import { refreshAccessToken, isTokenExpired, getStoredToken } from "../auth/session";

export interface InvoiceSummary {
  id: string;
  period: string;
  totalCents: number;
  status: "paid" | "open" | "void";
}

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
  }
}

/** Typed HTTP client for the billing REST API. */
export class ApiClient {
  constructor(private readonly baseUrl: string) {}

  /** Send an authenticated request, transparently refreshing an expired access token. */
  async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    let token = getStoredToken();
    if (!token || isTokenExpired(token)) {
      token = await refreshAccessToken();
    }
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: { ...init.headers, Authorization: `Bearer ${token}` },
    });
    if (!response.ok) {
      throw new ApiError(response.status, await response.text());
    }
    return (await response.json()) as T;
  }

  getInvoices(accountId: string): Promise<InvoiceSummary[]> {
    return this.request<InvoiceSummary[]>(`/accounts/${accountId}/invoices`);
  }

  /** Start a hosted checkout page so the customer can enter card details. */
  createCheckoutSession(priceId: string, successUrl: string): Promise<{ url: string }> {
    return this.request("/checkout/sessions", {
      method: "POST",
      body: JSON.stringify({ priceId, successUrl }),
    });
  }
}
