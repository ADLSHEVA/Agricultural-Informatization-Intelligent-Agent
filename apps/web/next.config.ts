import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output:
    process.env.ORIGIN_STANDALONE_BUILD === "1" ? "standalone" : undefined,
};

export default nextConfig;
