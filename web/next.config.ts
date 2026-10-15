import type { NextConfig } from "next";

const API = process.env.HACKFRONT_API ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  // gzip would buffer the /api/investigate SSE stream (verified); this is a local tool, so no compression.
  compress: false,
  // Syncs and investigations are long requests; the default proxy timeout is 30s.
  experimental: { proxyTimeout: 10 * 60_000 },
  // The FastAPI backend serves /api/*; same-origin from the browser, so no CORS.
  rewrites: async () => [{ source: "/api/:path*", destination: `${API}/api/:path*` }],
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
