"""Unit tests for data integrity validator — mocked S3 client."""

from __future__ import annotations

import hashlib
from typing import Optional

import allure
import pytest
from unittest.mock import MagicMock

from storguard.integrity.validator import IntegrityValidator, generate_test_data
from storguard.models import OperationResult, OperationStatus


def _mock_s3(download_data: Optional[bytes] = None, status: OperationStatus = OperationStatus.SUCCESS):
    s3 = MagicMock()
    if download_data is not None:
        checksum = hashlib.sha256(download_data).hexdigest()
        s3.download_object.return_value = OperationResult(
            status=status,
            duration_ms=10.0,
            bucket="b",
            key="k",
            size_bytes=len(download_data),
            checksum_sha256=checksum if status == OperationStatus.SUCCESS else None,
        )
    return s3


@allure.epic("Integrity")
@allure.feature("IntegrityValidator")
@pytest.mark.unit
@pytest.mark.integrity
class TestIntegrityValidator:

    @allure.story("SHA-256 Verification")
    @allure.title("verify() passes when downloaded data matches original")
    @allure.severity(allure.severity_level.BLOCKER)
    def test_passes_when_data_matches(self):
        with allure.step("Prepare 15-byte test payload"):
            data = b"hello storguard"

        with allure.step("Build mock S3 returning same data with matching SHA-256"):
            s3 = _mock_s3(download_data=data)
            validator = IntegrityValidator(s3)

        with allure.step("Run validator.verify()"):
            report = validator.verify("b", "k", data)

        with allure.step("Assert passed=True, checksum_match=True, size_match=True"):
            assert report.passed is True
            assert report.checksum_match is True
            assert report.size_match is True

    @allure.story("SHA-256 Verification")
    @allure.title("verify() fails when server returns corrupted bytes")
    @allure.severity(allure.severity_level.BLOCKER)
    def test_fails_when_data_corrupted(self):
        with allure.step("Define original and corrupted byte sequences"):
            original = b"original"
            corrupted = b"corrupted!"

        with allure.step("Build mock S3 returning corrupted data"):
            s3 = _mock_s3(download_data=corrupted)
            validator = IntegrityValidator(s3)

        with allure.step("Run verify() with original data"):
            report = validator.verify("b", "k", original)

        with allure.step("Assert passed=False and checksum_match=False"):
            assert report.passed is False
            assert report.checksum_match is False

    @allure.story("Download Failure")
    @allure.title("verify() fails when download returns FAILED status")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_fails_when_download_unavailable(self):
        with allure.step("Build mock S3 that returns FAILED status"):
            s3 = _mock_s3(download_data=b"", status=OperationStatus.FAILED)
            validator = IntegrityValidator(s3)

        with allure.step("Run verify() — download will fail"):
            report = validator.verify("b", "k", b"data")

        with allure.step("Assert passed=False and retrieved_sha256 is None"):
            assert report.passed is False
            assert report.retrieved_sha256 is None

    @allure.story("Batch Verification")
    @allure.title("corruption_count() counts all mismatched objects in batch")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_corruption_count(self):
        with allure.step("Build mock S3 returning wrong checksum for every key"):
            data = b"test"
            s3 = MagicMock()
            s3.download_object.return_value = OperationResult(
                status=OperationStatus.SUCCESS,
                duration_ms=5.0,
                bucket="b",
                key="k",
                size_bytes=len(data),
                checksum_sha256="wrong_checksum",
            )
            validator = IntegrityValidator(s3)

        with allure.step("Run verify_batch() on 2 keys"):
            reports = validator.verify_batch("b", {"k1": data, "k2": data})

        with allure.step("Assert corruption_count == 2"):
            assert validator.corruption_count(reports) == 2


@allure.epic("Integrity")
@allure.feature("Test Data Generator")
@pytest.mark.unit
class TestGenerateTestData:

    @allure.story("Size correctness")
    @allure.title("generate_test_data(0) returns empty bytes")
    def test_exact_size_zero(self):
        with allure.step("Call generate_test_data(0)"):
            result = generate_test_data(0)
        with allure.step("Assert result is b''"):
            assert result == b""

    @allure.story("Size correctness")
    @allure.title("generate_test_data(1024) returns exactly 1024 bytes")
    def test_exact_size_1kb(self):
        with allure.step("Call generate_test_data(1024)"):
            data = generate_test_data(1024)
        with allure.step("Assert len == 1024"):
            assert len(data) == 1024

    @allure.story("Determinism")
    @allure.title("Same seed produces identical bytes on repeated calls")
    def test_deterministic(self):
        with allure.step("Generate 512 bytes twice with seed=42"):
            first = generate_test_data(512, seed=42)
            second = generate_test_data(512, seed=42)
        with allure.step("Assert outputs are identical"):
            assert first == second

    @allure.story("Determinism")
    @allure.title("Different seeds produce different byte sequences")
    @pytest.mark.negative
    def test_different_seeds_produce_different_data(self):
        with allure.step("Generate 512 bytes with seed=1 and seed=2"):
            data_1 = generate_test_data(512, seed=1)
            data_2 = generate_test_data(512, seed=2)
        with allure.step("Assert outputs differ"):
            assert data_1 != data_2
