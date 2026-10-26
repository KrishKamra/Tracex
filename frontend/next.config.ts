import type { NextConfig } from "next";

// The browser talks to /api/v1 on the Next.js origin; requests are proxied to
// the FastAPI backend, so no CORS configuration is needed in development.
const API_URL = process.env.TRACEX_API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${API_URL}/api/v1/:path*` }];
  },
};

export default nextConfig;
