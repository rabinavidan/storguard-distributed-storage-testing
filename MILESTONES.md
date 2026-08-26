# StorGuard — Delivery Milestones

> Append-only. Mark items `[x]` when done. Never delete rows.

---

## Milestone 1 — Core Platform `v0.5` ✅ COMPLETE

| Item | Status |
|---|---|
| 4-node MinIO + nginx Docker ecosystem | DONE |
| S3 / Docker / Linux clients | DONE |
| Chaos controller (node, network, disk) | DONE |
| Integrity validator (SHA-256 round-trip) | DONE |
| Workload engine (ThreadPoolExecutor + metrics) | DONE |
| Quality gate (threshold evaluation) | DONE |
| Click + Rich CLI | DONE |
| Unit tests — 26/26 | DONE |
| Smoke tests — 3/3 | DONE |
| Functional tests — 9/9 | DONE |
| Performance tests — 2/2 | DONE |
| Resilience tests — 2/2 | DONE |
| Security tests — 19/19 | DONE |
| Jenkinsfile (11-stage pipeline) | DONE |
| CLAUDE.md context file | DONE |

**Total: 61/61 tests passing**

---

## Milestone 2 — Resilience Coverage `v0.6`

| Item | Status | Value |
|---|---|---|
| `test_network_faults.py` — 200 ms latency injection | DONE | SDET |
| `test_network_faults.py` — 30% packet loss injection | DONE | SDET |
| `test_disk_pressure.py` — disk fill → clean error → recovery | DONE | SDET |
| `@allure.step()` inside resilience test bodies | DONE | Reporting |
| Allure `environment.properties` | DONE | Reporting |
| Allure `categories.json` | DONE | Reporting |

---

## Milestone 3 — AI/Ollama Integration `v0.7` ★ DIFFERENTIATOR

| Item | Status | Value |
|---|---|---|
| `storguard/ai/ollama_client.py` — httpx wrapper, graceful fallback | DONE | Architecture |
| `storguard/ai/log_analyzer.py` — regex pre-scan + LLM root-cause | DONE | SDET |
| `storguard/ai/report_summarizer.py` — metrics → natural language | DONE | Recruiter |
| `storguard/ai/chaos_advisor.py` — AI chaos recommendations | DONE | Architecture |
| CLI `storguard ai status/analyze-logs/summarize/advise` | DONE | Demo |
| `tests/ai/test_ai.py` — unit tests (mocked + integration) | DONE | SDET |
| AI failure hook in conftest (auto-attach on test fail) | DONE | SDET |

**Recommended Ollama models (free, local):**

| Model | Size | Best for |
|---|---|---|
| `llama3.2` | 2 GB | General analysis, recommendations |
| `llama3.2:1b` | 1.3 GB | Fast analysis on low RAM |
| `mistral` | 4 GB | Structured JSON output |
| `phi3:mini` | 2.3 GB | Lightweight reasoning |
| `nomic-embed-text` | 274 MB | Log similarity / clustering |

**Quick start:**
```bash
# Install Ollama (Linux/Mac/Windows)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2          # 2 GB — recommended default
ollama serve                  # starts on http://localhost:11434

# StorGuard AI commands
storguard ai status           # verify Ollama + list models
storguard ai analyze-logs --container storguard-minio1
storguard ai summarize --metrics baselines/latest.json
storguard ai advise           # chaos scenario recommendations
```

---

## Milestone 4 — CI/CD Completeness `v0.8`

| Item | Status | Value |
|---|---|---|
| `pytest-cov` added to dev deps | DONE | CI |
| Coverage gate `--cov-fail-under=75` | DONE | CI |
| `gate evaluate` CLI — real threshold evaluation | DONE | Architecture |
| Jenkinsfile Stage 4b: coverage gate | TODO | CI |
| Jenkins server wired to Git repo | TODO | Demo |
| Nightly cron trigger `H 2 * * *` | TODO | CI |

---

## Milestone 5 — Documentation & Demo `v1.0`

| Item | Status | Value |
|---|---|---|
| `README.md` — architecture diagram + quick start | DONE | Recruiter |
| Screenshot evidence of Allure report | TODO | Recruiter |
| 2–3 min demo video | TODO | Recruiter |
| GitHub release tag `v1.0` | TODO | Portfolio |

---

## Milestone 6 — Advanced (Post v1.0)

| Item | Status | Value |
|---|---|---|
| Python 3.12 upgrade (pyenv) | TODO | Maintenance |
| Kubernetes / Helm deployment | TODO | Architecture |
| Prometheus + Grafana sidecar | TODO | Observability |
| Locust extended load tests | TODO | Performance |
| `nomic-embed-text` log similarity clustering | TODO | AI |

---

## Score Card — SW Architect / SDET / Recruiter

| Dimension | Before M1 | After M1–M3 |
|---|---|---|
| Test breadth | 0 suites | 7 suites, 70+ tests |
| Chaos coverage | None | Node + Network + Disk |
| AI differentiator | None | Local LLM analysis + advisor |
| Allure evidence | None | Full epic/feature/story/step |
| CI pipeline | None | 11-stage Jenkinsfile |
| Documentation | None | README + CLAUDE.md + MILESTONES.md |
