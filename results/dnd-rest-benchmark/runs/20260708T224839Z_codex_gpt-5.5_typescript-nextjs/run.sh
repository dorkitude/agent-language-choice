#!/usr/bin/env bash
set -euo pipefail

# Next 16 still probes for the TypeScript 5 compiler API path. The pinned
# TypeScript 7 package has a different layout, but dev mode only needs these
# values for setup when SWC/Turbopack compiles the app routes.
if [ ! -f node_modules/typescript/lib/typescript.js ]; then
  mkdir -p node_modules/typescript/lib
  cat > node_modules/typescript/lib/typescript.js <<'EOF'
import versionModule from "./version.cjs";

export const version = versionModule.version || versionModule.default || "7.0.2";
export const ModuleKind = {
  CommonJS: 1,
  AMD: 2,
  ES2020: 6,
  ESNext: 99,
  Node16: 100,
  NodeNext: 199,
  Preserve: 200,
};
export const ModuleResolutionKind = {
  NodeJs: 2,
  Node10: 2,
  Node12: 2,
  Node16: 3,
  NodeNext: 99,
  Bundler: 100,
};
export const JsxEmit = {
  ReactJSX: 4,
};
EOF
fi

next dev -H 127.0.0.1 -p "$PORT"
