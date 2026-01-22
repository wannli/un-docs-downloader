# Tests for Mandate Pipeline
# TDD: Red -> Green -> Refactor

import pytest

from mandate_pipeline import (
    download_document,
    extract_text,
    extract_operative_paragraphs,
    load_checks,
    run_checks,
    load_patterns,
    generate_symbols,
    discover_documents,
)


class TestDownloadDocumentUnit:
    """Test downloading UN documents and saving locally."""

    def test_download_saves_file(self, tmp_path, mocker):
        """Given a valid symbol, download and save the PDF file."""
        # Mock the HTTP response
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.content = b"%PDF-1.4 fake pdf content"
        mock_response.headers = {"Content-Type": "application/pdf"}
        mock_response.raise_for_status = mocker.Mock()

        mock_get = mocker.patch("mandate_pipeline.downloader.requests.get")
        mock_get.return_value = mock_response

        # Download the document
        result = download_document("A/RES/77/1", output_dir=tmp_path)

        # Assert file was saved
        expected_file = tmp_path / "A_RES_77_1.pdf"
        assert expected_file.exists()
        assert expected_file.read_bytes() == b"%PDF-1.4 fake pdf content"
        assert result == expected_file


@pytest.mark.integration
class TestDownloadDocumentIntegration:
    """Integration tests that hit real UN servers."""

    def test_download_real_pdf(self, tmp_path):
        """Download a real UN resolution and verify it's a valid PDF."""
        result = download_document("A/RES/77/1", output_dir=tmp_path)

        # Assert file exists and is a PDF
        assert result.exists()
        assert result.suffix == ".pdf"

        # Check it's actually a PDF (starts with %PDF magic bytes)
        content = result.read_bytes()
        assert content[:4] == b"%PDF", f"Expected PDF, got: {content[:100]}"

        # Should be a reasonable size (at least 10KB for a resolution)
        assert len(content) > 10_000, f"File too small: {len(content)} bytes"


class TestExtractText:
    """Test PDF text extraction."""

    def test_extract_text_from_pdf(self, tmp_path):
        """Extract text from a downloaded UN resolution."""
        # First download a real PDF
        pdf_path = download_document("A/RES/77/1", output_dir=tmp_path)

        # Extract text
        text = extract_text(pdf_path)

        # Should return a non-empty string
        assert isinstance(text, str)
        assert len(text) > 100, "Extracted text too short"

        # Should contain expected content from A/RES/77/1
        # (General Assembly resolution about something)
        assert "General Assembly" in text or "United Nations" in text


class TestExtractOperativeParagraphs:
    """Test extraction of operative paragraphs from UN resolution text."""

    def test_extract_operative_paragraphs_from_text(self):
        """Extract numbered operative paragraphs from resolution text."""
        sample_text = """
The General Assembly,

Recalling its resolution 46/182,

Noting with concern the situation,

1. Calls upon all Member States to provide assistance;

2. Requests the Secretary-General to coordinate efforts;

3. Decides to remain seized of the matter.
"""
        paragraphs = extract_operative_paragraphs(sample_text)

        assert len(paragraphs) == 3
        assert paragraphs[1] == "Calls upon all Member States to provide assistance;"
        assert paragraphs[2] == "Requests the Secretary-General to coordinate efforts;"
        assert paragraphs[3] == "Decides to remain seized of the matter."

    def test_extract_operative_paragraphs_from_real_resolution(self, tmp_path):
        """Extract operative paragraphs from a real UN resolution."""
        # Download and extract text
        pdf_path = download_document("A/RES/77/1", output_dir=tmp_path)
        text = extract_text(pdf_path)

        # Extract operative paragraphs
        paragraphs = extract_operative_paragraphs(text)

        # Should have multiple paragraphs
        assert len(paragraphs) >= 1, "No operative paragraphs found"

        # Should be a dict with integer keys
        assert all(isinstance(k, int) for k in paragraphs.keys())

        # Paragraph 1 should exist and contain text
        assert 1 in paragraphs
        assert len(paragraphs[1]) > 10


class TestChecks:
    """Test the YAML-based check system."""

    def test_load_checks_from_yaml(self, tmp_path):
        """Load check definitions from a YAML file."""
        yaml_content = """
checks:
  - signal: "agenda"
    phrases:
      - "decides to include"

  - signal: "PGA"
    phrases:
      - "requests the President of the General Assembly"
      - "President of the General Assembly"
"""
        config_file = tmp_path / "checks.yaml"
        config_file.write_text(yaml_content)

        checks = load_checks(config_file)

        assert len(checks) == 2
        assert checks[0]["signal"] == "agenda"
        assert "decides to include" in checks[0]["phrases"]
        assert checks[1]["signal"] == "PGA"

    def test_run_checks_finds_signals(self):
        """Run checks against paragraphs and find matching signals."""
        checks = [
            {
                "signal": "agenda",
                "phrases": ["decides to include"],
            },
            {
                "signal": "PGA",
                "phrases": ["requests the President of the General Assembly"],
            },
        ]

        paragraphs = {
            1: "Decides to include this item in the agenda of its next session;",
            2: "Requests the Secretary-General to report back;",
            3: "Also requests the President of the General Assembly to convene a meeting;",
        }

        results = run_checks(paragraphs, checks)

        # Should find agenda signal in paragraph 1
        assert 1 in results
        assert "agenda" in results[1]

        # Should find PGA signal in paragraph 3
        assert 3 in results
        assert "PGA" in results[3]

        # Paragraph 2 should have no signals
        assert 2 not in results or len(results[2]) == 0

    def test_run_checks_case_insensitive(self):
        """Check matching should be case-insensitive."""
        checks = [
            {
                "signal": "agenda",
                "phrases": ["decides to include"],
            },
        ]

        paragraphs = {
            1: "DECIDES TO INCLUDE this in the agenda;",
        }

        results = run_checks(paragraphs, checks)

        assert 1 in results
        assert "agenda" in results[1]

    def test_run_checks_on_real_resolution(self, tmp_path):
        """Run checks against a real UN resolution."""
        # Download and process
        pdf_path = download_document("A/RES/77/1", output_dir=tmp_path)
        text = extract_text(pdf_path)
        paragraphs = extract_operative_paragraphs(text)

        checks = [
            {
                "signal": "Assembly",
                "phrases": ["General Assembly"],
            },
        ]

        results = run_checks(paragraphs, checks)

        # Should find at least one signal (General Assembly is commonly mentioned)
        assert len(results) > 0


class TestPatterns:
    """Test symbol pattern loading and generation."""

    def test_load_patterns_from_yaml(self, tmp_path):
        """Load symbol patterns from YAML config."""
        yaml_content = """
patterns:
  - name: "L documents"
    template: "A/{session}/L.{number}"
    session: 80
    start: 1

  - name: "Committee L documents"
    template: "A/C.{committee}/{session}/L.{number}"
    committee: [1, 2, 3, 4, 5, 6]
    session: 80
    start: 1

  - name: "Resolutions"
    template: "A/RES/{session}/{number}"
    session: 80
    start: 1
"""
        config_file = tmp_path / "patterns.yaml"
        config_file.write_text(yaml_content)

        patterns = load_patterns(config_file)

        assert len(patterns) == 3
        assert patterns[0]["name"] == "L documents"
        assert patterns[0]["template"] == "A/{session}/L.{number}"
        assert patterns[0]["session"] == 80

    def test_generate_symbols_simple_pattern(self):
        """Generate symbols from a simple pattern."""
        pattern = {
            "name": "L documents",
            "template": "A/{session}/L.{number}",
            "session": 80,
            "start": 1,
        }

        # Generate first 3 symbols
        symbols = list(generate_symbols(pattern, count=3))

        assert symbols == ["A/80/L.1", "A/80/L.2", "A/80/L.3"]

    def test_generate_symbols_resolution_pattern(self):
        """Generate resolution symbols."""
        pattern = {
            "name": "Resolutions",
            "template": "A/RES/{session}/{number}",
            "session": 77,
            "start": 1,
        }

        symbols = list(generate_symbols(pattern, count=3))

        assert symbols == ["A/RES/77/1", "A/RES/77/2", "A/RES/77/3"]


class TestDiscoverDocuments:
    """Test document discovery with stop-after-N-misses logic."""

    def test_discover_stops_after_consecutive_misses(self, mocker):
        """Discovery stops after 3 consecutive misses."""
        pattern = {
            "name": "test",
            "template": "A/{session}/L.{number}",
            "session": 80,
            "start": 1,
        }

        # Mock document_exists: 1,2,3 exist, then 4,5,6 don't exist
        mock_exists = mocker.patch("mandate_pipeline.pipeline.document_exists")
        mock_exists.side_effect = [True, True, True, False, False, False]

        found = list(discover_documents(pattern, max_consecutive_misses=3))

        assert found == ["A/80/L.1", "A/80/L.2", "A/80/L.3"]
        assert mock_exists.call_count == 6

    def test_discover_resets_miss_count_on_hit(self, mocker):
        """Miss counter resets when a document is found."""
        pattern = {
            "name": "test",
            "template": "A/{session}/L.{number}",
            "session": 80,
            "start": 1,
        }

        # Pattern: hit, miss, miss, hit, miss, miss, miss (stop)
        mock_exists = mocker.patch("mandate_pipeline.pipeline.document_exists")
        mock_exists.side_effect = [True, False, False, True, False, False, False]

        found = list(discover_documents(pattern, max_consecutive_misses=3))

        assert found == ["A/80/L.1", "A/80/L.4"]

    def test_discover_real_documents(self, tmp_path):
        """Integration test: discover real L documents."""
        pattern = {
            "name": "L documents",
            "template": "A/{session}/L.{number}",
            "session": 77,  # Use session 77 which should have some L docs
            "start": 1,
        }

        # Just find first few to verify it works
        found = []
        for symbol in discover_documents(pattern, max_consecutive_misses=3):
            found.append(symbol)
            if len(found) >= 2:  # Stop early for test speed
                break

        # Should find at least one document
        assert len(found) >= 1
        assert found[0] == "A/77/L.1"


class TestSyncState:
    """Test sync state management for incremental updates."""

    def test_load_state_empty(self, tmp_path):
        """Load state returns empty dict if no state file exists."""
        from mandate_pipeline.pipeline import load_sync_state

        state = load_sync_state(tmp_path / "state.json")
        assert state == {"patterns": {}}

    def test_save_and_load_state(self, tmp_path):
        """Save and load sync state."""
        from mandate_pipeline.pipeline import load_sync_state, save_sync_state

        state = {
            "last_sync": "2026-01-20T06:00:00Z",
            "patterns": {
                "L documents": {"highest_found": 42},
            },
        }

        state_file = tmp_path / "state.json"
        save_sync_state(state_file, state)
        loaded = load_sync_state(state_file)

        assert loaded["last_sync"] == "2026-01-20T06:00:00Z"
        assert loaded["patterns"]["L documents"]["highest_found"] == 42

    def test_get_start_number_no_state(self, tmp_path):
        """Get start number returns pattern start if no state."""
        from mandate_pipeline.pipeline import get_start_number

        pattern = {"name": "L documents", "start": 1}
        state = {"patterns": {}}

        assert get_start_number(pattern, state) == 1

    def test_get_start_number_with_state(self, tmp_path):
        """Get start number returns highest_found + 1 if state exists."""
        from mandate_pipeline.pipeline import get_start_number

        pattern = {"name": "L documents", "start": 1}
        state = {"patterns": {"L documents": {"highest_found": 42}}}

        assert get_start_number(pattern, state) == 43


class TestSyncDocuments:
    """Test incremental document sync."""

    def test_sync_downloads_new_documents(self, tmp_path, mocker):
        """Sync discovers and downloads new documents."""
        from mandate_pipeline.pipeline import sync_pattern

        pattern = {
            "name": "L documents",
            "template": "A/{session}/L.{number}",
            "session": 80,
            "start": 1,
        }
        state = {"patterns": {"L documents": {"highest_found": 2}}}

        # Mock: docs 3, 4 exist, then 5, 6, 7 don't
        mock_exists = mocker.patch("mandate_pipeline.pipeline.document_exists")
        mock_exists.side_effect = [True, True, False, False, False]

        # Mock download
        mock_download = mocker.patch("mandate_pipeline.pipeline.download_document")
        mock_download.return_value = tmp_path / "fake.pdf"

        data_dir = tmp_path / "data"
        data_dir.mkdir()

        new_docs, new_highest = sync_pattern(
            pattern, state, data_dir, max_consecutive_misses=3
        )

        assert new_docs == ["A/80/L.3", "A/80/L.4"]
        assert new_highest == 4
        assert mock_download.call_count == 2

    def test_sync_no_new_documents(self, tmp_path, mocker):
        """Sync returns empty list when no new documents."""
        from mandate_pipeline.pipeline import sync_pattern

        pattern = {
            "name": "L documents",
            "template": "A/{session}/L.{number}",
            "session": 80,
            "start": 1,
        }
        state = {"patterns": {"L documents": {"highest_found": 42}}}

        # Mock: 43, 44, 45 all don't exist
        mock_exists = mocker.patch("mandate_pipeline.pipeline.document_exists")
        mock_exists.side_effect = [False, False, False]

        mock_download = mocker.patch("mandate_pipeline.pipeline.download_document")

        data_dir = tmp_path / "data"
        data_dir.mkdir()

        new_docs, new_highest = sync_pattern(
            pattern, state, data_dir, max_consecutive_misses=3
        )

        assert new_docs == []
        assert new_highest == 42  # unchanged
        assert mock_download.call_count == 0


class TestStaticGenerator:
    """Test static site generation."""

    def test_generate_data_json(self, tmp_path):
        """Generate data.json with correct structure."""
        from mandate_pipeline.static_generator import generate_data_json

        documents = [
            {
                "symbol": "A/80/L.1",
                "filename": "A_80_L_1.pdf",
                "paragraphs": {1: "First paragraph", 2: "Second paragraph"},
                "signals": {1: ["agenda"]},
            }
        ]
        checks = [{"signal": "agenda", "phrases": ["decides to include"]}]

        output_dir = tmp_path / "docs"
        output_dir.mkdir()

        generate_data_json(documents, checks, output_dir)

        import json

        data = json.loads((output_dir / "data.json").read_text())

        assert "generated_at" in data
        assert len(data["documents"]) == 1
        assert data["documents"][0]["symbol"] == "A/80/L.1"
        assert data["checks"] == checks

    def test_generate_search_index(self, tmp_path):
        """Generate Lunr.js compatible search index."""
        from mandate_pipeline.static_generator import generate_search_index

        documents = [
            {
                "symbol": "A/80/L.1",
                "filename": "A_80_L_1.pdf",
                "paragraphs": {1: "Climate change action", 2: "Sustainable development"},
                "signals": {1: ["agenda"]},
            },
            {
                "symbol": "A/80/L.2",
                "filename": "A_80_L_2.pdf",
                "paragraphs": {1: "Human rights protection"},
                "signals": {},
            },
        ]

        output_dir = tmp_path / "docs"
        output_dir.mkdir()

        generate_search_index(documents, output_dir)

        import json

        index_data = json.loads((output_dir / "search-index.json").read_text())

        # Should have documents array for client-side indexing
        assert "documents" in index_data
        assert len(index_data["documents"]) == 2
        assert index_data["documents"][0]["symbol"] == "A/80/L.1"
        assert "Climate change" in index_data["documents"][0]["content"]

    def test_generate_document_page(self, tmp_path):
        """Generate individual document HTML page."""
        from mandate_pipeline.static_generator import generate_document_page

        doc = {
            "symbol": "A/80/L.1",
            "filename": "A_80_L.1.pdf",
            "paragraphs": {1: "First paragraph about agenda", 2: "Second paragraph"},
            "signals": {1: ["agenda"]},
            "un_url": "https://docs.un.org/en/a/80/l.1?direct=true",
        }
        checks = [{"signal": "agenda", "phrases": ["decides to include"]}]

        output_dir = tmp_path / "docs" / "documents"
        output_dir.mkdir(parents=True)

        generate_document_page(doc, checks, output_dir)

        html_file = output_dir / "A_80_L.1.html"
        assert html_file.exists()

        content = html_file.read_text()
        assert "A/80/L.1" in content
        assert "First paragraph about agenda" in content
        assert "agenda" in content

    def test_generate_signal_page(self, tmp_path):
        """Generate signal-filtered page."""
        from mandate_pipeline.static_generator import generate_signal_page

        documents = [
            {
                "symbol": "A/80/L.1",
                "filename": "A_80_L.1.pdf",
                "paragraphs": {1: "About agenda items"},
                "signals": {1: ["agenda"]},
                "signal_summary": {"agenda": 1},
                "un_url": "https://docs.un.org/en/a/80/l.1?direct=true",
                "is_adopted_draft": False,
            },
            {
                "symbol": "A/80/L.2",
                "filename": "A_80_L.2.pdf",
                "paragraphs": {1: "No agenda here"},
                "signals": {},
                "signal_summary": {},
                "un_url": "https://docs.un.org/en/a/80/l.2?direct=true",
                "is_adopted_draft": False,
            },
        ]
        check = {"signal": "agenda", "phrases": ["decides to include"]}
        checks = [check]

        output_dir = tmp_path / "docs" / "signals"
        output_dir.mkdir(parents=True)

        generate_signal_page(documents, documents, check, checks, output_dir)

        html_file = output_dir / "agenda.html"
        assert html_file.exists()

        content = html_file.read_text()
        assert "A/80/L.1" in content
        # A/80/L.2 should not be prominently featured (no agenda signal)

    def test_get_un_document_url(self):
        """Generate correct UN ODS URL for a symbol."""
        from mandate_pipeline.static_generator import get_un_document_url

        url = get_un_document_url("A/80/L.1")
        assert url == "https://docs.un.org/en/a/80/l.1?direct=true"
        
        # Test resolution format
        url_res = get_un_document_url("A/RES/80/233")
        assert url_res == "https://docs.un.org/en/a/res/80/233?direct=true"

    def test_load_all_documents(self, tmp_path, mocker):
        """Load all documents from data directory."""
        from mandate_pipeline.static_generator import load_all_documents

        # Create fake PDF structure (flat pdfs/ directory)
        pdf_dir = tmp_path / "data" / "pdfs"
        pdf_dir.mkdir(parents=True)
        (pdf_dir / "A_80_L.1.pdf").write_bytes(b"%PDF-1.4 fake")

        # Mock extraction
        mocker.patch(
            "mandate_pipeline.static_generator.extract_text",
            return_value="1. First operative paragraph about agenda;",
        )
        mocker.patch(
            "mandate_pipeline.static_generator.extract_operative_paragraphs",
            return_value={1: "First operative paragraph about agenda;"},
        )

        checks = [{"signal": "agenda", "phrases": ["agenda"]}]

        documents = load_all_documents(tmp_path / "data", checks)

        assert len(documents) == 1
        assert documents[0]["symbol"] == "A/80/L.1"
        assert documents[0]["paragraphs"] == {1: "First operative paragraph about agenda;"}
        assert 1 in documents[0]["signals"]
        assert "agenda" in documents[0]["signals"][1]

    def test_generate_site_creates_all_files(self, tmp_path, mocker):
        """Full site generation creates expected file structure."""
        from mandate_pipeline.static_generator import generate_site

        # Setup directories
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        data_dir = tmp_path / "data"
        (data_dir / "pdfs").mkdir(parents=True)
        output_dir = tmp_path / "docs"

        # Create config files
        (config_dir / "checks.yaml").write_text(
            """
checks:
  - signal: "agenda"
    phrases:
      - "agenda"
"""
        )
        (config_dir / "patterns.yaml").write_text(
            """
patterns:
  - name: "L documents"
    template: "A/{session}/L.{number}"
    session: 80
    start: 1
"""
        )

        # Create fake PDF (flat pdfs/ directory)
        (data_dir / "pdfs" / "A_80_L.1.pdf").write_bytes(b"%PDF-1.4 fake")

        # Mock extraction
        mocker.patch(
            "mandate_pipeline.static_generator.extract_text",
            return_value="1. First paragraph about agenda;",
        )
        mocker.patch(
            "mandate_pipeline.static_generator.extract_operative_paragraphs",
            return_value={1: "First paragraph about agenda;"},
        )

        generate_site(config_dir, data_dir, output_dir)

        # Check generated files
        assert (output_dir / "index.html").exists()
        assert (output_dir / "documents" / "index.html").exists()
        assert (output_dir / "documents" / "A_80_L.1.html").exists()
        assert (output_dir / "signals" / "agenda.html").exists()
        assert (output_dir / "data.json").exists()
        assert (output_dir / "search-index.json").exists()
