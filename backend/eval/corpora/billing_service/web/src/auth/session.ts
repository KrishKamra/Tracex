const TOKEN_KEY = "billing.accessToken";

export function getStoredToken(): string | null {
  return window.localStorage.getItem(TOKEN_KEY);
}

/** Decode the JWT payload and check whether its `exp` claim is in the past. */
export function isTokenExpired(token: string, skewSeconds = 30): boolean {
  const payload = JSON.parse(atob(token.split(".")[1]));
  return payload.exp * 1000 < Date.now() + skewSeconds * 1000;
}

/** Exchange the refresh-token cookie for a new access token and store it. */
export async function refreshAccessToken(): Promise<string> {
  const response = await fetch("/auth/refresh", { method: "POST", credentials: "include" });
  if (!response.ok) {
    logout();
    throw new Error("session expired");
  }
  const { accessToken } = await response.json();
  window.localStorage.setItem(TOKEN_KEY, accessToken);
  return accessToken;
}

export function logout(): void {
  window.localStorage.removeItem(TOKEN_KEY);
  window.location.assign("/login");
}
