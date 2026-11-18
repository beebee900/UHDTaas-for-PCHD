#!/bin/sh
# Registration entries: the SPIRE agents (node entry), then one SVID per ATRA workload,
# selected by namespace and service account (spiffe://atra.local/ns/atra/sa/<service>).
set -e
server() { kubectl exec -n spire spire-server-0 -- /opt/spire/bin/spire-server "$@"; }
agent=spiffe://atra.local/ns/spire/sa/spire-agent
server entry create -node -spiffeID "$agent" \
  -selector k8s_psat:cluster:atra -selector k8s_psat:agent_ns:spire \
  -selector k8s_psat:agent_sa:spire-agent
for svc in edge ahdt population apdt channels; do
  server entry create -parentID "$agent" -spiffeID "spiffe://atra.local/ns/atra/sa/$svc" \
    -selector k8s:ns:atra -selector "k8s:sa:$svc"
done
