"""AI report summarizer — converts WorkloadMetrics / GateResult into plain-English narratives.

Used in CLI output and as Allure attachments so non-technical stakeholders can
read test results without understanding raw numbers.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import List, Optional

from storguard.ai.ollama_client import OllamaClient
from storguard.models import GateResult, RecoveryTimeline, WorkloadMetrics


@dataclass
class AITestNarrative:
    headline: str
    summary: str
    key_findings: List[str]
    risk_assessment: str
    ai_available: bool = True

    def format_report(self) -> str:
        lines = [
            f"# {self.headline}",
            "",
            self.summary,
            "",
            "Key Findings:",
        ] + [f"  • {f}" for f in self.key_findings] + [
            "",
            f"Risk: {self.risk_assessment}",
        ]
        return "\n".join(lines)


_SYSTEM_PROMPT = """You are a senior SDET writing executive summaries of distributed storage test results.
Be concise, technical, and specific. Avoid filler phrases.

Respond ONLY in this JSON format:
{
  "headline": "one-line result (≤12 words)",
  "summary": "2-3 sentence technical paragraph",
  "key_findings": ["specific finding 1", "specific finding 2", "specific finding 3"],
  "risk_assessment": "low|medium|high — one sentence explanation"
}"""


class ReportSummarizer:
    def __init__(self, client: Optional[OllamaClient] = None) -> None:
        self._client = client or OllamaClient()

    def summarize_metrics(self, metrics: WorkloadMetrics) -> AITestNarrative:
        prompt = f"""S3 workload test results:
Total operations : {metrics.total_operations}
Successful       : {metrics.successful_operations}
Failed           : {metrics.failed_operations}
Error rate       : {metrics.error_rate_percent}%
Throughput       : {metrics.throughput_mbps} MB/s
Avg latency      : {metrics.latency_ms_avg} ms
P95 latency      : {metrics.latency_ms_p95} ms
P99 latency      : {metrics.latency_ms_p99} ms
Duration         : {metrics.duration_seconds:.1f} s"""
        return self._call(prompt, f"Workload — {metrics.throughput_mbps} MB/s throughput")

    def summarize_chaos(self, timeline: RecoveryTimeline) -> AITestNarrative:
        prompt = f"""Chaos engineering result:
Fault type       : {timeline.fault_type}
Recovery time    : {timeline.recovery_time_seconds:.1f} s
Total downtime   : {timeline.total_downtime_seconds:.1f} s
Data integrity   : {"PRESERVED" if timeline.integrity_verified_at else "NOT VERIFIED"}"""
        return self._call(prompt, f"Chaos — {timeline.fault_type} recovered in {timeline.recovery_time_seconds:.1f}s")

    def summarize_gate(self, gate: GateResult) -> AITestNarrative:
        gate_result = "PASS" if gate.passed else "FAIL"
        violations = "\n".join(gate.violations) if gate.violations else "none"
        prompt = f"""Quality gate evaluation:
Gate result      : {gate_result}
Violations       : {violations}
Error rate       : {gate.metrics.error_rate_percent}%
P95 latency      : {gate.metrics.latency_ms_p95} ms
Throughput       : {gate.metrics.throughput_mbps} MB/s"""
        return self._call(prompt, f"Quality Gate — {gate_result}")

    # ─── Internal ─────────────────────────────────────────────────────────────

    def _call(self, prompt: str, fallback_headline: str) -> AITestNarrative:
        if not self._client.is_available():
            return AITestNarrative(
                headline=fallback_headline,
                summary="Ollama offline — AI narrative disabled.",
                key_findings=["Run `ollama serve` and `ollama pull llama3.2` to enable"],
                risk_assessment="unknown — AI not available",
                ai_available=False,
            )
        try:
            resp = self._client.generate(prompt, system=_SYSTEM_PROMPT)
            m = re.search(r"\{.*\}", resp.content, re.DOTALL)
            data = json.loads(m.group() if m else resp.content)
            return AITestNarrative(
                headline=data.get("headline", fallback_headline),
                summary=data.get("summary", ""),
                key_findings=data.get("key_findings", []),
                risk_assessment=data.get("risk_assessment", "unknown"),
                ai_available=True,
            )
        except Exception as exc:
            return AITestNarrative(
                headline=fallback_headline,
                summary=f"AI summarization failed: {exc}",
                key_findings=[],
                risk_assessment="unknown — AI error",
                ai_available=False,
            )
