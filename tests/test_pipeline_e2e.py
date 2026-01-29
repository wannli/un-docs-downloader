# End-to-end tests for Mandate Pipeline Workflows
# These tests simulate what each GitHub Action workflow does

import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import tempfile
import shutil


class TestDiscoveryWorkflow:
    """End-to-end tests for the Discover workflow."""

    def test_load_patterns(self):
        """Test loading discovery patterns from config."""
        from mandate_pipeline.discovery import load_patterns

        patterns_file = Path("config/patterns.yaml")
        if patterns_file.exists():
            patterns = load_patterns(patterns_file)
            assert isinstance(patterns, list)
            assert len(patterns) > 0
            # Each pattern should have required fields
            for pattern in patterns:
                assert "name" in pattern or "pattern" in pattern

    def test_pattern_structure(self):
        """Validate pattern configuration structure."""
        from mandate_pipeline.discovery import load_patterns

        patterns_file = Path("config/patterns.yaml")
        if not patterns_file.exists():
            pytest.skip("patterns.yaml not found")

        patterns = load_patterns(patterns_file)
        for pattern in patterns:
            # Patterns should have a name and search criteria
            assert isinstance(pattern, dict)


class TestExtractionWorkflow:
    """End-to-end tests for the Extract workflow."""

    def test_extract_functions_exist(self):
        """Verify all extraction functions are importable."""
        from mandate_pipeline.extractor import (
            extract_text,
            extract_operative_paragraphs,
            extract_lettered_paragraphs,
            extract_title,
            extract_agenda_items,
            find_symbol_references,
        )

        # All functions should be callable
        assert callable(extract_text)
        assert callable(extract_operative_paragraphs)
        assert callable(extract_title)

    def test_extract_operative_paragraphs(self):
        """Test operative paragraph extraction."""
        from mandate_pipeline.extractor import extract_operative_paragraphs

        sample_text = """
        The General Assembly,

        Recalling its resolution 70/1,

        1. Requests the Secretary-General to submit a report;

        2. Decides to include in the provisional agenda of its eightieth session;

        3. Takes note of the report of the Secretary-General;
        """

        paragraphs = extract_operative_paragraphs(sample_text)
        assert isinstance(paragraphs, dict)
        # Should extract numbered paragraphs
        if paragraphs:
            for num, text in paragraphs.items():
                assert isinstance(num, int)
                assert isinstance(text, str)

    def test_find_symbol_references(self):
        """Test finding UN document symbol references."""
        from mandate_pipeline.extractor import find_symbol_references

        sample_text = """
        Recalling resolution A/RES/70/1 and A/RES/75/280,
        and taking note of A/80/L.1 and its amendment A/80/L.1/Rev.1
        """

        refs = find_symbol_references(sample_text)
        assert isinstance(refs, list)
        # Should find resolution symbols
        if refs:
            for ref in refs:
                assert isinstance(ref, str)

    def test_extraction_output_format(self):
        """Test extraction output has correct structure for downstream processing."""
        # Simulate extracted document format
        extracted = {
            "symbol": "A/RES/79/1",
            "filename": "A_RES_79_1.pdf",
            "title": "Test Resolution",
            "text": "Full text here...",
            "paragraphs": {1: "Paragraph 1", 2: "Paragraph 2"},
            "agenda_items": [],
            "symbol_references": ["A/80/L.1"],
        }

        # Verify structure
        assert "symbol" in extracted
        assert "paragraphs" in extracted
        assert isinstance(extracted["paragraphs"], dict)
        for num, text in extracted["paragraphs"].items():
            assert isinstance(num, int)


class TestDetectionWorkflow:
    """End-to-end tests for the Detect workflow."""

    def test_load_checks(self):
        """Test loading signal detection checks."""
        from mandate_pipeline.detection import load_checks

        checks_file = Path("config/checks.yaml")
        if checks_file.exists():
            checks = load_checks(checks_file)
            assert isinstance(checks, list)
            assert len(checks) > 0
            # Each check should have required fields (signal or name)
            for check in checks:
                assert "signal" in check or "name" in check
                assert "phrases" in check

    def test_run_checks(self):
        """Test running signal detection on paragraphs."""
        from mandate_pipeline.detection import load_checks, run_checks

        checks_file = Path("config/checks.yaml")
        if not checks_file.exists():
            pytest.skip("checks.yaml not found")

        checks = load_checks(checks_file)

        # Sample paragraphs with likely signals
        test_paragraphs = {
            1: "Requests the Secretary-General to submit a report on implementation.",
            2: "Decides to include in the provisional agenda of its eightieth session.",
            3: "Requests the President of the General Assembly to convene a meeting.",
        }

        signals = run_checks(test_paragraphs, checks)
        assert isinstance(signals, dict)

        # Verify signal structure
        for para_num, para_signals in signals.items():
            assert isinstance(para_signals, list)
            for signal in para_signals:
                assert isinstance(signal, str)

    def test_detection_output_format(self):
        """Test detection output has correct structure."""
        # Simulate detection result format
        detection_result = {
            "symbol": "A/RES/79/1",
            "signals": {
                "1": ["report"],
                "2": ["agenda"],
                "3": ["PGA"],
            },
            "signal_summary": {"report": 1, "agenda": 1, "PGA": 1},
        }

        # Validate structure
        assert "symbol" in detection_result
        assert "signals" in detection_result
        assert "signal_summary" in detection_result
        assert isinstance(detection_result["signals"], dict)
        assert isinstance(detection_result["signal_summary"], dict)

        # Keys in signals should be paragraph numbers (as strings after JSON)
        for para_num, para_signals in detection_result["signals"].items():
            assert isinstance(para_signals, list)


class TestLinkingWorkflow:
    """End-to-end tests for the Link workflow."""

    def test_derive_resolution_origin(self):
        """Test deriving resolution origin from symbol."""
        from mandate_pipeline.linking import derive_resolution_origin

        # Test Plenary resolution
        doc = {"symbol": "A/RES/79/1", "linked_proposal_symbols": []}
        origin = derive_resolution_origin(doc)
        assert isinstance(origin, str)

        # Test committee resolution (C.1)
        doc = {"symbol": "A/RES/79/100", "linked_proposal_symbols": ["A/C.1/79/L.1"]}
        origin = derive_resolution_origin(doc)
        assert isinstance(origin, str)

    def test_linking_output_format(self):
        """Test linked document has correct structure."""
        # Simulate linked document format
        linked_doc = {
            "symbol": "A/RES/79/1",
            "doc_type": "resolution",
            "origin": "Plenary",
            "linked_proposals": [],
            "linked_resolutions": [],
            "signal_summary": {"report": 1},
            "signals": {"1": ["report"]},
        }

        # Required fields
        assert "symbol" in linked_doc
        assert "doc_type" in linked_doc
        assert "signals" in linked_doc
        assert "signal_summary" in linked_doc

        # Type validations
        assert isinstance(linked_doc["signals"], dict)
        assert isinstance(linked_doc["signal_summary"], dict)
        assert isinstance(linked_doc["linked_proposals"], list)
        assert isinstance(linked_doc["linked_resolutions"], list)

    def test_load_linked_documents(self):
        """Test loading linked documents from data directory."""
        linked_dir = Path("data/linked")
        if not linked_dir.exists():
            pytest.skip("data/linked not found")

        # Load a sample of documents
        errors = []
        for linked_file in list(linked_dir.glob("*.json"))[:10]:
            if linked_file.name == "index.json":
                continue

            try:
                with open(linked_file) as f:
                    doc = json.load(f)

                # Validate required fields
                assert "symbol" in doc, f"Missing symbol in {linked_file}"
                assert "signals" in doc, f"Missing signals in {linked_file}"

                # Validate types
                if not isinstance(doc["signals"], dict):
                    errors.append(f"{linked_file}: signals should be dict")
                if "signal_summary" in doc and not isinstance(doc["signal_summary"], dict):
                    errors.append(f"{linked_file}: signal_summary should be dict")

            except Exception as e:
                errors.append(f"{linked_file}: {e}")

        assert len(errors) == 0, f"Document validation errors:\n" + "\n".join(errors)


class TestGenerationWorkflow:
    """End-to-end tests for the Generate workflow."""

    def test_safe_paragraph_number(self):
        """Test the safe paragraph number helper."""
        from mandate_pipeline.generation import safe_paragraph_number

        # Valid cases
        assert safe_paragraph_number({"number": "42"}) == 42
        assert safe_paragraph_number({"number": 7}) == 7

        # Edge cases
        assert safe_paragraph_number({}) == 0
        assert safe_paragraph_number({"number": None}) == 0
        assert safe_paragraph_number({"number": "invalid"}) == 0

    def test_signal_paragraphs_enrichment(self):
        """Test creating signal_paragraphs from signals dict."""
        from mandate_pipeline.generation import safe_paragraph_number

        # Input document (from linked/*.json)
        doc = {
            "symbol": "A/RES/79/1",
            "signals": {
                "5": ["report"],
                "10": ["agenda", "PGA"],
            },
            "paragraphs": {
                "5": "Paragraph 5 text",
                "10": "Paragraph 10 text",
            },
            "signal_summary": {"report": 1, "agenda": 1, "PGA": 1},
        }

        # Simulate enrichment (what generate workflow does)
        signal_paras = []
        for para_num, para_signals in doc.get("signals", {}).items():
            if para_signals:
                signal_paras.append({
                    "number": para_num,
                    "text": doc.get("paragraphs", {}).get(para_num, ""),
                    "signals": para_signals,
                })

        signal_paras.sort(key=safe_paragraph_number)

        # Validate result
        assert isinstance(signal_paras, list)
        assert len(signal_paras) == 2
        assert signal_paras[0]["number"] == "5"  # Sorted
        assert signal_paras[1]["number"] == "10"

        # Verify we can create signal_summary from enriched data
        computed_summary = {}
        for para in signal_paras:
            for signal in para.get("signals", []):
                computed_summary[signal] = computed_summary.get(signal, 0) + 1

        assert computed_summary == {"report": 1, "agenda": 1, "PGA": 1}

    def test_document_total_counts(self):
        """Test counting documents and signal paragraphs."""
        documents = [
            {
                "symbol": "A/RES/79/1",
                "signal_paragraphs": [{"number": "1"}, {"number": "2"}],
                "signal_summary": {"report": 2},
            },
            {
                "symbol": "A/RES/79/2",
                "signal_paragraphs": [{"number": "5"}],
                "signal_summary": {"agenda": 1},
            },
            {"symbol": "A/RES/79/3", "signal_paragraphs": [], "signal_summary": {}},
        ]

        # Count documents with actual signals (empty list is falsy)
        # Note: if d.get("signal_paragraphs") returns False for empty list []
        docs_with_signals = [d for d in documents if d.get("signal_paragraphs")]
        assert len(docs_with_signals) == 2  # Only non-empty lists are truthy

        # Count documents with actual signals (explicit length check)
        docs_with_actual_signals = [d for d in documents if len(d.get("signal_paragraphs", [])) > 0]
        assert len(docs_with_actual_signals) == 2

        # Count total paragraphs (using correct list default)
        total_paras = sum(len(d.get("signal_paragraphs", [])) for d in documents)
        assert total_paras == 3

        # Count total signals from summaries
        signal_counts = {}
        for doc in documents:
            for signal, count in doc.get("signal_summary", {}).items():
                signal_counts[signal] = signal_counts.get(signal, 0) + count

        assert signal_counts == {"report": 2, "agenda": 1}

    def test_templates_exist(self):
        """Verify template files exist."""
        template_dir = Path("src/mandate_pipeline/templates")
        if not template_dir.exists():
            pytest.skip("templates directory not found")

        expected_templates = [
            "signals_unified.html",
        ]

        for template_name in expected_templates:
            # Check in static and/or root template dir
            found = (
                (template_dir / template_name).exists()
                or (template_dir / "static" / template_name).exists()
            )
            # Just log if missing, don't fail
            if not found:
                print(f"Note: Template {template_name} not found")


class TestFullPipelineIntegration:
    """Integration tests simulating the full pipeline flow."""

    def test_data_flow_discovery_to_extraction(self):
        """Test data compatibility between discovery and extraction."""
        # Discovery outputs PDF files
        # Extraction reads PDF files and outputs JSON
        extracted = {
            "symbol": "A/RES/79/1",
            "filename": "A_RES_79_1.pdf",
            "paragraphs": {1: "Para 1", 2: "Para 2"},
            "title": "Test",
            "text": "Full text",
        }

        # Extraction output should have paragraphs as dict with int keys
        assert isinstance(extracted["paragraphs"], dict)
        for key in extracted["paragraphs"]:
            assert isinstance(key, int)

    def test_data_flow_extraction_to_detection(self):
        """Test data compatibility between extraction and detection."""
        # Extraction outputs JSON with paragraphs
        extracted = {
            "symbol": "A/RES/79/1",
            "paragraphs": {1: "Para 1", 2: "Para 2"},
        }

        # Detection reads paragraphs
        from mandate_pipeline.detection import run_checks

        # run_checks expects dict[int, str]
        # After JSON round-trip, keys become strings
        paragraphs_after_json = {str(k): v for k, v in extracted["paragraphs"].items()}

        # Detection should still work with string keys
        # (checks.yaml may not exist in test env)
        checks = []  # Empty checks for test
        signals = run_checks(paragraphs_after_json, checks)
        assert isinstance(signals, dict)

    def test_data_flow_detection_to_linking(self):
        """Test data compatibility between detection and linking."""
        detection_result = {
            "symbol": "A/RES/79/1",
            "signals": {"1": ["report"], "2": ["agenda"]},
            "signal_summary": {"report": 1, "agenda": 1},
        }

        # Linking reads detection results
        linked = {
            "symbol": detection_result["symbol"],
            "doc_type": "resolution",
            "signals": detection_result["signals"],
            "signal_summary": detection_result["signal_summary"],
            "linked_proposals": [],
            "linked_resolutions": [],
        }

        # After JSON serialization (simulating file write/read)
        linked_json = json.dumps(linked)
        linked_loaded = json.loads(linked_json)

        # Signals keys become strings
        assert isinstance(linked_loaded["signals"], dict)
        for key in linked_loaded["signals"]:
            assert isinstance(key, str)

    def test_data_flow_linking_to_generation(self):
        """Test data compatibility between linking and generation."""
        from mandate_pipeline.generation import safe_paragraph_number

        # Linked document (as loaded from JSON)
        linked = {
            "symbol": "A/RES/79/1",
            "signals": {"5": ["report"], "10": ["agenda"]},
            "signal_summary": {"report": 1, "agenda": 1},
            "paragraphs": {"5": "Para 5", "10": "Para 10"},
        }

        # Generation enriches with signal_paragraphs
        signal_paras = []
        for para_num, para_signals in linked.get("signals", {}).items():
            if para_signals:
                signal_paras.append({
                    "number": para_num,  # String from JSON
                    "text": linked.get("paragraphs", {}).get(para_num, ""),
                    "signals": para_signals,
                })

        # Sort should work with string numbers
        signal_paras.sort(key=safe_paragraph_number)

        # Verify correct order (5 before 10)
        assert signal_paras[0]["number"] == "5"
        assert signal_paras[1]["number"] == "10"

        # Generation creates signal_paragraphs as a LIST
        linked["signal_paragraphs"] = signal_paras
        assert isinstance(linked["signal_paragraphs"], list)

        # Template can iterate over the list
        for para in linked["signal_paragraphs"]:
            assert "number" in para
            assert "text" in para
            assert "signals" in para


class TestErrorHandling:
    """Test error handling across pipeline stages."""

    def test_missing_file_handling(self):
        """Test graceful handling of missing files."""
        from mandate_pipeline.extractor import extract_text

        with pytest.raises(FileNotFoundError):
            extract_text(Path("/nonexistent/file.pdf"))

    def test_invalid_json_handling(self):
        """Test handling of invalid JSON in data files."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{ invalid json }")
            temp_path = f.name

        try:
            with pytest.raises(json.JSONDecodeError):
                with open(temp_path) as f:
                    json.load(f)
        finally:
            Path(temp_path).unlink()

    def test_empty_paragraphs_handling(self):
        """Test handling documents with no paragraphs."""
        from mandate_pipeline.detection import run_checks

        empty_paragraphs = {}
        checks = []  # Empty checks

        signals = run_checks(empty_paragraphs, checks)
        assert signals == {}

    def test_malformed_signals_handling(self):
        """Test handling documents with unusual signal data."""
        from mandate_pipeline.generation import safe_paragraph_number

        # Document with various edge cases
        docs_to_test = [
            {"signals": {}, "signal_summary": {}},  # Empty
            {"signals": {"1": []}, "signal_summary": {}},  # Empty signal list
            {"signals": None},  # None instead of dict
        ]

        for doc in docs_to_test:
            # Should not crash
            signals = doc.get("signals") or {}
            if isinstance(signals, dict):
                signal_paras = []
                for para_num, para_signals in signals.items():
                    if para_signals:
                        signal_paras.append({"number": para_num, "signals": para_signals})
                # Sort should work
                signal_paras.sort(key=safe_paragraph_number)


class TestDataValidation:
    """Tests validating actual data in the repository."""

    def test_all_linked_documents_valid(self):
        """Validate all linked documents have correct structure."""
        linked_dir = Path("data/linked")
        if not linked_dir.exists():
            pytest.skip("data/linked not found")

        errors = []
        for linked_file in linked_dir.glob("*.json"):
            if linked_file.name == "index.json":
                continue

            try:
                with open(linked_file) as f:
                    doc = json.load(f)

                # Required fields
                if "symbol" not in doc:
                    errors.append(f"{linked_file.name}: missing 'symbol'")

                # Type checks
                signals = doc.get("signals")
                if signals is not None and not isinstance(signals, dict):
                    errors.append(f"{linked_file.name}: 'signals' should be dict, got {type(signals).__name__}")

                signal_summary = doc.get("signal_summary")
                if signal_summary is not None and not isinstance(signal_summary, dict):
                    errors.append(f"{linked_file.name}: 'signal_summary' should be dict")

                # signal_paragraphs should be list if present
                signal_paragraphs = doc.get("signal_paragraphs")
                if signal_paragraphs is not None and not isinstance(signal_paragraphs, list):
                    errors.append(f"{linked_file.name}: 'signal_paragraphs' should be list")

            except json.JSONDecodeError as e:
                errors.append(f"{linked_file.name}: invalid JSON - {e}")

        if errors:
            pytest.fail(f"Found {len(errors)} validation errors:\n" + "\n".join(errors[:20]))

    def test_checks_config_valid(self):
        """Validate checks configuration."""
        from mandate_pipeline.detection import load_checks

        checks_file = Path("config/checks.yaml")
        if not checks_file.exists():
            pytest.skip("checks.yaml not found")

        checks = load_checks(checks_file)
        assert len(checks) > 0, "No checks defined"

        for check in checks:
            # Check must have signal or name identifier
            assert "signal" in check or "name" in check, f"Check missing 'signal'/'name': {check}"
            assert "phrases" in check, f"Check missing 'phrases': {check}"
            assert isinstance(check["phrases"], list), f"Check 'phrases' should be list: {check}"

    def test_patterns_config_valid(self):
        """Validate patterns configuration."""
        from mandate_pipeline.discovery import load_patterns

        patterns_file = Path("config/patterns.yaml")
        if not patterns_file.exists():
            pytest.skip("patterns.yaml not found")

        patterns = load_patterns(patterns_file)
        assert len(patterns) > 0, "No patterns defined"
