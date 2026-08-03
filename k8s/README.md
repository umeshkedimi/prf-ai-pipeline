# Kubernetes manifests

The same 12 services `docker-compose.yml` runs, as Kubernetes objects. Structured
as a Kustomize base plus environment overlays so the base stays cloud-neutral.

```
k8s/
  kind-cluster.yaml     cluster definition (node port mappings)
  base/                 cloud-neutral: Deployments, Services, ConfigMaps,
                        StatefulSet, PVC, migration Job
  overlays/kind/        local-only: imagePullPolicy, NodePorts, host Ollama
```

Nothing in `base/` names kind, Docker Desktop, or a cloud. Everything that would
change on EKS is isolated in an overlay — which is the whole point of the split.

## Quickstart

Requires Docker, [kind](https://kind.sigs.k8s.io/), `kubectl`, and Ollama running
on the host with `qwen2.5:14b` and `llama3.1:8b` pulled.

```bash
# 1. Cluster
kind create cluster --config k8s/kind-cluster.yaml

# 2. Image — kind nodes run their own containerd, so it must be loaded in
docker build -t prf-backend:local ./backend
kind load docker-image prf-backend:local --name prf

# 3. Manifests
kubectl kustomize --load-restrictor LoadRestrictionsNone k8s/overlays/kind \
  | kubectl apply -f -

# 4. Secrets — created out-of-band, never committed (see below)
kubectl -n prf create secret generic prf-api-keys \
  --from-literal=OPENAI_API_KEY=... \
  --from-literal=GOOGLE_API_KEY=... \
  --from-literal=ANTHROPIC_API_KEY=... \
  --from-literal=LITELLM_MASTER_KEY=sk-prf-local

kubectl -n prf get pods -w
```

The `prf-migrate` Job provisions everything on first apply: `alembic upgrade
head`, 12 seed donors, and 31 embedded knowledge chunks. All three steps are
idempotent, so `kubectl delete job prf-migrate` and re-apply is safe.

| | Host URL |
|---|---|
| API | http://localhost:18000/docs |
| Grafana | http://localhost:13000 |
| Jaeger | http://localhost:16687 |
| Prometheus | http://localhost:19090 |

Ports are deliberately *not* 8000/3000/16686 — docker-compose binds those, and a
disposable cluster shouldn't disturb a working stack. Both run at once.

Teardown is total: `kind delete cluster --name prf`.

### Why the `--load-restrictor` flag

The Kustomize base generates ConfigMaps directly from `litellm/config.yaml` and
`observability/` rather than keeping copies, so the cluster and docker-compose
can't drift. Those files live outside `k8s/`, which Kustomize blocks by default.
`kubectl apply -k` doesn't accept the flag, hence piping `kubectl kustomize`
through `kubectl apply -f -`.

The alternative — duplicating the config into the manifests — trades a CLI flag
for a silent drift risk. The flag is the better deal.

### Secrets

`prf-api-keys` is **not** in the manifests, and that is a correction rather than
an omission. It began as a committed placeholder with empty values, which was
wrong in a way only the second apply revealed: `kubectl apply` faithfully
restored the empty placeholder over the real keys and broke every pod that had
been working.

On EKS this is the seam where External Secrets Operator or the Secrets Store CSI
driver pulls from AWS Secrets Manager. Same boundary, real implementation.

## What this is verified to do

Confirmed against a live kind cluster, not asserted:

- All 12 pods reach `Running`, zero restarts.
- A full d-0001 workflow via the API NodePort completes through `pdf_generation`,
  with all six pipeline agents present.
- `GET /workflow/{id}/pdf` returns a real PDF — which also proves the shared PVC
  handoff, since `celery-worker` writes it and `api` serves it.
- Per-agent token accounting lands in `agent_audit_log` through the in-cluster
  LiteLLM proxy, with `pdf_generation` correctly recording none.
- Jaeger lists **both** `prf-api` and `prf-celery-worker`, so trace context still
  propagates across the Celery handoff.

### Three bugs the cluster found that compose never did

1. **LiteLLM OOMKilled six times** (exit 137) on a 1Gi limit. Compose sets no
   memory limit at all, so the process just took what it needed; declaring
   limits is what surfaced the real footprint. Now 2Gi.
2. **The `celery-worker` liveness probe restarted a healthy worker.** An `exec`
   probe runs without a shell, so `celery@$(hostname)` was passed as a literal
   and the probe asked for a node that cannot exist. Now wrapped in `sh -c`.
3. **The image shipped `ingest_knowledge.py` without its corpus.** Never noticed
   under compose, where ingest was always run from the host via `uv run`. An
   immediate `FileNotFoundError` the first time a Job tried to provision a fresh
   database. Fixed in the Dockerfile.

## What would change on EKS

The base applies as-is; an `overlays/eks/` would add:

| Concern | kind | EKS |
|---|---|---|
| Images | `kind load`, `imagePullPolicy: Never` | ECR, with pull permissions |
| Ingress | NodePort + host port mappings | ALB via AWS Load Balancer Controller |
| Storage class | local-path (cluster default) | `gp3` via EBS CSI |
| Secrets | `kubectl create secret` | External Secrets / Secrets Store CSI |
| Pod AWS access | n/a | IRSA-annotated ServiceAccount |
| Ollama | host via `host.docker.internal` | in-cluster Deployment, or Bedrock behind the same proxy |

**One thing genuinely doesn't port: the shared `prf-storage` PVC.**
`ReadWriteOnce` means one *node*, so on single-node kind both `api` and
`celery-worker` mount it happily. On multi-node EKS the scheduler can separate
them and the second pod hangs in `ContainerCreating` forever — an EBS volume is
zonal and single-attach. The fixes are EFS (real ReadWriteMany) or, properly,
S3 with presigned URLs. The latter is an application change, not a manifest
change, which is why it is documented here rather than quietly patched.
