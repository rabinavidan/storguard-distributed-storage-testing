# StorGuard

> **A production-grade reliability, chaos and performance-testing platform for distributed object storage — built in Python, with AI-powered analysis, full Allure evidence and a Jenkins CI/CD pipeline.**

---

## What This Project Proves

Distributed storage systems must survive partial failures without losing data or availability. StorGuard answers one engineering question with real automated evidence:

> **Can a 4-node MinIO cluster preserve data integrity, maintain S3 availability, and deliver acceptable performance when nodes fail, the network degrades, and disks fill up?**

The answer — proven across **186 automated tests in 10 layers** against a live cluster — is **yes**.

This is a recruiter-facing portfolio project demonstrating end-to-end SDET skills:
- Distributed systems understanding (erasure coding, quorum reads, network partitions)
- Multi-layer test architecture (unit → component → integration → chaos → security)
- CI/CD pipeline design (11-stage Jenkins, quality gates, Allure evidence)
- Infrastructure-as-code (Docker Compose, nginx, Prometheus, Grafana)
- AI integration (local LLMs for log analysis and chaos recommendations)

---

## Test Results — Live Cluster

```
186 passed · 0 failed · 0 skipped   (1m 9s)
```

| # | Layer | Tests | Marker | What it proves |
|---|---|---|---|---|
| L1 | **Unit** | 26 | `unit` | Models, integrity validator, quality gate — zero external deps |
| L2 | **Smoke** | 3 | `smoke` | Cluster reachable, bucket lifecycle, S3 round-trip — fast pipeline gate |
| L3 | **Functional** | 9 | `functional` | Full S3 CRUD, metadata, unicode keys, object replacement, 404 handling |
| L4 | **Performance** | 2 | `performance` | Concurrent throughput, P95/P99 latency, quality gate evaluation |
| L5 | **Resilience — Node Failure** | 2 | `resilience` | EC:2 quorum holds with 1/4 nodes down; SHA-256 intact post-recovery |
| L5 | **Resilience — Network Faults** | 4 | `resilience` | 200ms latency + 20–50% packet loss; boto3 retries absorb failures |
| L5 | **Resilience — Disk Pressure** | 3 | `resilience` | Disk fill → clean ENOSPC error → release → writes resume |
| L6 | **Security** | 19 | `security` | Auth rejection, namespace isolation, path traversal, injection, boundaries |
| L7 | **Race Conditions** | 63 | `race` | Seeded write/delete, overwrite/read, concurrent-write and node-restart/read races — every outcome classified allowed vs. forbidden, reproducible by seed |
| L8 | **Snapshot Simulation** | 6 | `snapshot` | Point-in-time create/list/restore/delete via server-side S3 copy; restore re-verifies SHA-256, survives multi-snapshot coexistence and node restart |
| L9 | **AI — Unit** | 49 | `unit` | Log analyzer, report summarizer, chaos advisor — fully mocked, zero Ollama required |
| L9 | **AI — Integration** | 12 | `ai` | Live gemma4:26b calls: log analysis, chaos advice, narrative generation |
| | **TOTAL** | **186** | | **All suites passing against live 4-node cluster (excludes `ai` marker when Ollama isn't running)** |

---

## System Architecture

```
╔══════════════════════════════════════════════════════════════════════════╗
║                        StorGuard Test Platform                           ║
║                                                                          ║
║  ┌──────────────────────────────────────────────────────────────────┐   ║
║  │                    Test Pyramid  (tests/)                         │   ║
║  │                                                                   │   ║
║  │    L9 AI Integration ──── live LLM calls via Ollama               │   ║
║  │    L8 Snapshot ─────────── point-in-time create/restore/delete    │   ║
║  │    L7 Race Conditions ─── seeded timing collisions, by seed       │   ║
║  │    L6 Security ─────────── auth · isolation · boundary inputs     │   ║
║  │    L5 Resilience ──────── node loss · network · disk pressure     │   ║
║  │    L4 Performance ─────── throughput · latency · quality gate     │   ║
║  │    L3 Functional ──────── S3 CRUD · metadata · edge cases         │   ║
║  │    L2 Smoke ───────────── health checks · bucket lifecycle        │   ║
║  │    L1 Unit ────────────── models · integrity · gate (no cluster)  │   ║
║  └──────────────────────────────────────────────────────────────────┘   ║
╚══════════════════════════════════╦═══════════════════════════════════════╝
                                   ║ boto3 · httpx · docker-py
                                   ▼
              ┌────────────────────────────────────┐
              │   nginx  :9000  (S3 API gateway)   │
              │   :9090  (MinIO Console proxy)      │
              │   least_conn  load balancer         │
              └────┬──────┬──────┬──────┬──────────┘
                   │      │      │      │        EC:2 erasure coding
              ┌────▼──┐ ┌─▼───┐ ┌▼────┐ ┌▼────┐  (survives 1-node loss)
              │minio1 │ │minio│ │minio│ │minio│
              │ /data │ │  2  │ │  3  │ │  4  │
              └───────┘ └─────┘ └─────┘ └─────┘
                   │                        │
              ┌────▼────────────────────────▼───┐
              │        Prometheus  :9091         │
              │   scrapes /minio/v2/metrics/*    │
              └────────────────┬────────────────┘
                               │
              ┌────────────────▼────────────────┐
              │    Grafana  :3030                │
              │    "StorGuard — MinIO Cluster"   │
              │    16 live panels, 10s refresh   │
              └─────────────────────────────────┘

              ┌─────────────────────────────────┐
              │   Ollama  :11434  (local LLM)    │
              │   gemma4:26b · qwen3-coder:30b   │
              │   Log analysis, chaos advice,    │
              │   executive narrative summaries  │
              └─────────────────────────────────┘

              ┌──────────────┐   ┌──────────────────────┐
              │ Jenkins :8080 │   │  Allure UI  :5252     │
              │ 11-stage CI  │   │  HTML reports +       │
              │ pipeline     │   │  per-step evidence    │
              └──────────────┘   └──────────────────────┘
```

---

## Technology Stack

### Infrastructure

| Technology | Version | Role |
|---|---|---|
| **MinIO** | RELEASE.2024-07-04 | 4-node distributed object storage with EC:2 erasure coding |
| **nginx** | 1.27-alpine | S3 API gateway + MinIO Console reverse proxy, `least_conn` LB |
| **Docker Compose** | v2 (no version key) | Multi-profile orchestration: `storage`, `monitoring`, `ci` |
| **Prometheus** | v2.53.0 | Metrics scraper — `/minio/v2/metrics/cluster` + `/node` |
| **Grafana** | 11.1.0 | 16-panel live dashboard (cluster health, IOPS, latency, erasure set quorum) |
| **Python** | 3.9.2 | Platform language (3.12 upgrade pending, boto3 warns after April 2026) |

### Python Libraries

| Library | Version | Role |
|---|---|---|
| **boto3** | 1.42 | S3 client — all object/bucket operations |
| **httpx** | 0.27 | Ollama LLM REST API calls and health checks |
| **docker-py** | 7.2 | Container lifecycle management; `exec_run` for `tc` fault injection |
| **paramiko** | 3.4 | SSH-based remote system diagnostics |
| **click** | 8.1 | CLI framework (`storguard` entrypoint — 12 commands) |
| **rich** | 13.7 | Terminal tables, spinners, live chaos demo, progress bars |
| **pyyaml** | 6.0 | Quality gate threshold configuration (`local.yaml`, `ci.yaml`) |
| **tenacity** | 9.0 | Retry-with-backoff for cluster health polling |
| **python-dotenv** | 1.0 | Environment variable management from `.env` |

### Testing Stack

| Library | Version | Role |
|---|---|---|
| **pytest** | 8.3.3 | Test runner, custom markers, fixtures, hooks |
| **pytest-xdist** | 3.5 | Parallel test execution across workers |
| **pytest-timeout** | 2.4 | Per-test and per-class timeout enforcement |
| **pytest-cov** | 5.0 | Coverage measurement and gate (`--cov-fail-under`) |
| **allure-pytest** | 2.16 | Allure integration: epic/feature/story/severity/title/step |

### AI / LLM Layer

| Technology | Role |
|---|---|
| **Ollama** | Local LLM runtime — zero cloud, zero API keys, data never leaves the machine |
| **gemma4:26b** | Primary model: log analysis, chaos recommendations, narrative summaries (Google, 26B) |
| **qwen3-coder:30b** | Code-aware analysis, 262k context window (Alibaba, 30B) |
| **httpx** | REST client wrapping the Ollama `/api/chat` endpoint |

### CI / Reporting

| Technology | Role |
|---|---|
| **Jenkins** | 11-stage declarative pipeline — lint → unit → deploy → smoke → functional → chaos → gate → publish |
| **Allure** | HTML reports with per-step evidence, `environment.properties`, `categories.json`, AI failure attachments |
| **ruff** | Linting (E, F, W, I, UP, B, SIM rules) |
| **black** | Code formatting |
| **mypy** | Static type checking (strict mode) |

---

## Allure Reporting — Step-Level Evidence

Every test uses `with allure.step(...)` to produce a drillable timeline in Allure. Each test is structured as:

```
Test: "Cluster serves reads during 1/4 node outage — EC:2 quorum holds"
  ├── Step: Upload 1 MB baseline object before fault injection
  ├── Step: Stop storguard-minio2 (1 of 4 nodes)
  │     ├── Step: Attach fault injection timestamp
  │     └── Step: Read object while node is down — quorum must hold
  ├── Step: Record cluster healthy timestamp after node restarts
  ├── Step: Verify post-recovery data integrity via SHA-256
  └── Step: Attach recovery timeline summary
             → Artifact: recovery-timeline.txt
```

This means a failure report shows the exact step that broke — not just a line number.

### Allure Label Hierarchy

```
Epic
 └── Feature
       └── Story
             └── Test (with @allure.title, @allure.severity)
                   └── Steps (with allure.step context managers)
                         └── Attachments (text artifacts, metrics, logs)
```

| Epic | Features |
|---|---|
| **Smoke** | Cluster Health |
| **Storage** | S3 CRUD, Edge Cases |
| **Performance** | Workload Engine |
| **Resilience** | Node Failure, Network Faults, Disk Pressure |
| **Security** | Auth Enforcement, Namespace Isolation, Boundary Inputs, Error Safety |
| **Integrity** | IntegrityValidator, Test Data Generator |
| **Quality Gate** | Threshold Evaluation |
| **Models** | CommandResult, OperationResult, RecoveryTimeline, GateResult |
| **AI — Ollama Client** | Configuration, Connectivity, Lifecycle |
| **AI — Log Analyzer** | Pattern Detection, Offline Fallback, AI Response Parsing |
| **AI — Report Summarizer** | Offline Fallback, AI Response Parsing, Report Schema |
| **AI — Chaos Advisor** | Offline Fallback, AI Response Parsing, Recommendation Format |
| **AI — Integration** | Ollama Runtime, Log Analyzer, Chaos Advisor, Report Summarizer |

---

## Chaos Engineering

Four fault injection scenarios implemented with real kernel-level mechanisms — not mocks.

| Scenario | Mechanism | What Is Proved |
|---|---|---|
| **Node failure** | `docker stop storguard-minio2` via docker-py | EC:2 quorum holds with 3/4 nodes; SHA-256 intact after restart |
| **Network latency** | `tc qdisc netem delay 200ms` inside container | S3 latency rises proportionally; boto3 retries absorb transients |
| **Packet loss** | `tc qdisc netem loss 20–50%` inside container | Error rate spikes then stabilises; data integrity preserved |
| **Disk pressure** | `fallocate -l 4096M /data/storguard_filler.bin` inside container | Writes return clean ENOSPC; reads unaffected; recovery verified |

### Live Chaos Timeline

```
T+0.0s    minio2 stopped
T+0.2s    container status: exited
T+10.3s   read during outage: OK  (10,016ms — MinIO reroutes after timeout)
T+10.3s   minio2 restarted
T+10.5s   minio2 running
T+10.5s   SHA-256 post-recovery: MATCH — zero data corruption
```

`ChaosController.restore_all()` runs in every fixture teardown as a safety net — cluster is always returned to healthy state regardless of test outcome.

---

## AI Integration

StorGuard uses **Ollama** — a fully local LLM runtime. Zero cloud dependency. Zero API keys. All inference runs on the same machine as the tests.

### What the AI Layer Does

| Module | CLI | Description |
|---|---|---|
| `log_analyzer.py` | `storguard ai analyze-logs` | Regex pre-scan (8 patterns) + LLM root-cause analysis on container logs |
| `report_summarizer.py` | `storguard ai summarize` | WorkloadMetrics / GateResult → plain-English executive narrative |
| `chaos_advisor.py` | `storguard ai advise` | Analyses cluster state and recommends which chaos scenario to inject next |
| `ollama_client.py` | *(all of the above)* | httpx wrapper for Ollama REST API with graceful offline degradation |

### Graceful Degradation

When Ollama is offline, **every AI feature falls back automatically**:
- Rule-based regex replaces LLM log analysis
- Built-in defaults replace AI chaos recommendations
- All 186 tests still pass — no test depends on Ollama unless it carries `@pytest.mark.ai`

### Auto-Attach on Test Failure

`conftest.py` contains a `pytest_runtest_makereport` hook: when any test fails, it calls the log analyzer on all 4 MinIO containers (with a 30s timeout) and attaches the AI anomaly report as an Allure artifact automatically.

### Models Available

| Model | Size | Strengths |
|---|---|---|
| `gemma4:26b` | 17.9 GB | General analysis, structured JSON output, thinking mode (Google) |
| `qwen3-coder:30b` | 18.5 GB | Code-aware analysis, 262k context window (Alibaba) |

---

## Observability — Prometheus + Grafana

The `monitoring` Docker Compose profile brings up Prometheus and Grafana alongside the MinIO cluster.

```bash
docker compose --profile storage --profile monitoring up -d
```

**Grafana dashboard at http://localhost:3030** (`admin / storguard_grafana_123`) includes 16 live panels:

| Row | Panels |
|---|---|
| Cluster overview | Health status · Nodes online · Drives online · Total objects · Total buckets · Usable free space |
| S3 traffic | Request rate (req/s) · Error rate (4xx / 5xx / auth-rejected) |
| Network | Throughput received (bytes/s) · Throughput sent (bytes/s) |
| Node resources | Memory per node (bytes) · CPU per node (cores) |
| Storage health | Disk usage % · Erasure set write quorum · In-flight S3 requests |
| I/O | Node read/write throughput · Scanner objects/s |

---

## Performance Benchmarks

Live numbers from local 4-node Docker cluster:

| Scenario | Workers | Objects | Throughput | Avg latency | P95 | P99 |
|---|---|---|---|---|---|---|
| 1 KB upload | 10 | 20 | 0.21 MB/s | 41 ms | 63 ms | 63 ms |
| **1 MB upload** | **10** | **20** | **67.34 MB/s** | **136 ms** | **188 ms** | **188 ms** |
| 1 MB mixed (upload + download + delete) | 10 | 20 | 45.77 MB/s | 119 ms | 172 ms | 172 ms |

### Quality Gate Thresholds

| Metric | Local (dev) | CI (Jenkins) |
|---|---|---|
| Max error rate | 5% | 2% |
| Max data corruptions | **0** | **0** |
| Max recovery time | 60s | 30s |
| Max P95 latency | 1,000ms | 800ms |
| Max performance regression | 20% | 20% |

---

## Security Test Coverage

19 tests across 4 classes — all run against the live cluster:

| Class | Tests | What Is Covered |
|---|---|---|
| `TestAuthEnforcement` | 6 | Wrong secret key · wrong access key · empty credentials rejected on upload/download/delete · health endpoint exposes no sensitive data |
| `TestNamespaceIsolation` | 2 | Objects in bucket A not visible from bucket B · cross-bucket download returns `NOT_FOUND` |
| `TestBoundaryInputs` | 6 | Path traversal (`../etc/passwd`, `%2e%2e%2f`) · max key length (1024 bytes) · oversized key (1025) · SQL injection in key · null bytes · 100 MB object upload |
| `TestErrorSafety` | 5 | Nonexistent bucket/key returns clean error on download · delete · list · upload · metadata — never HTTP 500 or unhandled exception |

---

## CI/CD — Jenkins Pipeline (11 Stages)

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Jenkinsfile — Declarative Pipeline                │
│                                                                      │
│  Stage 1   Checkout          Git clone + environment validation      │
│  Stage 2   Environment       Python · Docker · pip version check     │
│                                                                      │
│  Stage 3   Quality Gate ─── parallel ────────────────────────────── │
│              3a  ruff lint                                           │
│              3b  black format check                                  │
│              3c  mypy type check                                     │
│                                                                      │
│  Stage 4   Unit Tests        26 tests — no cluster required          │
│  Stage 5   Deploy            docker compose --profile storage up -d  │
│                              + wait-for-health.sh polling loop       │
│  Stage 6   Smoke Tests       3 tests — cluster reachable gate        │
│  Stage 7   Functional Tests  9 tests — S3 CRUD (pytest-xdist)        │
│  Stage 8   Performance       2 tests — throughput + quality gate     │
│  Stage 9   Chaos/Resilience  9 tests — node · network · disk         │
│                                                                      │
│  Stage 10  Publish           allure generate → Allure docker service │
│  Stage 11  Cleanup           docker compose down (always, even on ✗) │
└─────────────────────────────────────────────────────────────────────┘
```

Every stage that fails causes the pipeline to abort — except Stage 11, which always runs to guarantee cluster cleanup.

---

## Project Structure

```
.
├── CLAUDE.md                          Session context (project source of truth)
├── .env                               Active credentials (gitignored)
├── .env.example                       Template committed to git
├── pyproject.toml                     Build, deps, ruff/black/mypy config
├── pytest.ini                         Markers, timeout, addopts
├── Jenkinsfile                        11-stage declarative pipeline
│
├── storguard/                         Installable Python package
│   ├── models.py                      ALL shared dataclasses + enums (source of truth)
│   ├── clients/
│   │   ├── s3_client.py               boto3 wrapper → typed OperationResult
│   │   ├── docker_client.py           docker-py → container lifecycle + tc injection
│   │   └── linux_client.py            subprocess → system diagnostics
│   ├── ai/
│   │   ├── ollama_client.py           httpx REST wrapper, graceful offline fallback
│   │   ├── log_analyzer.py            Regex pre-scan + LLM root-cause analysis
│   │   ├── report_summarizer.py       Metrics/gate results → executive narrative
│   │   └── chaos_advisor.py           AI-powered chaos scenario recommendations
│   ├── chaos/
│   │   └── controller.py              Fault injection + restore_all() safety net
│   ├── concurrency/
│   │   └── race_runner.py             Seeded two-operation race runner + outcome classification
│   ├── integrity/
│   │   └── validator.py               SHA-256 round-trip + test data generation
│   ├── snapshot/
│   │   └── service.py                 Point-in-time create/list/restore/delete via server-side copy
│   ├── workloads/
│   │   └── engine.py                  ThreadPoolExecutor concurrent S3 + P95/P99
│   ├── quality_gate/
│   │   └── gate.py                    Multi-threshold evaluation → GateResult
│   ├── dashboard/
│   │   ├── monitor.py                 Rich Live terminal dashboard (real-time cluster view)
│   │   └── demo.py                    6-step visual chaos demo with AI narrative
│   └── cli/
│       └── main.py                    Click + Rich CLI (12 commands)
│
├── tests/
│   ├── conftest.py                    Session fixtures · auto-cleanup · AI failure hook
│   ├── unit/                          L1 — 26 tests, no cluster, no Ollama
│   │   ├── test_models.py             CommandResult · OperationResult · RecoveryTimeline · GateResult
│   │   ├── test_integrity.py          SHA-256 validator · test data generator
│   │   └── test_quality_gate.py       Multi-threshold gate evaluation
│   ├── integration/                   L2 — 3 smoke tests
│   │   └── test_smoke.py
│   ├── functional/                    L3 — 9 S3 CRUD tests
│   │   └── test_storage.py
│   ├── performance/                   L4 — 2 workload + quality gate tests
│   │   └── test_workload.py
│   ├── resilience/                    L5 — 9 chaos tests
│   │   ├── test_node_failure.py       minio2 stop + quorum + SHA-256 recovery
│   │   ├── test_network_faults.py     tc latency 200ms · packet loss 20–50%
│   │   └── test_disk_pressure.py      fallocate fill · ENOSPC · release
│   ├── security/                      L6 — 19 security tests
│   │   └── test_security.py
│   ├── race_conditions/               L7 — 63 seeded race tests
│   │   └── test_race_conditions.py    write/delete · overwrite/read · concurrent-write · restart/read
│   ├── snapshots/                     L8 — 6 snapshot lifecycle tests
│   │   └── test_snapshot.py           create/restore roundtrip · coexistence · node-restart · delete · list
│   └── ai/                            L9 — 61 AI tests (49 unit + 12 integration)
│       ├── conftest.py                OllamaClientBuilder · MetricsBuilder · require_ollama
│       ├── test_ollama_client.py      Config · connectivity · lifecycle
│       ├── test_log_analyzer.py       Pattern detection (parametrized) · AI parse · fallback
│       ├── test_report_summarizer.py  Narrative generation · schema · offline fallback
│       ├── test_chaos_advisor.py      Recommendations · AI parse · format
│       └── test_ai_integration.py    Live Ollama end-to-end tests
│
├── config/
│   ├── local.yaml                     Dev quality gate thresholds
│   └── ci.yaml                        Stricter CI quality gate thresholds
│
└── infrastructure/
    ├── docker-compose.yml             8 services: MinIO ×4 · nginx · Prometheus · Grafana · Jenkins · Allure ×2
    ├── nginx/nginx.conf               S3 load balancer + console reverse proxy
    ├── prometheus/prometheus.yml      Scrape config for cluster + per-node metrics
    ├── grafana/
    │   ├── provisioning/              Auto-provision datasource + dashboard on startup
    │   └── storguard-minio-dashboard.json  Custom 16-panel dashboard JSON
    └── scripts/
        ├── deploy.sh
        ├── destroy.sh
        └── wait-for-health.sh        Polls /minio/health/cluster with configurable deadline
```

---

## Key Design Decisions

| Decision | Reason |
|---|---|
| 4 MinIO nodes minimum | EC:2 erasure coding requires at least 4 drives for quorum |
| nginx in front of MinIO | Single S3 endpoint; realistic production topology; load balanced |
| Docker Compose profiles | `storage` runs without CI overhead; Jenkins brings full stack; `monitoring` is opt-in |
| `dataclass` over pydantic | Zero extra dependency; sufficient for typed result objects |
| `ThreadPoolExecutor` over asyncio | boto3 is synchronous; simpler; pytest-compatible |
| SHA-256 stored in S3 metadata on upload | Server-side integrity check without re-downloading for comparison |
| `restore_all()` in every fixture teardown | Cluster is always healthy after any test, pass or fail — no leaked faults |
| Ollama over cloud LLMs | Zero cost, zero latency, no API keys, data never leaves the machine |
| AI graceful fallback | All 186 tests pass whether Ollama is running or not — AI is additive, not required |
| `from __future__ import annotations` everywhere | Python 3.9 compatibility — defers type hint evaluation |
| `with allure.step(...)` in every test | Drillable Allure timeline — failure shows exact step, not just line number |
| Conftest AI hook with 30s timeout | AI log analysis on failure never blocks the suite — fails fast and moves on |

---

## Quick Start

```bash
# 1. Start MinIO cluster
cd infrastructure
docker compose --profile storage up -d

# 2. Verify cluster health
curl -s http://localhost:9000/minio/health/cluster    # expect HTTP 200

# 3. Install StorGuard
pip install -e ".[dev]"

# 4. Run all 186 tests
python -m pytest tests/ -m "not ai" --tb=short

# 5. Generate Allure report
python -m pytest tests/ -m "not ai" --alluredir=allure-results
allure generate allure-results --clean -o allure-report
allure open allure-report

# 6. Run specific test layers
python -m pytest -m smoke                            # L2 — fast cluster gate
python -m pytest -m functional                       # L3 — S3 CRUD
python -m pytest -m resilience                       # L5 — chaos scenarios
python -m pytest -m security                         # L6 — security suite
python -m pytest -m race                             # L7 — seeded race conditions
python -m pytest -m snapshot                         # L8 — snapshot create/restore
python -m pytest -m ai                               # L9 — requires Ollama + model

# 7. AI features (Ollama running on localhost:11434)
storguard ai status                                  # list installed models
storguard ai analyze-logs --container storguard-minio1
storguard ai advise
storguard ai summarize --metrics baselines/latest.json

# 8. Visual tools
storguard monitor                                    # real-time Rich terminal dashboard
storguard demo                                       # 6-step live chaos demo with AI narrative

# 9. Observability
docker compose --profile storage --profile monitoring up -d
# Grafana: http://localhost:3030  (admin / storguard_grafana_123)
# Prometheus: http://localhost:9091

# 10. CI/CD
docker compose --profile ci up -d                   # Jenkins + Allure
# Jenkins: http://localhost:8080  (admin / storguard_jenkins_123)
# Allure UI: http://localhost:5252
```

---

## Service Endpoints

| Service | URL | Credentials |
|---|---|---|
| S3 API | http://localhost:9000 | storguard / storguard_secret_123 |
| MinIO Console | http://localhost:9090 | storguard / storguard_secret_123 |
| Grafana | http://localhost:3030 | admin / storguard_grafana_123 |
| Prometheus | http://localhost:9091 | — |
| Ollama API | http://localhost:11434 | — |
| Jenkins | http://localhost:8080 | admin / storguard_jenkins_123 |
| Allure API | http://localhost:5050 | — |
| Allure UI | http://localhost:5252 | — |

---

## Pytest Markers

| Marker | Description |
|---|---|
| `unit` | Pure unit tests — no cluster, no Ollama, no Docker |
| `component` | Single-module tests with mocked collaborators |
| `smoke` | Fast blocking health checks — fail the pipeline early |
| `functional` | Full S3 CRUD and edge cases — requires live cluster |
| `integration` | Python client → S3 protocol → storage nodes |
| `integrity` | SHA-256 and size validation after transfer and recovery |
| `resilience` | Node loss, network faults, disk pressure |
| `race` | Seeded concurrent-timing collisions classified as allowed/forbidden |
| `snapshot` | Point-in-time create/list/restore/delete via server-side S3 copy |
| `performance` | Concurrent throughput and latency percentiles |
| `security` | Auth enforcement, permissions, input boundary validation |
| `negative` | Missing objects, invalid input, unavailable services |
| `boundary` | Edge-case and boundary-value inputs |
| `ai` | Ollama integration tests — auto-skipped when model not installed |
