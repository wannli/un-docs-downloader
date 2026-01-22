# Tests for Mandate Pipeline Linking Module
# Unit tests for document linkage and UN Digital Library integration

from pathlib import Path

import pytest

from mandate_pipeline.linking import (
    symbol_to_filename,
    filename_to_symbol,
    classify_symbol,
    normalize_symbol,
    normalize_title,
    is_resolution,
    is_proposal,
    is_excluded_draft_symbol,
    is_base_proposal_doc,
    link_documents,
    annotate_linkage,
    fetch_undl_metadata,
    _parse_undl_marc_xml,
)


# =============================================================================
# UNIT TESTS: UN Digital Library Integration
# =============================================================================


# Sample MARC XML response for testing
SAMPLE_MARC_XML = """<?xml version="1.0" encoding="UTF-8"?>
<collection xmlns="http://www.loc.gov/MARC21/slim">
  <record>
    <datafield tag="191" ind1=" " ind2=" ">
      <subfield code="a">A/RES/80/142</subfield>
      <subfield code="b">A/</subfield>
      <subfield code="c">80</subfield>
    </datafield>
    <datafield tag="993" ind1="2" ind2=" ">
      <subfield code="a">A/C.2/80/L.35/Rev.1</subfield>
    </datafield>
    <datafield tag="993" ind1="4" ind2=" ">
      <subfield code="a">A/80/PV.64</subfield>
    </datafield>
    <datafield tag="993" ind1="2" ind2=" ">
      <subfield code="a">A/80/555</subfield>
    </datafield>
  </record>
</collection>
"""

SAMPLE_MARC_XML_NO_DRAFT = """<?xml version="1.0" encoding="UTF-8"?>
<collection xmlns="http://www.loc.gov/MARC21/slim">
  <record>
    <datafield tag="191" ind1=" " ind2=" ">
      <subfield code="a">A/RES/80/166</subfield>
    </datafield>
    <datafield tag="993" ind1="4" ind2=" ">
      <subfield code="a">A/80/PV.70</subfield>
    </datafield>
  </record>
</collection>
"""

SAMPLE_MARC_XML_MULTIPLE_DRAFTS = """<?xml version="1.0" encoding="UTF-8"?>
<collection xmlns="http://www.loc.gov/MARC21/slim">
  <record>
    <datafield tag="191" ind1=" " ind2=" ">
      <subfield code="a">A/RES/80/100</subfield>
    </datafield>
    <datafield tag="993" ind1="2" ind2=" ">
      <subfield code="a">A/80/L.50</subfield>
    </datafield>
    <datafield tag="993" ind1="2" ind2=" ">
      <subfield code="a">A/80/L.51</subfield>
    </datafield>
  </record>
</collection>
"""


class TestParseUndlMarcXml:
    """Tests for MARC XML parsing."""

    def test_parse_resolution_with_draft(self):
        """Parse resolution metadata with draft symbol in tag 993."""
        result = _parse_undl_marc_xml(SAMPLE_MARC_XML, "A/RES/80/142")

        assert result is not None
        assert result["symbol"] == "A/RES/80/142"
        assert "A/C.2/80/L.35/Rev.1" in result["related_symbols"]
        assert "A/80/PV.64" in result["related_symbols"]
        assert result["draft_symbols"] == ["A/C.2/80/L.35/Rev.1"]
        assert result["base_proposal"] == "A/C.2/80/L.35/Rev.1"

    def test_parse_resolution_no_draft(self):
        """Parse resolution without draft symbol."""
        result = _parse_undl_marc_xml(SAMPLE_MARC_XML_NO_DRAFT, "A/RES/80/166")

        assert result is not None
        assert result["symbol"] == "A/RES/80/166"
        assert result["draft_symbols"] == []
        assert result["base_proposal"] is None

    def test_parse_resolution_multiple_drafts(self):
        """Parse resolution with multiple draft symbols."""
        result = _parse_undl_marc_xml(SAMPLE_MARC_XML_MULTIPLE_DRAFTS, "A/RES/80/100")

        assert result is not None
        assert len(result["draft_symbols"]) == 2
        assert "A/80/L.50" in result["draft_symbols"]
        assert "A/80/L.51" in result["draft_symbols"]
        assert result["base_proposal"] == "A/80/L.50"

    def test_parse_symbol_not_found(self):
        """Return None when target symbol not in XML."""
        result = _parse_undl_marc_xml(SAMPLE_MARC_XML, "A/RES/99/999")

        assert result is None

    def test_parse_invalid_xml(self):
        """Return None for malformed XML."""
        result = _parse_undl_marc_xml("<invalid>not xml", "A/RES/80/142")

        assert result is None

    def test_parse_empty_xml(self):
        """Return None for empty collection."""
        empty_xml = """<?xml version="1.0"?>
        <collection xmlns="http://www.loc.gov/MARC21/slim">
        </collection>
        """
        result = _parse_undl_marc_xml(empty_xml, "A/RES/80/142")

        assert result is None

    def test_parse_case_insensitive_symbol_match(self):
        """Match symbol case-insensitively."""
        result = _parse_undl_marc_xml(SAMPLE_MARC_XML, "a/res/80/142")

        assert result is not None
        assert result["symbol"] == "a/res/80/142"


class TestFetchUndlMetadata:
    """Tests for UN Digital Library API fetching."""

    def test_fetch_success(self, mocker):
        """Fetch metadata successfully from UNDL."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.text = SAMPLE_MARC_XML
        mock_response.raise_for_status = mocker.Mock()

        mocker.patch("mandate_pipeline.linking.requests.get", return_value=mock_response)

        result = fetch_undl_metadata("A/RES/80/142")

        assert result is not None
        assert result["base_proposal"] == "A/C.2/80/L.35/Rev.1"

    def test_fetch_network_error(self, mocker):
        """Return None on network error."""
        import requests

        mocker.patch(
            "mandate_pipeline.linking.requests.get",
            side_effect=requests.RequestException("Connection failed"),
        )

        result = fetch_undl_metadata("A/RES/80/142")

        assert result is None

    def test_fetch_http_error(self, mocker):
        """Return None on HTTP error status."""
        import requests

        mock_response = mocker.Mock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("404 Not Found")

        mocker.patch("mandate_pipeline.linking.requests.get", return_value=mock_response)

        result = fetch_undl_metadata("A/RES/80/142")

        assert result is None

    def test_fetch_timeout(self, mocker):
        """Return None on timeout."""
        import requests

        mocker.patch(
            "mandate_pipeline.linking.requests.get",
            side_effect=requests.Timeout("Request timed out"),
        )

        result = fetch_undl_metadata("A/RES/80/142")

        assert result is None


class TestLinkDocumentsWithUndl:
    """Tests for link_documents with UNDL metadata integration."""

    def test_link_via_undl_metadata(self, mocker):
        """Link resolution to proposal via UNDL metadata (Pass 0)."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.text = SAMPLE_MARC_XML
        mock_response.raise_for_status = mocker.Mock()

        mocker.patch("mandate_pipeline.linking.requests.get", return_value=mock_response)

        documents = [
            {"symbol": "A/RES/80/142", "title": "Test Resolution"},
            {"symbol": "A/C.2/80/L.35/Rev.1", "title": "Test Draft"},
        ]

        link_documents(documents, use_undl_metadata=True)

        resolution = documents[0]
        proposal = documents[1]

        assert resolution["link_method"] == "undl_metadata"
        assert resolution["link_confidence"] == 1.0
        assert resolution["base_proposal_symbol"] == "A/C.2/80/L.35/Rev.1"
        assert "A/C.2/80/L.35/Rev.1" in resolution["linked_proposal_symbols"]

        assert proposal["linked_resolution_symbol"] == "A/RES/80/142"
        assert proposal["link_method"] == "undl_metadata"

    def test_link_fallback_to_symbol_reference(self, mocker):
        """Fall back to symbol reference when UNDL has no draft."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.text = SAMPLE_MARC_XML_NO_DRAFT
        mock_response.raise_for_status = mocker.Mock()

        mocker.patch("mandate_pipeline.linking.requests.get", return_value=mock_response)

        documents = [
            {
                "symbol": "A/RES/80/166",
                "title": "Test Resolution",
                "symbol_references": ["A/80/L.99"],
            },
            {"symbol": "A/80/L.99", "title": "Test Draft"},
        ]

        link_documents(documents, use_undl_metadata=True)

        resolution = documents[0]

        # Should fall back to Pass 1 (symbol_reference)
        assert resolution["link_method"] == "symbol_reference"
        assert resolution["base_proposal_symbol"] == "A/80/L.99"

    def test_link_undl_disabled(self, mocker):
        """Skip UNDL lookup when disabled."""
        mock_get = mocker.patch("mandate_pipeline.linking.requests.get")

        documents = [
            {
                "symbol": "A/RES/80/142",
                "title": "Test Resolution",
                "symbol_references": ["A/80/L.50"],
            },
            {"symbol": "A/80/L.50", "title": "Test Draft"},
        ]

        link_documents(documents, use_undl_metadata=False)

        # Should not have called the API
        mock_get.assert_not_called()

        # Should use symbol_reference method
        resolution = documents[0]
        assert resolution["link_method"] == "symbol_reference"

    def test_link_undl_draft_not_in_local_collection(self, mocker):
        """Store base_proposal even when draft not in local collection."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.text = SAMPLE_MARC_XML
        mock_response.raise_for_status = mocker.Mock()

        mocker.patch("mandate_pipeline.linking.requests.get", return_value=mock_response)

        # Only resolution, no local copy of the draft
        documents = [
            {"symbol": "A/RES/80/142", "title": "Test Resolution"},
        ]

        link_documents(documents, use_undl_metadata=True)

        resolution = documents[0]

        # Should still record the base_proposal from UNDL
        assert resolution["base_proposal_symbol"] == "A/C.2/80/L.35/Rev.1"
        assert resolution["link_method"] == "undl_metadata"
        # But linked_proposal_symbols should be empty (not in local collection)
        assert resolution["linked_proposal_symbols"] == []

    def test_link_skip_already_linked(self, mocker):
        """Skip UNDL lookup for already-linked documents."""
        mock_get = mocker.patch("mandate_pipeline.linking.requests.get")

        documents = [
            {
                "symbol": "A/RES/80/142",
                "title": "Test Resolution",
                "linked_proposal_symbols": ["A/80/L.1"],  # Already linked
            },
        ]

        link_documents(documents, use_undl_metadata=True)

        # Should not call API for already-linked resolution
        mock_get.assert_not_called()


# =============================================================================
# UNIT TESTS: Helper Functions
# =============================================================================


class TestSymbolToFilename:
    """Test symbol_to_filename conversion."""

    def test_simple_symbol(self):
        """Convert simple A/80/L.1 to A_80_L.1."""
        assert symbol_to_filename("A/80/L.1") == "A_80_L.1"

    def test_resolution_symbol(self):
        """Convert resolution A/RES/80/1 to A_RES_80_1."""
        assert symbol_to_filename("A/RES/80/1") == "A_RES_80_1"

    def test_committee_symbol(self):
        """Convert committee A/C.1/80/L.5 to A_C.1_80_L.5."""
        assert symbol_to_filename("A/C.1/80/L.5") == "A_C.1_80_L.5"

    def test_revision_symbol(self):
        """Convert revision A/80/L.1/Rev.1 to A_80_L.1_Rev.1."""
        assert symbol_to_filename("A/80/L.1/Rev.1") == "A_80_L.1_Rev.1"

    def test_empty_symbol(self):
        """Empty string returns empty string."""
        assert symbol_to_filename("") == ""


class TestFilenameToSymbol:
    """Test filename_to_symbol conversion."""

    def test_simple_filename(self):
        """Convert A_80_L.1 to A/80/L.1."""
        assert filename_to_symbol("A_80_L.1") == "A/80/L.1"

    def test_filename_with_pdf(self):
        """Strip .pdf extension and convert."""
        assert filename_to_symbol("A_80_L.1.pdf") == "A/80/L.1"

    def test_resolution_filename(self):
        """Convert A_RES_80_1 to A/RES/80/1."""
        assert filename_to_symbol("A_RES_80_1") == "A/RES/80/1"

    def test_committee_filename(self):
        """Convert A_C.1_80_L.5 to A/C.1/80/L.5."""
        assert filename_to_symbol("A_C.1_80_L.5") == "A/C.1/80/L.5"


class TestClassifySymbol:
    """Test symbol classification."""

    def test_resolution_symbol(self):
        """Classify A/RES/80/1 as resolution."""
        assert classify_symbol("A/RES/80/1") == "resolution"

    def test_resolution_lowercase(self):
        """Classify lowercase a/res/80/1 as resolution."""
        assert classify_symbol("a/res/80/1") == "resolution"

    def test_proposal_symbol(self):
        """Classify A/80/L.1 as proposal."""
        assert classify_symbol("A/80/L.1") == "proposal"

    def test_committee_proposal(self):
        """Classify A/C.1/80/L.5 as proposal."""
        assert classify_symbol("A/C.1/80/L.5") == "proposal"

    def test_other_document(self):
        """Classify A/80/100 as other."""
        assert classify_symbol("A/80/100") == "other"

    def test_report_document(self):
        """Classify A/80/390 as other (report)."""
        assert classify_symbol("A/80/390") == "other"


class TestNormalizeSymbol:
    """Test symbol normalization."""

    def test_uppercase_conversion(self):
        """Convert to uppercase."""
        assert normalize_symbol("a/80/l.1") == "A/80/L.1"

    def test_strip_whitespace(self):
        """Strip leading/trailing whitespace."""
        assert normalize_symbol("  A/80/L.1  ") == "A/80/L.1"

    def test_already_normalized(self):
        """Already normalized symbol unchanged."""
        assert normalize_symbol("A/80/L.1") == "A/80/L.1"


class TestNormalizeTitle:
    """Test title normalization for fuzzy matching."""

    def test_lowercase_conversion(self):
        """Convert to lowercase."""
        assert "climate" in normalize_title("Climate Action")

    def test_remove_special_chars(self):
        """Remove special characters."""
        result = normalize_title("Climate: Action & Plans!")
        assert ":" not in result
        assert "&" not in result
        assert "!" not in result

    def test_strip_resolution_prefix(self):
        """Strip resolution number prefix like 80/60."""
        result = normalize_title("80/60. Climate Action")
        assert "80/60" not in result
        assert "climate" in result

    def test_normalize_whitespace(self):
        """Normalize multiple spaces."""
        result = normalize_title("Climate   Action   Plan")
        assert "  " not in result

    def test_empty_string(self):
        """Empty string returns empty string."""
        assert normalize_title("") == ""


class TestIsResolution:
    """Test resolution symbol detection."""

    def test_resolution_true(self):
        """A/RES/80/1 is a resolution."""
        assert is_resolution("A/RES/80/1") is True

    def test_proposal_false(self):
        """A/80/L.1 is not a resolution."""
        assert is_resolution("A/80/L.1") is False

    def test_other_false(self):
        """A/80/100 is not a resolution."""
        assert is_resolution("A/80/100") is False


class TestIsProposal:
    """Test proposal symbol detection."""

    def test_proposal_true(self):
        """A/80/L.1 is a proposal."""
        assert is_proposal("A/80/L.1") is True

    def test_committee_proposal_true(self):
        """A/C.1/80/L.5 is a proposal."""
        assert is_proposal("A/C.1/80/L.5") is True

    def test_resolution_false(self):
        """A/RES/80/1 is not a proposal."""
        assert is_proposal("A/RES/80/1") is False

    def test_other_false(self):
        """A/80/100 is not a proposal."""
        assert is_proposal("A/80/100") is False


class TestIsExcludedDraftSymbol:
    """Test detection of revision/addendum/corrigendum drafts."""

    def test_revision_excluded(self):
        """A/80/L.1/Rev.1 is excluded."""
        assert is_excluded_draft_symbol("A/80/L.1/Rev.1") is True

    def test_addendum_excluded(self):
        """A/80/L.1/Add.1 is excluded."""
        assert is_excluded_draft_symbol("A/80/L.1/Add.1") is True

    def test_corrigendum_excluded(self):
        """A/80/L.1/Corr.1 is excluded."""
        assert is_excluded_draft_symbol("A/80/L.1/Corr.1") is True

    def test_base_proposal_not_excluded(self):
        """A/80/L.1 is not excluded."""
        assert is_excluded_draft_symbol("A/80/L.1") is False

    def test_resolution_not_excluded(self):
        """A/RES/80/1 is not excluded."""
        assert is_excluded_draft_symbol("A/RES/80/1") is False

    def test_case_insensitive(self):
        """Case insensitive detection."""
        assert is_excluded_draft_symbol("A/80/L.1/rev.1") is True


class TestIsBaseProposalDoc:
    """Test base proposal document detection."""

    def test_base_proposal_true(self):
        """Base proposal doc returns True."""
        doc = {"symbol": "A/80/L.1", "doc_type": "proposal"}
        assert is_base_proposal_doc(doc) is True

    def test_revision_false(self):
        """Revision doc returns False."""
        doc = {"symbol": "A/80/L.1/Rev.1", "doc_type": "proposal"}
        assert is_base_proposal_doc(doc) is False

    def test_wrong_doc_type_false(self):
        """Wrong doc_type returns False."""
        doc = {"symbol": "A/80/L.1", "doc_type": "amendment"}
        assert is_base_proposal_doc(doc) is False

    def test_resolution_false(self):
        """Resolution returns False."""
        doc = {"symbol": "A/RES/80/1", "doc_type": "resolution"}
        assert is_base_proposal_doc(doc) is False

    def test_missing_symbol_false(self):
        """Missing symbol returns False."""
        doc = {"doc_type": "proposal"}
        assert is_base_proposal_doc(doc) is False


# =============================================================================
# UNIT TESTS: link_documents Function
# =============================================================================


class TestLinkDocuments:
    """Test document linking algorithm."""

    def test_link_by_symbol_reference(self):
        """Link resolution to proposal via explicit symbol reference."""
        documents = [
            {
                "symbol": "A/RES/80/1",
                "title": "Climate Action",
                "agenda_items": ["Item 68"],
                "symbol_references": ["A/80/L.1"],
            },
            {
                "symbol": "A/80/L.1",
                "title": "Climate Action",
                "agenda_items": ["Item 68"],
                "symbol_references": [],
            },
        ]

        link_documents(documents, use_undl_metadata=False)

        resolution = documents[0]
        proposal = documents[1]

        assert resolution["linked_proposal_symbols"] == ["A/80/L.1"]
        assert resolution["link_method"] == "symbol_reference"
        assert resolution["link_confidence"] == 1.0
        assert proposal["linked_resolution_symbol"] == "A/RES/80/1"
        assert proposal["link_method"] == "symbol_reference"

    def test_link_multiple_proposals(self):
        """Link resolution to multiple proposals."""
        documents = [
            {
                "symbol": "A/RES/80/1",
                "title": "Climate Action",
                "agenda_items": ["Item 68"],
                "symbol_references": ["A/80/L.1", "A/80/L.5"],
            },
            {
                "symbol": "A/80/L.1",
                "title": "Climate Action",
                "agenda_items": ["Item 68"],
                "symbol_references": [],
            },
            {
                "symbol": "A/80/L.5",
                "title": "Related Topic",
                "agenda_items": ["Item 68"],
                "symbol_references": [],
            },
        ]

        link_documents(documents, use_undl_metadata=False)

        resolution = documents[0]
        assert "A/80/L.1" in resolution["linked_proposal_symbols"]
        assert "A/80/L.5" in resolution["linked_proposal_symbols"]

    def test_link_by_fuzzy_title_match(self):
        """Link by fuzzy title matching when no symbol reference."""
        documents = [
            {
                "symbol": "A/RES/80/1",
                "title": "80/1. Strengthening humanitarian assistance",
                "agenda_items": ["Item 68"],
                "symbol_references": [],
            },
            {
                "symbol": "A/80/L.1",
                "title": "Strengthening humanitarian assistance",
                "agenda_items": ["Item 68"],
                "symbol_references": [],
            },
        ]

        link_documents(documents, use_undl_metadata=False)

        resolution = documents[0]
        proposal = documents[1]

        assert resolution["linked_proposal_symbols"] == ["A/80/L.1"]
        assert resolution["link_method"] == "title_agenda_fuzzy"
        assert resolution["link_confidence"] >= 0.85
        assert proposal["linked_resolution_symbol"] == "A/RES/80/1"

    def test_fuzzy_link_requires_agenda_overlap(self):
        """Fuzzy matching requires agenda item overlap if both have items."""
        documents = [
            {
                "symbol": "A/RES/80/1",
                "title": "Climate Action",
                "agenda_items": ["Item 68"],
                "symbol_references": [],
            },
            {
                "symbol": "A/80/L.1",
                "title": "Climate Action",
                "agenda_items": ["Item 125"],  # Different agenda item
                "symbol_references": [],
            },
        ]

        link_documents(documents, use_undl_metadata=False)

        resolution = documents[0]
        # Should not link due to agenda mismatch
        assert resolution["linked_proposal_symbols"] == []

    def test_fuzzy_link_ignores_agenda_if_missing(self):
        """Fuzzy matching works if one side has no agenda items."""
        documents = [
            {
                "symbol": "A/RES/80/1",
                "title": "Climate Action",
                "agenda_items": ["Item 68"],
                "symbol_references": [],
            },
            {
                "symbol": "A/80/L.1",
                "title": "Climate Action",
                "agenda_items": [],  # No agenda items
                "symbol_references": [],
            },
        ]

        link_documents(documents, use_undl_metadata=False)

        resolution = documents[0]
        assert resolution["linked_proposal_symbols"] == ["A/80/L.1"]

    def test_fuzzy_link_threshold(self):
        """Fuzzy match requires 85% similarity threshold."""
        documents = [
            {
                "symbol": "A/RES/80/1",
                "title": "Climate Action for Sustainable Development",
                "agenda_items": ["Item 68"],
                "symbol_references": [],
            },
            {
                "symbol": "A/80/L.1",
                "title": "Totally Different Topic Here",  # Low similarity
                "agenda_items": ["Item 68"],
                "symbol_references": [],
            },
        ]

        link_documents(documents, use_undl_metadata=False)

        resolution = documents[0]
        # Should not link due to low title similarity
        assert resolution["linked_proposal_symbols"] == []

    def test_no_link_for_proposals(self):
        """Proposals don't initiate linking (only resolutions do)."""
        documents = [
            {
                "symbol": "A/80/L.1",
                "title": "Climate Action",
                "agenda_items": ["Item 68"],
                "symbol_references": ["A/80/L.5"],
            },
            {
                "symbol": "A/80/L.5",
                "title": "Related Topic",
                "agenda_items": ["Item 68"],
                "symbol_references": [],
            },
        ]

        link_documents(documents, use_undl_metadata=False)

        # Proposals don't get linked_proposal_symbols from their references
        proposal = documents[0]
        assert proposal["linked_proposal_symbols"] == []

    def test_symbol_link_takes_precedence(self):
        """Symbol-based linking takes precedence over fuzzy matching."""
        documents = [
            {
                "symbol": "A/RES/80/1",
                "title": "Climate Action",
                "agenda_items": ["Item 68"],
                "symbol_references": ["A/80/L.5"],  # References L.5
            },
            {
                "symbol": "A/80/L.1",
                "title": "Climate Action",  # Better title match
                "agenda_items": ["Item 68"],
                "symbol_references": [],
            },
            {
                "symbol": "A/80/L.5",
                "title": "Different Title",  # Worse title match
                "agenda_items": ["Item 68"],
                "symbol_references": [],
            },
        ]

        link_documents(documents, use_undl_metadata=False)

        resolution = documents[0]
        # Should link to L.5 (symbol reference) not L.1 (title match)
        assert resolution["linked_proposal_symbols"] == ["A/80/L.5"]
        assert resolution["link_method"] == "symbol_reference"

    def test_sets_base_proposal_symbol(self):
        """Sets base_proposal_symbol on resolution."""
        documents = [
            {
                "symbol": "A/RES/80/1",
                "title": "Climate Action",
                "agenda_items": ["Item 68"],
                "symbol_references": ["A/80/L.1", "A/80/L.5"],
            },
            {
                "symbol": "A/80/L.1",
                "title": "Climate Action",
                "agenda_items": ["Item 68"],
                "symbol_references": [],
            },
            {
                "symbol": "A/80/L.5",
                "title": "Related",
                "agenda_items": ["Item 68"],
                "symbol_references": [],
            },
        ]

        link_documents(documents, use_undl_metadata=False)

        resolution = documents[0]
        # base_proposal_symbol should be first linked proposal
        assert resolution["base_proposal_symbol"] == "A/80/L.1"

    def test_default_fields_initialized(self):
        """All link-related fields are initialized."""
        documents = [
            {
                "symbol": "A/80/L.1",
                "title": "Climate Action",
                "agenda_items": ["Item 68"],
                "symbol_references": [],
            },
        ]

        link_documents(documents, use_undl_metadata=False)

        doc = documents[0]
        assert "linked_resolution_symbol" in doc
        assert "linked_proposal_symbols" in doc
        assert "link_method" in doc
        assert "link_confidence" in doc

    def test_empty_documents_list(self):
        """Empty documents list handled gracefully."""
        documents = []
        link_documents(documents, use_undl_metadata=False)  # Should not raise
        assert documents == []

    def test_proposal_already_linked_not_relinked(self):
        """Proposals already linked to a resolution are skipped in fuzzy matching."""
        documents = [
            {
                "symbol": "A/RES/80/1",
                "title": "Climate Action",
                "agenda_items": ["Item 68"],
                "symbol_references": ["A/80/L.1"],
            },
            {
                "symbol": "A/RES/80/2",
                "title": "Climate Action",  # Same title
                "agenda_items": ["Item 68"],
                "symbol_references": [],
            },
            {
                "symbol": "A/80/L.1",
                "title": "Climate Action",
                "agenda_items": ["Item 68"],
                "symbol_references": [],
            },
        ]

        link_documents(documents, use_undl_metadata=False)

        # A/80/L.1 should be linked to A/RES/80/1 (symbol ref), not A/RES/80/2
        proposal = documents[2]
        assert proposal["linked_resolution_symbol"] == "A/RES/80/1"


# =============================================================================
# UNIT TESTS: annotate_linkage Function
# =============================================================================


class TestAnnotateLinkage:
    """Test linkage annotation algorithm."""

    def test_annotate_adopted_draft(self):
        """Mark proposal as adopted when linked to resolution."""
        documents = [
            {
                "symbol": "A/RES/80/1",
                "doc_type": "resolution",
                "linked_proposal_symbols": ["A/80/L.1"],
            },
            {
                "symbol": "A/80/L.1",
                "doc_type": "proposal",
                "linked_resolution_symbol": "A/RES/80/1",
            },
        ]

        annotate_linkage(documents)

        proposal = documents[1]
        assert proposal["is_adopted_draft"] is True
        assert proposal["adopted_by"] == "A/RES/80/1"

    def test_unadopted_draft(self):
        """Proposal without linked resolution is not adopted."""
        documents = [
            {
                "symbol": "A/80/L.1",
                "doc_type": "proposal",
                "linked_resolution_symbol": None,
            },
        ]

        annotate_linkage(documents)

        proposal = documents[0]
        assert proposal["is_adopted_draft"] is False
        assert proposal["adopted_by"] is None

    def test_revision_not_marked_adopted(self):
        """Revision drafts are not marked as adopted base proposals."""
        documents = [
            {
                "symbol": "A/RES/80/1",
                "doc_type": "resolution",
                "linked_proposal_symbols": ["A/80/L.1/Rev.1"],
            },
            {
                "symbol": "A/80/L.1/Rev.1",
                "doc_type": "proposal",
                "linked_resolution_symbol": "A/RES/80/1",
            },
        ]

        annotate_linkage(documents)

        revision = documents[1]
        # Revisions are excluded from base proposal tracking
        assert revision["is_adopted_draft"] is False

    def test_linked_proposals_populated(self):
        """Resolution gets linked_proposals list."""
        documents = [
            {
                "symbol": "A/RES/80/1",
                "doc_type": "resolution",
                "linked_proposal_symbols": ["A/80/L.1", "A/80/L.5"],
            },
            {
                "symbol": "A/80/L.1",
                "doc_type": "proposal",
                "linked_resolution_symbol": "A/RES/80/1",
            },
            {
                "symbol": "A/80/L.5",
                "doc_type": "proposal",
                "linked_resolution_symbol": "A/RES/80/1",
            },
        ]

        annotate_linkage(documents)

        resolution = documents[0]
        linked = resolution["linked_proposals"]
        assert len(linked) == 2
        symbols = [lp["symbol"] for lp in linked]
        assert "A/80/L.1" in symbols
        assert "A/80/L.5" in symbols

    def test_linked_proposals_excludes_revisions(self):
        """linked_proposals excludes revision drafts."""
        documents = [
            {
                "symbol": "A/RES/80/1",
                "doc_type": "resolution",
                "linked_proposal_symbols": ["A/80/L.1", "A/80/L.1/Rev.1"],
            },
            {
                "symbol": "A/80/L.1",
                "doc_type": "proposal",
                "linked_resolution_symbol": "A/RES/80/1",
            },
            {
                "symbol": "A/80/L.1/Rev.1",
                "doc_type": "proposal",
                "linked_resolution_symbol": "A/RES/80/1",
            },
        ]

        annotate_linkage(documents)

        resolution = documents[0]
        linked = resolution["linked_proposals"]
        symbols = [lp["symbol"] for lp in linked]
        assert "A/80/L.1" in symbols
        assert "A/80/L.1/Rev.1" not in symbols

    def test_linked_proposals_html_filename(self):
        """linked_proposals includes HTML filename."""
        documents = [
            {
                "symbol": "A/RES/80/1",
                "doc_type": "resolution",
                "linked_proposal_symbols": ["A/80/L.1"],
            },
            {
                "symbol": "A/80/L.1",
                "doc_type": "proposal",
                "linked_resolution_symbol": "A/RES/80/1",
            },
        ]

        annotate_linkage(documents)

        resolution = documents[0]
        linked = resolution["linked_proposals"][0]
        assert linked["filename"] == "A_80_L.1.html"

    def test_empty_documents_list(self):
        """Empty documents list handled gracefully."""
        documents = []
        annotate_linkage(documents)  # Should not raise
        assert documents == []

    def test_default_fields_initialized(self):
        """All linkage fields are initialized."""
        documents = [
            {
                "symbol": "A/80/L.1",
                "doc_type": "proposal",
            },
        ]

        annotate_linkage(documents)

        doc = documents[0]
        assert "is_adopted_draft" in doc
        assert "adopted_by" in doc
        assert "linked_proposals" in doc


# =============================================================================
# DATA QUALITY TESTS: Real Documents
# =============================================================================

DATA_DIR = Path(__file__).parent.parent / "data" / "pdfs"


@pytest.mark.skipif(not DATA_DIR.exists(), reason="Data directory not available")
class TestDataQualityLinkage:
    """Data quality tests for linkage using real documents."""

    def test_symbol_extraction_consistency(self):
        """Symbol extraction produces consistent normalized results."""
        from mandate_pipeline.extractor import extract_text, find_symbol_references

        # Test with a few known documents
        test_files = list(DATA_DIR.glob("A_80_L.*.pdf"))[:5]
        if len(test_files) < 3:
            pytest.skip("Not enough test files")

        for pdf in test_files:
            text = extract_text(pdf)
            symbol = filename_to_symbol(pdf.stem)
            refs = find_symbol_references(text)

            # All extracted symbols should be uppercase
            for ref in refs:
                assert ref == ref.upper(), f"Symbol {ref} not normalized"

    def test_classify_symbol_real_documents(self):
        """Classification works on real document symbols."""
        # Test known document types
        proposals = ["A/80/L.1", "A/80/L.10", "A/C.1/80/L.5"]
        resolutions = ["A/RES/80/1", "A/RES/80/100"]
        others = ["A/80/390", "A/80/100"]

        for symbol in proposals:
            assert classify_symbol(symbol) == "proposal", f"{symbol} should be proposal"

        for symbol in resolutions:
            assert classify_symbol(symbol) == "resolution", f"{symbol} should be resolution"

        for symbol in others:
            assert classify_symbol(symbol) == "other", f"{symbol} should be other"

    def test_link_documents_with_real_structure(self):
        """link_documents works with realistic document structure."""
        from mandate_pipeline.extractor import extract_text, extract_title, extract_agenda_items, find_symbol_references

        test_files = list(DATA_DIR.glob("A_80_L.*.pdf"))[:10]
        if len(test_files) < 5:
            pytest.skip("Not enough test files")

        documents = []
        for pdf in test_files:
            text = extract_text(pdf)
            symbol = filename_to_symbol(pdf.stem)

            documents.append({
                "symbol": symbol,
                "doc_type": "proposal",
                "title": extract_title(text),
                "agenda_items": extract_agenda_items(text),
                "symbol_references": find_symbol_references(text),
            })

        # Should not raise
        link_documents(documents, use_undl_metadata=False)
        annotate_linkage(documents)

        # All documents should have link fields
        for doc in documents:
            assert "linked_resolution_symbol" in doc
            assert "linked_proposal_symbols" in doc
            assert "is_adopted_draft" in doc
            assert "linked_proposals" in doc

    def test_fuzzy_title_matching_quality(self):
        """Fuzzy title matching produces reasonable results."""
        # Test cases with known similar titles
        test_cases = [
            ("80/1. Climate Action", "Climate Action", True),
            ("80/1. Climate Action for Development", "Climate Action for Development", True),
            ("Climate Action", "Totally Different Topic", False),
            ("Humanitarian Assistance", "humanitarian assistance", True),
            ("Short", "Completely Different and Much Longer Title", False),
        ]

        for title1, title2, should_match in test_cases:
            norm1 = normalize_title(title1)
            norm2 = normalize_title(title2)

            from rapidfuzz import fuzz
            similarity = fuzz.ratio(norm1, norm2)

            if should_match:
                assert similarity >= 85, f"Expected match: {title1} vs {title2}"
            else:
                assert similarity < 85, f"Expected no match: {title1} vs {title2}"


# =============================================================================
# INTEGRATION TESTS: Full Pipeline
# =============================================================================


class TestLinkageIntegration:
    """Integration tests for complete linkage workflow."""

    def test_full_link_and_annotate_workflow(self):
        """Complete workflow: link_documents then annotate_linkage."""
        documents = [
            # Resolution with symbol reference
            {
                "symbol": "A/RES/80/1",
                "doc_type": "resolution",
                "title": "80/1. Climate Action",
                "agenda_items": ["Item 68"],
                "symbol_references": ["A/80/L.1"],
            },
            # Resolution without symbol reference (needs fuzzy match)
            {
                "symbol": "A/RES/80/2",
                "doc_type": "resolution",
                "title": "80/2. Humanitarian Assistance",
                "agenda_items": ["Item 70"],
                "symbol_references": [],
            },
            # Base proposal (will be linked and adopted)
            {
                "symbol": "A/80/L.1",
                "doc_type": "proposal",
                "title": "Climate Action",
                "agenda_items": ["Item 68"],
                "symbol_references": [],
            },
            # Base proposal (fuzzy match candidate)
            {
                "symbol": "A/80/L.5",
                "doc_type": "proposal",
                "title": "Humanitarian Assistance",
                "agenda_items": ["Item 70"],
                "symbol_references": [],
            },
            # Revision (should not be marked as adopted base)
            {
                "symbol": "A/80/L.1/Rev.1",
                "doc_type": "proposal",
                "title": "Climate Action",
                "agenda_items": ["Item 68"],
                "symbol_references": [],
            },
            # Unrelated proposal (should remain unlinked)
            {
                "symbol": "A/80/L.10",
                "doc_type": "proposal",
                "title": "Completely Different Topic",
                "agenda_items": ["Item 125"],
                "symbol_references": [],
            },
        ]

        # Run linking
        link_documents(documents, use_undl_metadata=False)
        annotate_linkage(documents)

        # Verify RES/80/1 linked to L.1 via symbol
        res1 = next(d for d in documents if d["symbol"] == "A/RES/80/1")
        assert res1["linked_proposal_symbols"] == ["A/80/L.1"]
        assert res1["link_method"] == "symbol_reference"

        # Verify RES/80/2 linked to L.5 via fuzzy
        res2 = next(d for d in documents if d["symbol"] == "A/RES/80/2")
        assert res2["linked_proposal_symbols"] == ["A/80/L.5"]
        assert res2["link_method"] == "title_agenda_fuzzy"

        # Verify L.1 is adopted
        l1 = next(d for d in documents if d["symbol"] == "A/80/L.1")
        assert l1["is_adopted_draft"] is True
        assert l1["adopted_by"] == "A/RES/80/1"

        # Verify L.5 is adopted
        l5 = next(d for d in documents if d["symbol"] == "A/80/L.5")
        assert l5["is_adopted_draft"] is True
        assert l5["adopted_by"] == "A/RES/80/2"

        # Verify revision is NOT marked as adopted base
        rev = next(d for d in documents if d["symbol"] == "A/80/L.1/Rev.1")
        assert rev["is_adopted_draft"] is False

        # Verify unrelated proposal is not adopted
        l10 = next(d for d in documents if d["symbol"] == "A/80/L.10")
        assert l10["is_adopted_draft"] is False
        assert l10["linked_resolution_symbol"] is None
