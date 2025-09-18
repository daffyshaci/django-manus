import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    // Proxy API calls to Django backend during development to avoid CORS issues
    return [
      {
        source: "/v1/:path*",
        destination: "http://localhost:8000/api/v1/:path*",
      },
      {
        source: "/openapi.json",
        destination: "http://localhost:8000/api/openapi.json",
      },
    ];
  },
};

export default nextConfig;
