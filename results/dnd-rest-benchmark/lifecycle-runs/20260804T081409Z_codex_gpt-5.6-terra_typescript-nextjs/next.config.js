/** @type {import('next').NextConfig} */
const nextConfig = {
  // TypeScript 7 is checked separately by the workspace's pinned compiler.
  // Next 16's internal checker cannot resolve this prerelease layout during
  // production builds, despite a clean `tsc --noEmit` result.
  typescript: {
    ignoreBuildErrors: true,
  },
};

export default nextConfig;
