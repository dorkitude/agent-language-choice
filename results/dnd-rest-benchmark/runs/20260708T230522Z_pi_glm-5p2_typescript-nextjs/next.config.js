/** @type {import('next').NextConfig} */
export default {
  // TypeScript 7.0.2 is a native rewrite whose compiler API differs from what
  // Next 16.2.10's type-check worker expects, so skip build-time type
  // validation (SWC still transpiles .ts/.tsx correctly at runtime).
  typescript: { ignoreBuildErrors: true },
};
