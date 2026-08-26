# StorGuard — Claude Code Context File

> This file is the single source of truth for every Claude Code session on this project.
> Read it at the start of every session. Update it whenever something material changes.
> Never delete history entries — append only.

---

## Project Identity

| Field | Value |
|---|---|
| Name | StorGuard |
| Repo | `storguard-distributed-storage-testing` |
| Description | Python reliability, chaos and performance-testing platform for distributed storage on Linux |
| Working dir | `C:\Users\user\PycharmProjects\MinIO_SorageGuard_Linux_Python` |
| Version | 0.1.0 |
| Python | 3.9.2 (system — upgrade to 3.12 is pending, boto3 warns after April 2026) |
| Plan source | `C:\Users\user\Downloads\storguard_recruiter_ready_project_plan.pdf` |

---

## Purpose

Recruiter-facing portfolio project. Demonstrates:
- Python infrastructure automation (pytest, Linux, S3, Docker)
- Chaos engineering (node failure, network faults, disk pressure)
- Distributed systems reliability (MinIO erasure coding, quorum reads)
- CI/CD quality gates (Jenkins, Allure evidence)

**The answer it proves:** can a distributed storage cluster preserve data, availability and acceptable performance when infrastructure starts failing?

---

## Stack

| Layer | Technology | Notes |
|---|---|---|
| Language | Python 3.9.2 | Target 3.12 — currently 3.9 only available |
| Testing | Pytest 8.3.3, pytest-xdist, pytest-timeout | |
| Storage | MinIO `RELEASE.2024-07-04T14-25-45Z` | 4-node distributed, erasure coding |
| Gateway | nginx 1.27-alpine | Load balancer across 4 MinIO nodes |
| Infrastructure | Docker Compose (no version key) | storguard-net bridge network |
| Clients | boto3 1.42.97, httpx, paramiko, docker-py 7.2.0 | |
| CI/CD | Jenkins (Jenkinsfile written, not yet wired) | 11-stage pipeline |
| Reporting | allure-pytest 2.16.0 | Allure docker service available |
| Quality | ruff, black, mypy | In pyproject.toml dev deps |
| CLI | Click + Rich | `storguard` entrypoint |

---

## Docker Ecosystem

### Services (all on `storguard-net`)

| Container | Image | Port | Profile | Status |
|---|---|---|---|---|
| storguard-minio1 | minio:RELEASE.2024-07-04 | 9101→9001 (console) | storage | healthy |
| storguard-minio2 | minio:RELEASE.2024-07-04 | — | storage | healthy |
| storguard-minio3 | minio:RELEASE.2024-07-04 | — | storage | healthy |
| storguard-minio4 | minio:RELEASE.2024-07-04 | — | storage | healthy |
| storguard-gateway | nginx:1.27-alpine | 9000 (S3), 9090 (console) | storage | healthy |
| storguard-jenkins | jenkins/jenkins:lts-jdk17 | 8080, 50000 | ci | not started |
| storguard-allure | allure-docker-service:2.27.0 | 5050 | ci | not started |
| storguard-allure-ui | allure-docker-service-ui:7.0.3 | 5252 | ci | not started |

### Compose Commands

```bash
# From infrastructure/ directory:
docker compose --profile storage up -d          # MinIO cluster + gateway
docker compose --profile ci up -d               # Jenkins + Allure
docker compose --profile storage --profile ci up -d  # Full ecosystem
docker compose --profile storage down           # Stop cluster
VOLUMES=true ./scripts/destroy.sh              # Stop + wipe volumes
```

### Endpoints

| Service | URL | Credentials |
|---|---|---|
| S3 API | http://localhost:9000 | storguard / storguard_secret_123 |
| MinIO Console | http://localhost:9090 | storguard / storguard_secret_123 |
| Jenkins | http://localhost:8080 | admin / storguard_jenkins_123 |
| Allure UI | http://localhost:5252 | — |
| Allure API | http://localhost:5050 | — |

---

## Repository Structure

```
.
├── CLAUDE.md                          ← this file
├── .env                               ← active env (gitignored)
├── .env.example                       ← template committed to git
├── .gitignore
├── pyproject.toml                     ← build, deps, ruff/black/mypy config
├── pytest.ini                         ← markers, timeout, addopts
├── Jenkinsfile                        ← 11-stage declarative pipeline
│
├── config/
│   ├── local.yaml                     ← local thresholds + endpoints
│   └── ci.yaml                        ← stricter CI thresholds
│
├── infrastructure/
│   ├── docker-compose.yml             ← full ecosystem (no version key)
│   ├── nginx/nginx.conf               ← S3 LB + console proxy
│   ├── jenkins/plugins.txt
│   └── scripts/
│       ├── deploy.sh
│       ├── destroy.sh
│       └── wait-for-health.sh         ← polls /minio/health/cluster
│
├── storguard/                         ← installable Python package
│   ├── __init__.py                    ← version = "0.1.0"
│   ├── models.py                      ← ALL shared dataclasses + enums
│   ├── cli/main.py                    ← Click CLI (storguard entrypoint)
│   ├── clients/
│   │   ├── s3_client.py               ← boto3 wrapper → OperationResult
│   │   ├── linux_client.py            ← subprocess → CommandResult
│   │   └── docker_client.py           ← docker-py → ContainerState
│   ├── workloads/engine.py            ← ThreadPoolExecutor concurrent S3
│   ├── chaos/controller.py            ← fault injection + restore_all()
│   ├── integrity/validator.py         ← SHA-256 round-trip + generate_test_data()
│   └── quality_gate/gate.py           ← threshold evaluation → GateResult
│
└── tests/
    ├── conftest.py                    ← session fixtures, auto-attach on fail
    ├── unit/                          ← 26 tests, no external deps
    │   ├── test_models.py
    │   ├── test_integrity.py
    │   └── test_quality_gate.py
    ├── integration/
    │   └── test_smoke.py              ← 3 tests (smoke marker)
    ├── functional/
    │   └── test_storage.py            ← 9 tests (functional + negative)
    ├── performance/
    │   └── test_workload.py           ← 2 tests (performance marker)
    ├── resilience/
    │   └── test_node_failure.py       ← 2 tests (resilience marker)
    └── security/
        └── __init__.py                ← STUB — needs tests (see backlog)
```

---

## Package & Key Models

### `storguard/models.py` — source of truth for all types

```
OperationStatus   enum  SUCCESS | FAILED | TIMEOUT | UNAUTHORIZED | NOT_FOUND
FailureCategory   enum  DNS_RESOLUTION_FAILED | TCP_CONNECTION_REFUSED |
                        TCP_CONNECTION_TIMEOUT | TLS_HANDSHAKE_FAILED |
                        HTTP_AUTHENTICATION_FAILED | S3_SERVICE_UNAVAILABLE |
                        STORAGE_OPERATION_TIMEOUT | DATA_INTEGRITY_FAILED
FaultType         enum  NODE_STOP | NODE_RESTART | NETWORK_LATENCY |
                        PACKET_LOSS | DISK_PRESSURE | CPU_LIMIT | MEMORY_LIMIT
CommandResult     dc    command, stdout, stderr, exit_code, duration_ms, timed_out
OperationResult   dc    status, duration_ms, bucket, key, size_bytes,
                        checksum_sha256, error, error_code
ConnectivityResult dc   endpoint, overall_success, failure_category, layer_timings
WorkloadMetrics   dc    total/successful/failed ops, throughput_mbps,
                        latency min/avg/max/p95/p99, error_rate_percent
RecoveryTimeline  dc    fault_injected_at, fault_type, fault_removed_at,
                        cluster_healthy_at, integrity_verified_at
GateResult        dc    passed, metrics, violations[], recovery_timeline
```

### CLI Commands

```bash
storguard cluster deploy [--profile storage]
storguard cluster status
storguard cluster destroy [--volumes]
storguard test smoke
storguard test functional [--workers N]
storguard test resilience
storguard run --scenario node-failure|network-latency|packet-loss|disk-pressure
storguard baseline capture [--output baselines/latest.json]
storguard baseline compare [--baseline baselines/latest.json]
storguard gate evaluate [--config config/local.yaml] [--results allure-results]
storguard report generate [--results allure-results] [--output allure-report]
```

---

## Pytest Markers

```
smoke        fast blocking health checks (<5 min total)
functional   S3 CRUD, metadata, naming, replacement
integration  Python client → S3 protocol → storage nodes
integrity    SHA-256 and size validation
resilience   node loss, restart, latency, packet loss, disk pressure
performance  parallel throughput and latency percentiles
security     invalid credentials, permissions, TLS
negative     missing objects, invalid input, unavailable services
```

---

## Test Results Log

| Date | Suite | Tests | Result | Notes |
|---|---|---|---|---|
| 2026-08-26 | unit | 26/26 | PASS | 0.08s |
| 2026-08-26 | smoke | 3/3 | PASS | 0.47s, live cluster |
| 2026-08-26 | functional | 9/9 | PASS | 1.01s, live cluster |
| 2026-08-26 | performance | 2/2 | PASS | 1.08s, live cluster |
| 2026-08-26 | resilience | 2/2 | PASS | 13.58s, minio2 stopped+recovered |
| 2026-08-26 | ALL | 42/42 | PASS | 14.59s total |
| 2026-08-26 | security | 19/19 | PASS | 3.25s, live cluster — auth, namespace isolation, boundary inputs, error safety |
| 2026-08-26 | ai (unit) | 19/19 | PASS | 18.7s, mocked Ollama — log analyzer, summarizer, advisor |
| 2026-08-26 | ai (integration) | 5 skipped | SKIP | Ollama running but llama3.2 not pulled |
| 2026-08-26 | ALL (excl. new resilience) | 79/79 | PASS | 65s total |

### Live Benchmark Numbers (2026-08-26, local Docker)

| Scenario | Throughput | Avg latency | P95 | P99 |
|---|---|---|---|---|
| 10w × 20 × 1 KB upload | 0.21 MB/s | 41 ms | 63 ms | 63 ms |
| 10w × 20 × 1 MB upload | 67.34 MB/s | 136 ms | 188 ms | 188 ms |
| 10w × 20 × 1 MB mixed | 45.77 MB/s | 119 ms | 172 ms | 172 ms |

### Chaos Timeline (2026-08-26)

```
T+0.0s   minio2 stopped
T+0.2s   container status: exited
T+10.3s  read during outage: OK (10,016 ms — MinIO timeout before routing around node)
T+10.3s  minio2 restarted
T+10.5s  minio2 running
T+10.5s  SHA-256 post-recovery: MATCH — zero data corruption
```

---

## Bugs Fixed (Session Log)

| Date | Bug | Fix |
|---|---|---|
| 2026-08-26 | `version: "3.8"` in docker-compose.yml → warning | Removed obsolete key |
| 2026-08-26 | nginx health check used `localhost` → Connection refused (IPv6 vs IPv4 in alpine) | Changed to `127.0.0.1` |
| 2026-08-26 | `pyproject.toml` build-backend `setuptools.backends.legacy:build` — not available in old setuptools | Changed to `setuptools.build_meta` |
| 2026-08-26 | `requires-python = ">=3.12"` but only 3.9 installed | Changed to `>=3.9` |
| 2026-08-26 | `match/case` statements (Python 3.10+) in chaos/controller.py + workloads/engine.py | Replaced with `if/elif` |
| 2026-08-26 | `list[X]` / `bytes \| None` annotations fail in Python 3.9 | Added `from __future__ import annotations` + `List` from typing |
| 2026-08-26 | Windows terminal (cp1252) crashes on `→` character in print | Replaced arrow with plain text |

---

## Architecture Decisions

| Decision | Reason |
|---|---|
| 4 MinIO nodes (not 3) | MinIO requires minimum 4 drives for erasure coding quorum |
| nginx gateway in front of MinIO | Single S3 endpoint for tests; load balanced; realistic architecture |
| Docker Compose profiles (`storage`, `ci`) | Lets tests run without Jenkins/Allure overhead; Jenkins can bring full stack |
| `dataclass` not pydantic for models | Lighter dependency; sufficient for typed results |
| `if/elif` not `match/case` | Python 3.9 compatibility (only version installed) |
| `ThreadPoolExecutor` not asyncio for workloads | boto3 is sync; simpler; pytest-compatible |
| SHA-256 stored in S3 metadata on upload | Enables server-side integrity check without re-downloading to compare |
| `restore_all()` in chaos controller | Safety net — always cleans up even if test fails mid-scenario |
| `wait_until_running()` polls with deadline | Never sleeps fixed duration; resilient to varying container start times |

---

## Quality Gate Thresholds

### local.yaml (development)
```yaml
maximum_error_rate_percent: 5
maximum_data_corruption_count: 0
maximum_recovery_time_seconds: 60
maximum_p95_latency_ms: 1000
maximum_performance_regression_percent: 20
```

### ci.yaml (Jenkins pipeline)
```yaml
maximum_error_rate_percent: 2
maximum_data_corruption_count: 0
maximum_recovery_time_seconds: 30
maximum_p95_latency_ms: 800
maximum_performance_regression_percent: 20
```

---

## 6-Week Delivery Plan — Progress

| Week | Focus | Status | Deliverable |
|---|---|---|---|
| 1 | Linux/Python foundation, Docker setup | COMPLETE | Health + diagnostic layer |
| 2 | S3 client, CLI, functional tests | COMPLETE | All CRUD + CLI working |
| 3 | Integrity, negative tests, structured logging | COMPLETE | SHA-256 validation passing |
| 4 | Workload engine, metrics, baselines | COMPLETE | 67 MB/s benchmark captured |
| 5 | Chaos controller, recovery, networking | COMPLETE | Node failure + recovery proven |
| 6 | Jenkins, Allure, README, demo video | IN PROGRESS | Target: v1.0 release |

### Version Releases

| Version | Status | Content |
|---|---|---|
| v0.1 | DONE | Cluster deploy + health checks |
| v0.2 | DONE | Storage functional suite |
| v0.3 | DONE | Integrity + diagnostics |
| v0.4 | DONE | Concurrency baseline |
| v0.5 | DONE | Resilience suite |
| v1.0 | PENDING | Jenkins + Allure + recorded demo |

---

## Backlog (Prioritised)

### High — interview value, quick

- [x] `tests/security/test_security.py` — **DONE 2026-08-26, 19/19 PASS**
  - Wrong credentials → UNAUTHORIZED on every operation
  - Path traversal key (`../secret`) → rejected or contained
  - Bucket namespace isolation — cross-bucket reads return NOT_FOUND
  - Max key length (1024 chars) + oversized (1025) + null bytes — all handled cleanly
  - SQL injection in key → no InternalError
  - 100 MB upload → clean result (no crash)
  - Health endpoint → 200, no credentials leaked in body

- [ ] Allure environment.properties file
  - Write `allure-results/environment.properties` after cluster deploy
  - Fields: MINIO_VERSION, CLUSTER_NODES, PYTHON_VERSION, STORGUARD_VERSION

- [ ] Allure categories.json
  - Classify: Infrastructure failures, Data integrity failures, Recovery timeout

- [ ] `@allure.step()` inside resilience test bodies
  - Each chaos phase (inject, measure, restore, verify) as a named step
  - Makes the Allure timeline read as a story, not a single test block

### Medium — CI/CD completeness

- [ ] Coverage gate: `pytest --cov=storguard --cov-fail-under=75 tests/unit/`
  - Add `pytest-cov` to pyproject.toml test deps
  - Add as Stage 4b in Jenkinsfile

- [ ] Nightly Jenkins cron trigger
  - Full suite including resilience + performance
  - `triggers { cron('H 2 * * *') }` in Jenkinsfile

- [ ] `tests/resilience/test_network_faults.py`
  - Add latency injection test (200 ms via tc)
  - Add packet loss test (30%)
  - Both use `ChaosController.add_latency()` / `add_packet_loss()`

- [ ] `tests/resilience/test_disk_pressure.py`
  - Fill disk on one node, attempt write, verify clean error
  - Release disk, verify recovery

### Lower — after v1.0

- [ ] Upgrade Python to 3.12 (install via pyenv or official installer)
  - Restores `match/case`, `list[X]` syntax, removes boto3 deprecation warning

- [ ] Kubernetes deployment (plan says: after workflow stable)
  - Helm chart for MinIO distributed
  - Jenkins k8s agent

- [ ] Prometheus + Grafana metrics sidecar

- [ ] Locust load test for extended throughput runs

- [ ] README with architecture diagram, commands, troubleshooting

- [ ] 2-3 minute demo video (final recruiter artifact)

---

## External References Seen This Project

| Repo | URL | Relevance |
|---|---|---|
| test-case-management | https://github.com/rabinavidan/test-case-management.git | Compared against for test + CI/CD gaps |

### Key gaps identified from that repo vs StorGuard

1. Their Python tests use zero `@allure.feature/story/severity/step` — we already do this, advantage StorGuard
2. They have no performance/load tests — we have WorkloadEngine + benchmark numbers
3. They have no chaos/resilience tests — our strongest differentiator
4. They have no security test suite — both projects missing this, we should fill it first
5. Their CI lacks linting gate, coverage threshold — add both to our Jenkinsfile

---

## How To Resume Any Session

```bash
# 1. Start Docker Desktop if not running (check system tray)
# 2. Start the cluster
cd infrastructure && docker compose --profile storage up -d

# 3. Verify health
curl -s http://localhost:9000/minio/health/cluster   # expect HTTP 200

# 4. Activate env (if using venv)
# pip install -e ".[dev]"  (already installed globally)

# 5. Run full test suite to confirm baseline
python -m pytest tests/ --tb=short

# 6. Check this file for current backlog and pick next task
```

---

## Session History

### Session 1 — 2026-08-26

**Activities:**
- Read and discussed 15-page project plan PDF (`storguard_recruiter_ready_project_plan.pdf`)
- Built complete Docker ecosystem: 4 MinIO nodes + nginx gateway + Jenkins + Allure (55 files)
- Created complete Python package: models, clients (S3/Linux/Docker), workloads, chaos, integrity, quality gate, CLI
- Built test suite: unit (26), smoke (3), functional (9), performance (2), resilience (2) = 42 total
- Copied `.env.example` → `.env`, spun up cluster
- Fixed 7 bugs during bring-up (see Bugs Fixed section)
- Ran all 5 test suites — 42/42 passing
- Captured live benchmark: 67 MB/s on 1 MB objects, 4-node local cluster
- Proved chaos scenario: minio2 stopped → quorum maintained → node recovered → SHA-256 intact
- Compared project against https://github.com/rabinavidan/test-case-management for gaps
- Identified backlog: security tests, Allure categories, coverage gate, network faults
- Created this CLAUDE.md context file

**End state:** v0.5 complete, 42/42 tests passing, cluster healthy, Week 6 (Jenkins+Allure+demo) next
