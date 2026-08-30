import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Cloud Run runs the app as a standalone server bundle, which keeps the
  // runtime image small and the cold start short.
  output: "standalone",
  reactStrictMode: true,
  // Pin the workspace root: without this Turbopack walks up past the repo and
  // picks up unrelated lockfiles, which changes what gets bundled in Docker.
  turbopack: { root: import.meta.dirname },
};

export default nextConfig;
