"""AI chaos scenario advisor — recommends fault injection strategies.

Given current WorkloadMetrics and cluster state, the advisor asks a local
Ollama model which chaos scenarios would best surface hidden weaknesses.
Falls back to a curated default list when Ollama is offline.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from storguard.ai.ollama_client import OllamaClient
from storguard.models import WorkloadMetrics


@dataclass
class ChaosRecommendation:
    scenario: str           # matches CLI: node-failure | network-latency | packet-loss | disk-pressure
    rationale: str
    expected_impact: str
    priority: str           # "low" | "medium" | "high"
    parameters: Dict[str, Any] = field(default_factory=dict)

    def format(self) -> str:
        params = ", ".join(f"{k}={v}" for k, v in self.parameters.items())
        header = f"[{self.priority.upper()}] {self.scenario}"
        if params:
            header += f"  ({params})"
        return f"{header}\n  Rationale : {self.rationale}\n  Expected  : {self.expected_impact}"


_SYSTEM_PROMPT = """You are a chaos engineering expert for distributed MinIO storage clusters.
Recommend fault injection scenarios to validate resilience.

Available scenarios: node-failure, network-latency, packet-loss, disk-pressure

Respond ONLY in this JSON format:
{
  "recommendations": [
    {
      "scenario": "scenario-name",
      "rationale": "why this scenario exposes a weakness",
      "expected_impact": "what should happen if the system is healthy",
      "priority": "low|medium|high",
      "parameters": {"key": "value"}
    }
  ]
}"""

_DEFAULTS: List[ChaosRecommendation] = [
    ChaosRecommendation(
        scenario="node-failure",
        rationale="Validates erasure-coding quorum — core MinIO resilience claim",
        expected_impact="Reads continue with elevated latency; zero data loss on recovery",
        priority="high",
        parameters={"node": "storguard-minio2"},
    ),
    ChaosRecommendation(
        scenario="network-latency",
        rationale="Tests S3 client timeout and retry behaviour under degraded network",
        expected_impact="Latency increases proportionally; retries absorb transient failures",
        priority="medium",
        parameters={"latency_ms": 200, "interface": "eth0"},
    ),
    ChaosRecommendation(
        scenario="packet-loss",
        rationale="Simulates degraded WAN link — exposes missing retry logic",
        expected_impact="Error rate spikes then stabilises as boto3 retries succeed",
        priority="medium",
        parameters={"loss_percent": 30, "interface": "eth0"},
    ),
    ChaosRecommendation(
        scenario="disk-pressure",
        rationale="Full-disk condition surfaces unhandled ENOSPC error paths",
        expected_impact="Writes fail with clean error; reads and deletes unaffected",
        priority="low",
        parameters={"fill_mb": 4096, "path": "/data"},
    ),
]


class ChaosAdvisor:
    def __init__(self, client: Optional[OllamaClient] = None) -> None:
        self._client = client or OllamaClient()

    def recommend(
        self,
        metrics: Optional[WorkloadMetrics] = None,
        cluster_state: Optional[Dict[str, Any]] = None,
    ) -> List[ChaosRecommendation]:
        if not self._client.is_available():
            return list(_DEFAULTS)

        prompt = self._build_prompt(metrics, cluster_state)
        try:
            return self._ai_recommend(prompt)
        except Exception:
            return list(_DEFAULTS)

    # ─── Internal ─────────────────────────────────────────────────────────────

    def _build_prompt(
        self,
        metrics: Optional[WorkloadMetrics],
        state: Optional[Dict[str, Any]],
    ) -> str:
        parts = ["Analyze this distributed storage cluster and recommend chaos scenarios:"]
        if metrics:
            parts.append(
                f"\nCurrent performance metrics:\n"
                f"  Throughput : {metrics.throughput_mbps} MB/s\n"
                f"  Error rate : {metrics.error_rate_percent}%\n"
                f"  P95 latency: {metrics.latency_ms_p95} ms\n"
                f"  P99 latency: {metrics.latency_ms_p99} ms\n"
                f"  Ops total  : {metrics.total_operations}"
            )
        if state:
            parts.append(f"\nCluster state:\n{json.dumps(state, indent=2)}")
        parts.append("\nWhich chaos scenarios would best validate resilience and expose hidden weaknesses?")
        return "\n".join(parts)

    def _ai_recommend(self, prompt: str) -> List[ChaosRecommendation]:
        resp = self._client.generate(prompt, system=_SYSTEM_PROMPT)
        m = re.search(r"\{.*\}", resp.content, re.DOTALL)
        data = json.loads(m.group() if m else resp.content)
        return [
            ChaosRecommendation(
                scenario=r.get("scenario", "node-failure"),
                rationale=r.get("rationale", ""),
                expected_impact=r.get("expected_impact", ""),
                priority=r.get("priority", "medium"),
                parameters=r.get("parameters", {}),
            )
            for r in data.get("recommendations", [])
        ]
