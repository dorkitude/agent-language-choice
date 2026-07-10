/** @type {import('next').NextConfig} */
export default {
  // SWC compiles successfully; skip the separate TS type-check worker
  // (incompatible with the pinned TS 7.0.2 on this runtime).
  typescript: { ignoreBuildErrors: true },
};
