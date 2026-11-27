import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  // A second build can go to its own folder (PP_WEB_DIST=out-x) so a running server's web/out is not replaced.
  ...(process.env.PP_WEB_DIST ? { distDir: process.env.PP_WEB_DIST } : {}),
  trailingSlash: true,
  images: { unoptimized: true },
};

export default nextConfig;
