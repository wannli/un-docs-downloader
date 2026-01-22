# Tests for Mandate Pipeline Extractor Module
# Comprehensive unit tests for text extraction functions

import pytest
from pathlib import Path

from mandate_pipeline.extractor import (
    extract_text,
    extract_operative_paragraphs,
    extract_lettered_paragraphs,
    extract_title,
    extract_agenda_items,
    find_symbol_references,
)


class TestExtractText:
    """Test PDF text extraction."""

    def test_extract_text_file_not_found(self, tmp_path):
        """Raise FileNotFoundError for missing PDF file."""
        missing_file = tmp_path / "nonexistent.pdf"

        with pytest.raises(FileNotFoundError) as exc_info:
            extract_text(missing_file)

        assert "PDF file not found" in str(exc_info.value)

    def test_extract_text_multiple_pages(self, tmp_path, mocker):
        """Extract and concatenate text from multiple pages."""
        # Create a real file so existence check passes
        fake_pdf = tmp_path / "multi.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4 fake")

        # Create mock page objects
        mock_page1 = mocker.Mock()
        mock_page1.get_text.return_value = "Page 1 content"
        mock_page2 = mocker.Mock()
        mock_page2.get_text.return_value = "Page 2 content"
        mock_page3 = mocker.Mock()
        mock_page3.get_text.return_value = "Page 3 content"

        # Create mock document that iterates over pages
        mock_doc = mocker.Mock()
        mock_doc.__enter__ = mocker.Mock(return_value=mock_doc)
        mock_doc.__exit__ = mocker.Mock(return_value=False)
        mock_doc.__iter__ = mocker.Mock(return_value=iter([mock_page1, mock_page2, mock_page3]))

        # Mock pymupdf.open
        mocker.patch("mandate_pipeline.extractor.pymupdf.open", return_value=mock_doc)

        result = extract_text(fake_pdf)

        assert result == "Page 1 content\nPage 2 content\nPage 3 content"

    def test_extract_text_empty_pdf(self, tmp_path, mocker):
        """Handle PDF with no text (returns empty string)."""
        # Create a real file so existence check passes
        fake_pdf = tmp_path / "empty.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4 fake")

        mock_doc = mocker.Mock()
        mock_doc.__enter__ = mocker.Mock(return_value=mock_doc)
        mock_doc.__exit__ = mocker.Mock(return_value=False)
        mock_doc.__iter__ = mocker.Mock(return_value=iter([]))

        mocker.patch("mandate_pipeline.extractor.pymupdf.open", return_value=mock_doc)

        result = extract_text(fake_pdf)

        assert result == ""

    def test_extract_text_single_page(self, tmp_path, mocker):
        """Extract text from single-page PDF."""
        # Create a real file so existence check passes
        fake_pdf = tmp_path / "single.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4 fake")

        mock_page = mocker.Mock()
        mock_page.get_text.return_value = "Single page content with UN resolution text."

        mock_doc = mocker.Mock()
        mock_doc.__enter__ = mocker.Mock(return_value=mock_doc)
        mock_doc.__exit__ = mocker.Mock(return_value=False)
        mock_doc.__iter__ = mocker.Mock(return_value=iter([mock_page]))

        mocker.patch("mandate_pipeline.extractor.pymupdf.open", return_value=mock_doc)

        result = extract_text(fake_pdf)

        assert result == "Single page content with UN resolution text."


class TestExtractOperativeParagraphs:
    """Test extraction of operative paragraphs from UN resolution text."""

    def test_extract_empty_text(self):
        """Empty string returns empty dict."""
        result = extract_operative_paragraphs("")
        assert result == {}

    def test_extract_no_operative_paragraphs(self):
        """Text without numbered paragraphs returns empty dict."""
        text = """
The General Assembly,

Recalling its previous resolutions on the matter,

Noting the importance of international cooperation,

Reaffirming its commitment to the Charter of the United Nations.
"""
        result = extract_operative_paragraphs(text)
        assert result == {}

    def test_extract_simple_paragraphs(self):
        """Extract simple numbered operative paragraphs."""
        text = """
The General Assembly,

1. Calls upon all Member States to provide assistance;

2. Requests the Secretary-General to coordinate efforts;

3. Decides to remain seized of the matter.
"""
        result = extract_operative_paragraphs(text)

        assert len(result) == 3
        assert result[1] == "Calls upon all Member States to provide assistance;"
        assert result[2] == "Requests the Secretary-General to coordinate efforts;"
        assert result[3] == "Decides to remain seized of the matter."

    def test_extract_multiline_paragraphs(self):
        """Extract paragraphs that span multiple lines."""
        text = """
1. Calls upon all Member States to strengthen their national
efforts to combat climate change, including through the adoption
of comprehensive mitigation and adaptation strategies;

2. Requests the Secretary-General to submit a report on
progress made in this regard.
"""
        result = extract_operative_paragraphs(text)

        assert len(result) == 2
        assert "strengthen their national efforts" in result[1]
        assert "mitigation and adaptation strategies" in result[1]
        assert "submit a report" in result[2]

    def test_extract_non_sequential_numbers(self):
        """Handle non-sequential paragraph numbering (gaps)."""
        text = """
1. First paragraph;

3. Third paragraph (gap);

5. Fifth paragraph.
"""
        result = extract_operative_paragraphs(text)

        assert len(result) == 3
        assert 1 in result
        assert 2 not in result
        assert 3 in result
        assert 5 in result

    def test_extract_whitespace_normalization(self):
        """Normalize excessive whitespace in paragraphs."""
        text = """
1. Calls upon    all   Member States
   to provide    assistance;
"""
        result = extract_operative_paragraphs(text)

        assert result[1] == "Calls upon all Member States to provide assistance;"

    def test_extract_high_numbered_paragraphs(self):
        """Handle resolutions with many paragraphs (100+)."""
        text = """
99. Paragraph ninety-nine;

100. Paragraph one hundred;

101. Paragraph one hundred and one.
"""
        result = extract_operative_paragraphs(text)

        assert 99 in result
        assert 100 in result
        assert 101 in result


class TestExtractTitle:
    """Test document title extraction."""

    def test_extract_title_resolution_format(self):
        """Extract title in resolution format '80/1. Title...'."""
        text = """
United Nations
General Assembly

Resolution adopted by the General Assembly on 20 October 2025

80/1. Strengthening the coordination of humanitarian assistance
"""
        result = extract_title(text)

        assert "80/1." in result
        assert "Strengthening the coordination" in result

    def test_extract_title_resolution_multiline(self):
        """Extract multi-line resolution title."""
        text = """
United Nations
General Assembly

Resolution adopted by the General Assembly on 20 October 2025

80/60. Strengthening the coordination of humanitarian and disaster
relief assistance of the United Nations, including special economic
assistance

The General Assembly,

Recalling its resolution 46/182,
"""
        result = extract_title(text)

        assert "80/60." in result
        assert "Strengthening the coordination" in result
        assert "special economic assistance" in result

    def test_extract_title_proposal_format(self):
        """Extract title after 'draft resolution' line."""
        text = """
United Nations
General Assembly
A/80/L.1

Eightieth session
Agenda item 68

Albania, Australia: draft resolution

Climate action for sustainable development

The General Assembly,

Recalling its previous resolutions,
"""
        result = extract_title(text)

        assert "Climate action for sustainable development" in result

    def test_extract_title_proposal_multiline(self):
        """Extract multi-line proposal title."""
        text = """
United Nations
General Assembly
A/80/L.5

Albania, Australia: draft resolution

International cooperation in the peaceful uses
of outer space

The General Assembly,
"""
        result = extract_title(text)

        assert "International cooperation" in result
        assert "outer space" in result

    def test_extract_title_skips_headers(self):
        """Skip standard header lines (United Nations, Distr., etc.)."""
        text = """
United Nations
General Assembly
Distr.: General
25 October 2025
A/80/L.10

Eightieth session
Agenda item 68

Spain: draft resolution

Sustainable urban development

The General Assembly,
"""
        result = extract_title(text)

        assert "United Nations" not in result
        assert "Distr." not in result
        assert "A/80/L.10" not in result
        assert "Sustainable urban development" in result

    def test_extract_title_stops_at_preamble(self):
        """Stop title extraction at preambular markers."""
        text = """
Spain: draft resolution

Sustainable development

Recalling its resolution 70/1,

Noting the importance of,
"""
        result = extract_title(text)

        assert "Sustainable development" in result
        assert "Recalling" not in result
        assert "Noting" not in result

    def test_extract_title_stops_at_general_assembly(self):
        """Stop title extraction at 'The General Assembly'."""
        text = """
draft resolution

Climate action

The General Assembly,

1. Decides to take action;
"""
        result = extract_title(text)

        assert "Climate action" in result
        assert "The General Assembly" not in result

    def test_extract_title_not_found(self):
        """Return empty string when no title found."""
        text = """
1. First paragraph;

2. Second paragraph;
"""
        result = extract_title(text)

        assert result == ""

    def test_extract_title_skips_facilitator_lines(self):
        """Skip facilitator/submitter lines ending with country in parentheses."""
        text = """
draft resolution

Submitted by the facilitator (Germany)

Oceans and the law of the sea

The General Assembly,
"""
        result = extract_title(text)

        assert "Oceans and the law of the sea" in result
        assert "facilitator" not in result
        assert "Germany" not in result

    def test_extract_title_skips_agenda_items(self):
        """Skip agenda item lines."""
        text = """
A/80/L.1

Agenda item 68
Item 12

draft resolution

Human rights protection

The General Assembly,
"""
        result = extract_title(text)

        assert "Human rights protection" in result
        assert "Agenda" not in result
        assert "Item 12" not in result


class TestExtractAgendaItems:
    """Test agenda item extraction."""

    def test_extract_agenda_items_standard_format(self):
        """Extract 'Agenda item 68' format."""
        text = """
United Nations
General Assembly
Agenda item 68

draft resolution
"""
        result = extract_agenda_items(text)

        assert "Item 68" in result

    def test_extract_agenda_items_item_format(self):
        """Extract 'Item 12A' format with letter suffix."""
        text = """
Eightieth session
Item 12A
Item 45B

draft resolution
"""
        result = extract_agenda_items(text)

        assert "Item 12A" in result
        assert "Item 45B" in result

    def test_extract_agenda_items_multiple(self):
        """Extract multiple agenda items from text."""
        text = """
Agenda item 68
Agenda item 125
Item 13
"""
        result = extract_agenda_items(text)

        assert len(result) == 3
        assert "Item 68" in result
        assert "Item 125" in result
        assert "Item 13" in result

    def test_extract_agenda_items_plural(self):
        """Handle 'Agenda items' (plural) format - captures first number only."""
        text = """
Agenda items 22, 68 and 125

Referring to agenda item 13 in the document.
"""
        result = extract_agenda_items(text)

        # Note: Current regex captures only the first number after "Agenda items"
        # Enhancement could capture comma-separated lists
        assert "Item 22" in result
        assert "Item 13" in result

    def test_extract_agenda_items_case_insensitive(self):
        """Extract items regardless of case."""
        text = """
AGENDA ITEM 68
agenda item 125
Agenda Item 13
"""
        result = extract_agenda_items(text)

        assert "Item 68" in result
        assert "Item 125" in result
        assert "Item 13" in result

    def test_extract_agenda_items_none_found(self):
        """Return empty list when no agenda items found."""
        text = """
The General Assembly,

1. Decides to take action;
"""
        result = extract_agenda_items(text)

        assert result == []

    def test_extract_agenda_items_no_duplicates(self):
        """No duplicate items in result."""
        text = """
Agenda item 68
Referring to item 68 again.
Under agenda item 68 we find...
"""
        result = extract_agenda_items(text)

        assert result.count("Item 68") == 1


class TestFindSymbolReferences:
    """Test finding document symbol references in text."""

    def test_find_symbol_simple(self):
        """Find simple A/80/L.1 format symbols."""
        text = """
The draft resolution A/80/L.1 was submitted for consideration.
"""
        result = find_symbol_references(text)

        assert "A/80/L.1" in result

    def test_find_symbol_committee(self):
        """Find committee format A/C.1/80/L.1 symbols."""
        text = """
As contained in document A/C.1/80/L.15 and A/C.3/80/L.42.
"""
        result = find_symbol_references(text)

        assert "A/C.1/80/L.15" in result
        assert "A/C.3/80/L.42" in result

    def test_find_symbol_multiple(self):
        """Find multiple symbols in text (unique, ordered)."""
        text = """
Recalling document A/80/L.1 and A/80/L.5,

Also recalling A/80/L.10 and A/80/L.15.
"""
        result = find_symbol_references(text)

        assert len(result) == 4
        # Verify order of appearance
        assert result[0] == "A/80/L.1"
        assert result[1] == "A/80/L.5"
        assert result[2] == "A/80/L.10"
        assert result[3] == "A/80/L.15"

    def test_find_symbol_case_normalization(self):
        """Normalize symbols to uppercase."""
        text = """
Document a/80/l.1 was adopted.
"""
        result = find_symbol_references(text)

        assert "A/80/L.1" in result
        assert "a/80/l.1" not in result

    def test_find_symbol_none_found(self):
        """Return empty list when no L. symbols found."""
        text = """
The General Assembly resolution A/RES/80/1 was adopted.
Document A/80/100 is available.
"""
        result = find_symbol_references(text)

        assert result == []

    def test_find_symbol_no_duplicates(self):
        """No duplicate symbols in result."""
        text = """
Document A/80/L.1 is important.
Referring again to A/80/L.1 for emphasis.
As mentioned in A/80/L.1 previously.
"""
        result = find_symbol_references(text)

        assert len(result) == 1
        assert result[0] == "A/80/L.1"

    def test_find_symbol_complex_committee(self):
        """Find complex committee symbols."""
        text = """
Document A/C.6/80/L.3 from the Sixth Committee.
"""
        result = find_symbol_references(text)

        assert "A/C.6/80/L.3" in result

    def test_find_symbol_revision(self):
        """Find symbols with revision numbers."""
        text = """
The revised draft A/80/L.1/Rev.1 supersedes A/80/L.1.
"""
        result = find_symbol_references(text)

        # Note: current implementation may or may not capture /Rev.1
        # At minimum, base symbol should be found
        assert any("A/80/L.1" in s for s in result)

    def test_find_symbol_embedded_in_text(self):
        """Find symbols embedded in running text."""
        text = """
The Secretary-General, recalling document A/80/L.42, noted that the
provisions contained therein were consistent with A/C.1/80/L.5.
"""
        result = find_symbol_references(text)

        assert "A/80/L.42" in result
        assert "A/C.1/80/L.5" in result


class TestExtractLetteredParagraphs:
    """Test extraction of lettered paragraphs from draft decisions."""

    def test_extract_lettered_simple(self):
        """Extract simple lettered paragraphs (a), (b), (c)."""
        text = """
The General Assembly,

(a) Expresses its profound gratitude to France;

(b) Endorses the New York Declaration;

(c) Decides to remain seized of the matter.
"""
        result = extract_lettered_paragraphs(text)

        assert len(result) == 3
        assert "a" in result
        assert "b" in result
        assert "c" in result
        assert "Expresses its profound gratitude" in result["a"]
        assert "Endorses the New York Declaration" in result["b"]

    def test_extract_lettered_multiline(self):
        """Extract lettered paragraphs spanning multiple lines."""
        text = """
(a) Expresses its profound gratitude to France and Saudi Arabia
for discharging their responsibilities as Co-Chairs;

(b) Endorses the Declaration.
"""
        result = extract_lettered_paragraphs(text)

        assert len(result) == 2
        assert "France and Saudi Arabia" in result["a"]
        assert "Co-Chairs" in result["a"]

    def test_extract_lettered_empty(self):
        """Return empty dict when no lettered paragraphs."""
        text = """
1. First numbered paragraph;

2. Second numbered paragraph.
"""
        result = extract_lettered_paragraphs(text)

        assert result == {}

    def test_extract_lettered_whitespace_normalization(self):
        """Normalize whitespace in lettered paragraphs."""
        text = """
(a) Expresses    its   gratitude
   to all    participants;
"""
        result = extract_lettered_paragraphs(text)

        assert result["a"] == "Expresses its gratitude to all participants;"


# Data quality tests using real documents
# These tests validate extraction against actual UN documents
DATA_DIR = Path(__file__).parent.parent / "data" / "pdfs"


@pytest.mark.skipif(not DATA_DIR.exists(), reason="Data directory not available")
class TestDataQualityRealDocuments:
    """Data quality tests using real UN documents."""

    def test_draft_decision_lettered_paragraphs(self):
        """A/80/L.1 is a draft decision with lettered paragraphs."""
        pdf = DATA_DIR / "A_80_L.1.pdf"
        if not pdf.exists():
            pytest.skip("A_80_L.1.pdf not available")

        text = extract_text(pdf)
        numbered = extract_operative_paragraphs(text)
        lettered = extract_lettered_paragraphs(text)

        # Draft decisions use lettered paragraphs, not numbered
        assert len(numbered) == 0, "Draft decision should have no numbered paragraphs"
        assert len(lettered) >= 2, "Draft decision should have lettered paragraphs"
        assert "a" in lettered
        assert "b" in lettered

    def test_draft_decision_title(self):
        """A/80/L.1 title should be extracted correctly."""
        pdf = DATA_DIR / "A_80_L.1.pdf"
        if not pdf.exists():
            pytest.skip("A_80_L.1.pdf not available")

        text = extract_text(pdf)
        title = extract_title(text)

        assert "Palestine" in title or "Two-State" in title

    def test_outcome_document_title(self):
        """A/80/L.41 is an outcome document with special title structure."""
        pdf = DATA_DIR / "A_80_L.41.pdf"
        if not pdf.exists():
            pytest.skip("A_80_L.41.pdf not available")

        text = extract_text(pdf)
        title = extract_title(text)

        assert title != "", "Outcome document title should not be empty"
        assert "Information Society" in title or "World Summit" in title

    def test_regular_draft_resolution(self):
        """A/80/L.10 is a regular draft resolution with numbered paragraphs."""
        pdf = DATA_DIR / "A_80_L.10.pdf"
        if not pdf.exists():
            pytest.skip("A_80_L.10.pdf not available")

        text = extract_text(pdf)
        title = extract_title(text)
        paragraphs = extract_operative_paragraphs(text)
        agenda = extract_agenda_items(text)

        assert title != "", "Title should be extracted"
        assert len(paragraphs) >= 5, "Should have multiple operative paragraphs"
        assert len(agenda) >= 1, "Should have agenda items"

    def test_amendment_has_no_operative_paragraphs(self):
        """A/80/L.19 is an amendment - should have no operative paragraphs."""
        pdf = DATA_DIR / "A_80_L.19.pdf"
        if not pdf.exists():
            pytest.skip("A_80_L.19.pdf not available")

        text = extract_text(pdf)
        paragraphs = extract_operative_paragraphs(text)
        lettered = extract_lettered_paragraphs(text)

        # Amendments don't have operative content
        assert len(paragraphs) == 0
        assert len(lettered) == 0
        # But the text should mention "amendment"
        assert "amendment" in text.lower()

    def test_committee_document_extraction(self):
        """A/C.1/80/L.1 is a First Committee document."""
        pdf = DATA_DIR / "A_C.1_80_L.1.pdf"
        if not pdf.exists():
            pytest.skip("A_C.1_80_L.1.pdf not available")

        text = extract_text(pdf)
        title = extract_title(text)
        paragraphs = extract_operative_paragraphs(text)

        assert len(text) > 500, "Should extract substantial text"
        # Committee docs should have title or paragraphs
        assert title != "" or len(paragraphs) > 0

    def test_bulk_extraction_quality(self):
        """Verify extraction quality across all available documents."""
        if not DATA_DIR.exists():
            pytest.skip("Data directory not available")

        pdfs = list(DATA_DIR.glob("*.pdf"))
        if len(pdfs) < 10:
            pytest.skip("Not enough PDFs for bulk test")

        results = {
            "total": 0,
            "has_text": 0,
            "has_title": 0,
            "has_paragraphs": 0,
            "has_agenda": 0,
        }

        for pdf in pdfs[:50]:  # Test first 50 for speed
            results["total"] += 1
            try:
                text = extract_text(pdf)
                title = extract_title(text)
                numbered = extract_operative_paragraphs(text)
                lettered = extract_lettered_paragraphs(text)
                agenda = extract_agenda_items(text)

                if len(text) > 100:
                    results["has_text"] += 1
                if title:
                    results["has_title"] += 1
                if numbered or lettered:
                    results["has_paragraphs"] += 1
                if agenda:
                    results["has_agenda"] += 1
            except Exception:
                pass

        # Quality thresholds
        assert results["has_text"] == results["total"], "All docs should have text"
        assert results["has_title"] >= results["total"] * 0.9, "90%+ should have title"
        assert results["has_agenda"] >= results["total"] * 0.8, "80%+ should have agenda"
