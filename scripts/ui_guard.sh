#!/bin/sh
# Fail if GraphDev UI files drifted from the graphdev-baseline tag, outside the allowlist.
set -e
cd "$(dirname "$0")/.."
git rev-parse --verify graphdev-baseline >/dev/null
changed=$(git diff --name-only graphdev-baseline -- modswarm/frontend/src/components/graph modswarm/frontend/src/components/layout modswarm/frontend/src/components/explorer modswarm/frontend/src/components/chat modswarm/frontend/src/components/ui modswarm/frontend/src/store modswarm/frontend/src/lib modswarm/frontend/src/types/graph.ts modswarm/frontend/src/app/new/page.tsx || true)
allow='modswarm/frontend/src/components/graph/edge-lines.tsx
modswarm/frontend/src/components/graph/node-cloud.tsx
modswarm/frontend/src/components/graph/graph-toggles.tsx
modswarm/frontend/src/components/graph/graph-canvas.tsx
modswarm/frontend/src/components/graph/impact-banner.tsx
modswarm/frontend/src/components/layout/app-header.tsx
modswarm/frontend/src/store/graph-store.ts
modswarm/frontend/src/types/graph.ts
modswarm/frontend/src/app/new/page.tsx'
bad=""
for f in $changed; do
  ok=0
  for a in $allow; do
    if [ "$f" = "$a" ]; then ok=1; fi
  done
  if [ "$ok" = "0" ]; then bad="$bad $f"; fi
done
if [ -n "$bad" ]; then
  echo "ui_guard failed:$bad"
  exit 1
fi
echo "ui_guard passed"
