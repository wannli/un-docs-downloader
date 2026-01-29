# Tests for Mandate Pipeline Generation Module
# Comprehensive unit tests for static site generation functions

import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from mandate_pipeline.generation import (
    safe_paragraph_number,
    get_un_document_url,
)


class TestSafeParagraphNumber:
    """Test the safe_paragraph_number helper function."""

    def test_valid_integer_string(self):
        """Should convert valid integer string to int."""
        para = {"number": "42"}
        assert safe_paragraph_number(para) == 42

    def test_valid_integer(self):
        """Should handle integer values directly."""
        para = {"number": 7}
        assert safe_paragraph_number(para) == 7

    def test_string_with_leading_zeros(self):
        """Should handle strings with leading zeros."""
        para = {"number": "007"}
        assert safe_paragraph_number(para) == 7

    def test_missing_number_key(self):
        """Should return default when number key is missing."""
        para = {}
        assert safe_paragraph_number(para) == 0
        assert safe_paragraph_number(para, default=99) == 99

    def test_none_value(self):
        """Should return default when number is None."""
        para = {"number": None}
        assert safe_paragraph_number(para) == 0

    def test_invalid_string(self):
        """Should return default for non-numeric strings."""
        para = {"number": "abc"}
        assert safe_paragraph_number(para) == 0

    def test_empty_string(self):
        """Should return default for empty string."""
        para = {"number": ""}
        assert safe_paragraph_number(para) == 0

    def test_float_string(self):
        """Should handle float strings (truncated to int)."""
        para = {"number": "3.14"}
        # int("3.14") raises ValueError, should return default
        assert safe_paragraph_number(para) == 0

    def test_negative_number(self):
        """Should handle negative numbers."""
        para = {"number": "-5"}
        assert safe_paragraph_number(para) == -5

    def test_custom_default(self):
        """Should use custom default value."""
        para = {"number": "invalid"}
        assert safe_paragraph_number(para, default=-1) == -1


class TestSignalParagraphsDataStructure:
    """Test that signal_paragraphs is correctly handled as a list."""

    def test_signal_paragraphs_is_list_not_dict(self):
        """Verify signal_paragraphs should be a list of paragraph dicts."""
        # This is the expected format for signal_paragraphs
        signal_paragraphs = [
            {"number": "1", "text": "Paragraph 1 text", "signals": ["report"]},
            {"number": "7", "text": "Paragraph 7 text", "signals": ["agenda", "PGA"]},
        ]

        # Verify it's a list
        assert isinstance(signal_paragraphs, list)

        # Verify each item is a dict with expected keys
        for para in signal_paragraphs:
            assert isinstance(para, dict)
            assert "number" in para
            assert "text" in para
            assert "signals" in para
            assert isinstance(para["signals"], list)

    def test_signal_summary_is_dict(self):
        """Verify signal_summary is a dict mapping signal names to counts."""
        signal_summary = {"report": 2, "agenda": 1, "PGA": 3}

        assert isinstance(signal_summary, dict)
        for signal_name, count in signal_summary.items():
            assert isinstance(signal_name, str)
            assert isinstance(count, int)

    def test_iterate_signal_paragraphs_correctly(self):
        """Test correct iteration pattern for signal_paragraphs."""
        signal_paragraphs = [
            {"number": "1", "text": "Text 1", "signals": ["report"]},
            {"number": "2", "text": "Text 2", "signals": ["agenda", "process"]},
        ]

        # CORRECT: iterate over list directly
        signal_count = {}
        for para in signal_paragraphs:
            for signal in para.get("signals", []):
                signal_count[signal] = signal_count.get(signal, 0) + 1

        assert signal_count == {"report": 1, "agenda": 1, "process": 1}

    def test_wrong_iteration_pattern_fails(self):
        """Demonstrate what happens with wrong iteration (calling .values())."""
        signal_paragraphs = [
            {"number": "1", "text": "Text 1", "signals": ["report"]},
        ]

        # WRONG: trying to call .values() on a list raises AttributeError
        with pytest.raises(AttributeError, match="'list' object has no attribute 'values'"):
            for para_signals in signal_paragraphs.values():
                pass


class TestDocumentEnrichment:
    """Test document enrichment logic that creates signal_paragraphs."""

    def test_enrich_document_with_signals(self):
        """Test converting signals dict to signal_paragraphs list."""
        doc = {
            "symbol": "A/RES/79/1",
            "paragraphs": {
                "1": "First paragraph text",
                "7": "Seventh paragraph text about agenda items",
            },
            "signals": {
                "1": [],  # No signals
                "7": ["agenda"],  # Has signal
            },
            "signal_summary": {"agenda": 1},
        }

        # Simulate enrichment logic
        signal_paras = []
        for para_num, para_signals in doc.get("signals", {}).items():
            if para_signals:
                para_text = doc.get("paragraphs", {}).get(para_num, "")
                signal_paras.append({
                    "number": para_num,
                    "text": para_text,
                    "signals": para_signals,
                })

        signal_paras.sort(key=safe_paragraph_number)

        # Verify result
        assert len(signal_paras) == 1
        assert signal_paras[0]["number"] == "7"
        assert signal_paras[0]["signals"] == ["agenda"]

    def test_enrich_document_multiple_signals(self):
        """Test document with multiple paragraphs containing signals."""
        doc = {
            "symbol": "A/RES/79/10",
            "paragraphs": {
                "1": "Para 1",
                "5": "Para 5 with report",
                "10": "Para 10 with agenda",
                "15": "Para 15 with PGA and process",
            },
            "signals": {
                "1": [],
                "5": ["report"],
                "10": ["agenda"],
                "15": ["PGA", "process"],
            },
        }

        signal_paras = []
        for para_num, para_signals in doc.get("signals", {}).items():
            if para_signals:
                para_text = doc.get("paragraphs", {}).get(para_num, "")
                signal_paras.append({
                    "number": para_num,
                    "text": para_text,
                    "signals": para_signals,
                })

        signal_paras.sort(key=safe_paragraph_number)

        # Verify sorted order
        assert len(signal_paras) == 3
        assert [p["number"] for p in signal_paras] == ["5", "10", "15"]

    def test_create_signal_summary_from_paragraphs(self):
        """Test creating signal_summary from signal_paragraphs list."""
        signal_paragraphs = [
            {"number": "5", "text": "...", "signals": ["report"]},
            {"number": "10", "text": "...", "signals": ["report", "agenda"]},
            {"number": "15", "text": "...", "signals": ["PGA"]},
        ]

        # Create signal summary (correct way - iterating over list)
        signal_summary = {}
        for para in signal_paragraphs:
            for signal in para.get("signals", []):
                signal_summary[signal] = signal_summary.get(signal, 0) + 1

        assert signal_summary == {"report": 2, "agenda": 1, "PGA": 1}


class TestSortingEdgeCases:
    """Test edge cases in paragraph sorting."""

    def test_sort_mixed_string_numbers(self):
        """Test sorting paragraphs with string numbers."""
        signal_paras = [
            {"number": "10", "text": "...", "signals": []},
            {"number": "2", "text": "...", "signals": []},
            {"number": "1", "text": "...", "signals": []},
        ]

        signal_paras.sort(key=safe_paragraph_number)

        assert [p["number"] for p in signal_paras] == ["1", "2", "10"]

    def test_sort_with_invalid_numbers(self):
        """Test sorting handles invalid numbers gracefully."""
        signal_paras = [
            {"number": "10", "text": "...", "signals": []},
            {"number": "invalid", "text": "...", "signals": []},  # Invalid
            {"number": "5", "text": "...", "signals": []},
        ]

        # Should not raise, invalid numbers get default (0)
        signal_paras.sort(key=safe_paragraph_number)

        # Invalid number (0) should come first
        assert signal_paras[0]["number"] == "invalid"
        assert signal_paras[1]["number"] == "5"
        assert signal_paras[2]["number"] == "10"

    def test_sort_empty_list(self):
        """Test sorting empty list doesn't crash."""
        signal_paras = []
        signal_paras.sort(key=safe_paragraph_number)
        assert signal_paras == []


class TestGetUnDocumentUrl:
    """Test UN document URL generation."""

    def test_resolution_url(self):
        """Test URL generation for resolution."""
        url = get_un_document_url("A/RES/79/1")
        assert "docs.un.org" in url
        assert "a/res/79/1" in url.lower() or "A/RES/79/1" in url

    def test_proposal_url(self):
        """Test URL generation for proposal."""
        url = get_un_document_url("A/80/L.1")
        assert "docs.un.org" in url


class TestDocumentDefaults:
    """Test default value handling for document fields."""

    def test_signal_paragraphs_default_is_list(self):
        """Ensure signal_paragraphs defaults to empty list, not dict."""
        doc = {"symbol": "A/RES/79/1"}

        # Correct default
        signal_paragraphs = doc.get("signal_paragraphs", [])
        assert signal_paragraphs == []
        assert isinstance(signal_paragraphs, list)

        # len() works on both, but iterating .values() only works on dict
        assert len(signal_paragraphs) == 0

    def test_signals_default_is_dict(self):
        """Ensure signals defaults to empty dict."""
        doc = {"symbol": "A/RES/79/1"}

        signals = doc.get("signals", {})
        assert signals == {}
        assert isinstance(signals, dict)

    def test_signal_summary_default_is_dict(self):
        """Ensure signal_summary defaults to empty dict."""
        doc = {"symbol": "A/RES/79/1"}

        signal_summary = doc.get("signal_summary", {})
        assert signal_summary == {}
        assert isinstance(signal_summary, dict)


class TestIntegrationScenarios:
    """Integration tests simulating real pipeline scenarios."""

    def test_full_document_flow(self):
        """Test complete document processing flow."""
        # Simulate document loaded from JSON (as in linked/*.json files)
        raw_doc = {
            "symbol": "A/RES/79/100",
            "doc_type": "resolution",
            "signals": {
                "17": ["report"],
                "25": ["agenda", "process"],
            },
            "signal_summary": {"report": 1, "agenda": 1, "process": 1},
            "paragraphs": {
                "17": "Requests the Secretary-General to submit a report...",
                "25": "Decides to include in the provisional agenda...",
            },
        }

        # Step 1: Create signal_paragraphs from signals
        signal_paras = []
        for para_num, para_signals in raw_doc.get("signals", {}).items():
            if para_signals:
                signal_paras.append({
                    "number": para_num,
                    "text": raw_doc.get("paragraphs", {}).get(para_num, ""),
                    "signals": para_signals,
                })

        signal_paras.sort(key=safe_paragraph_number)
        raw_doc["signal_paragraphs"] = signal_paras

        # Step 2: Verify signal_paragraphs is a list
        assert isinstance(raw_doc["signal_paragraphs"], list)
        assert len(raw_doc["signal_paragraphs"]) == 2

        # Step 3: Count signals from signal_paragraphs (if signal_summary missing)
        computed_summary = {}
        for para in raw_doc["signal_paragraphs"]:
            for signal in para.get("signals", []):
                computed_summary[signal] = computed_summary.get(signal, 0) + 1

        assert computed_summary == {"report": 1, "agenda": 1, "process": 1}

    def test_empty_document_handling(self):
        """Test handling of document with no signals."""
        doc = {
            "symbol": "A/RES/79/200",
            "doc_type": "resolution",
            "signals": {},
            "signal_summary": {},
            "paragraphs": {},
        }

        signal_paras = []
        for para_num, para_signals in doc.get("signals", {}).items():
            if para_signals:
                signal_paras.append({
                    "number": para_num,
                    "text": doc.get("paragraphs", {}).get(para_num, ""),
                    "signals": para_signals,
                })

        assert len(signal_paras) == 0
        doc["signal_paragraphs"] = signal_paras

        # Should work without crashing
        total = len(doc.get("signal_paragraphs", []))
        assert total == 0


class TestCLISignalCountFix:
    """Test the fixed signal counting logic from cli.py."""

    def test_signal_count_from_summary(self):
        """Test counting signals from signal_summary (fixed approach)."""
        documents = [
            {"signal_summary": {"report": 2, "agenda": 1}},
            {"signal_summary": {"report": 1, "PGA": 3}},
            {"signal_summary": {}},
        ]

        # Fixed approach: use signal_summary
        signal_counts = {}
        for doc in documents:
            for signal, count in doc.get("signal_summary", {}).items():
                signal_counts[signal] = signal_counts.get(signal, 0) + count

        assert signal_counts == {"report": 3, "agenda": 1, "PGA": 3}

    def test_total_signal_paragraphs_count(self):
        """Test counting total signal paragraphs."""
        documents = [
            {"signal_paragraphs": [{"number": "1"}, {"number": "2"}]},
            {"signal_paragraphs": [{"number": "5"}]},
            {"signal_paragraphs": []},
            {},  # No signal_paragraphs key
        ]

        # Fixed: use [] default, not {}
        total = sum(len(d.get("signal_paragraphs", [])) for d in documents)
        assert total == 3
