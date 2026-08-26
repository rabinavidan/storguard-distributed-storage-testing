"""AI-powered log analyzer — regex pre-scan + LLM root-cause analysis.

Falls back to rule-based analysis when Ollama is unavailable so tests never
depend on the AI service being running.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import List, Optional

from storguard.ai.ollama_client import OllamaClient, OllamaConfig


@dataclass
class LogAnalysis:
    container: str
    severity: str          # "low" | "medium" | "high" | "critical"
    anomalies: List[str]
    root_cause: str
    recommendations: List[str]
    ai_summary: str
    ai_available: bool = True

    @property
    def is_healthy(self) -> bool:
        return self.severity == "low" and not self.anomalies

    def format_report(self) -> str:
        lines = [
            f"Log Analysis — {self.container}",
            f"Severity   : {self.severity.upper()}",
            f"Root Cause : {self.root_cause}",
        ]
        if not self.ai_available:
            lines.append("AI         : offline — rule-based only")
        if self.anomalies:
            lines += ["", "Anomalies:"] + [f"  • {a}" for a in self.anomalies]
        if self.recommendations:
            lines += ["", "Recommendations:"] + [f"  → {r}" for r in self.recommendations]
        return "\n".join(lines)


_SYSTEM_PROMPT = """You are an expert in MinIO distributed storage and Docker infrastructure.
Analyze these container logs and respond ONLY in this JSON format — no prose:
{
  "severity": "low|medium|high|critical",
  "anomalies": ["short description of each anomaly found"],
  "root_cause": "one concise sentence",
  "recommendations": ["actionable step 1", "actionable step 2"]
}"""

_PATTERN_RULES = [
    (r"(?i)panic|fatal|corruption",                    "Fatal error or data corruption"),
    (r"(?i)connection refused|connection reset",        "Network connectivity failure"),
    (r"(?i)out of memory|oom.?kill",                   "Memory pressure / OOM kill"),
    (r"(?i)no space left|enospc|disk full",            "Disk space exhaustion"),
    (r"(?i)timeout.*\d{4,}\s*ms",                      "Request timeouts exceeding 1 s"),
    (r"(?i)quorum.*fail|erasure.*error",               "Erasure-coding / quorum failure"),
    (r"(?i)InvalidAccessKeyId|authentication failed",  "Authentication failure"),
    (r"(?i)certificate.*expired|tls.*error",           "TLS / certificate issue"),
    (r"(?i)read.?only|i/o error",                      "Storage I/O error"),
]


class LogAnalyzer:
    def __init__(self, client: Optional[OllamaClient] = None) -> None:
        self._client = client or OllamaClient()

    def analyze(self, logs: str, container: str = "unknown") -> LogAnalysis:
        pre = self._detect_patterns(logs)

        if not self._client.is_available():
            return self._rule_based(container, pre)

        try:
            return self._ai_analysis(logs, container, pre)
        except Exception:
            return self._rule_based(container, pre)

    # ─── Internal ─────────────────────────────────────────────────────────────

    def _detect_patterns(self, logs: str) -> List[str]:
        return [label for pattern, label in _PATTERN_RULES if re.search(pattern, logs)]

    def _ai_analysis(self, logs: str, container: str, pre: List[str]) -> LogAnalysis:
        # Feed only the last 100 lines to stay within context limits
        tail = "\n".join(logs.strip().splitlines()[-100:])
        prompt = (
            f"Container: {container}\n"
            f"Pre-detected patterns: {pre}\n\n"
            f"Logs (last 100 lines):\n{tail}"
        )
        resp = self._client.generate(prompt, system=_SYSTEM_PROMPT)

        try:
            m = re.search(r"\{.*\}", resp.content, re.DOTALL)
            data = json.loads(m.group() if m else resp.content)
            return LogAnalysis(
                container=container,
                severity=data.get("severity", "medium"),
                anomalies=data.get("anomalies", pre),
                root_cause=data.get("root_cause", "See AI summary"),
                recommendations=data.get("recommendations", []),
                ai_summary=resp.content,
                ai_available=True,
            )
        except (json.JSONDecodeError, AttributeError):
            return LogAnalysis(
                container=container,
                severity="medium" if pre else "low",
                anomalies=pre,
                root_cause="AI response could not be parsed — see raw summary",
                recommendations=["Review logs manually"],
                ai_summary=resp.content,
                ai_available=True,
            )

    def _rule_based(self, container: str, anomalies: List[str]) -> LogAnalysis:
        n = len(anomalies)
        severity = "critical" if n >= 3 else "high" if n >= 2 else "medium" if n else "low"
        return LogAnalysis(
            container=container,
            severity=severity,
            anomalies=anomalies,
            root_cause="Ollama offline — rule-based detection only",
            recommendations=[
                "Start Ollama: ollama serve",
                "Pull model:   ollama pull llama3.2",
            ],
            ai_summary="",
            ai_available=False,
        )
