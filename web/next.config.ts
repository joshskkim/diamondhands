import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emit a self-contained server bundle (.next/standalone/server.js) for a small
  // production image — see web/Dockerfile.
  output: "standalone",
};

export default nextConfig;
