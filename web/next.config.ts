import type { NextConfig } from "next";

// /api/* is served by app/api/[...path]/route.ts, a server-side proxy to the FastAPI backend (HACKFRONT_API,
// HACKFRONT_API_TOKEN). It replaced a rewrite so the token stays server-side and long streams get a long timeout.
const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  // gzip would buffer the /api/investigate SSE stream (verified); this is a local tool, so no compression.
  compress: false,
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
