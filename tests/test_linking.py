# Tests for Mandate Pipeline Linking Module
# Unit tests for document linkage and UN Digital Library integration

from pathlib import Path

import pytest

from mandate_pipeline.linking import (
    symbol_to_filename,
    filename_to_symbol,
    classify_symbol,
    normalize_symbol,
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


@pytest.fixture
def mock_session(mocker):
    """Fixture to mock _get_session helper."""
    mock_s = mocker.Mock()
    mocker.patch("mandate_pipeline.linking._get_session", return_value=mock_s)
    return mock_s

class TestFetchUndlMetadata:
    """Tests for UN Digital Library API fetching."""

    def test_fetch_success(self, mocker, mock_session):
        """Fetch metadata successfully from UNDL."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.text = SAMPLE_MARC_XML
        mock_response.raise_for_status = mocker.Mock()

        mock_session.get.return_value = mock_response

        mocker.patch("mandate_pipeline.linking.time.sleep")
        mocker.patch("mandate_pipeline.linking._save_cached_metadata")

        result = fetch_undl_metadata("A/RES/80/142")

        assert result is not None
        assert result["base_proposal"] == "A/C.2/80/L.35/Rev.1"

    def test_fetch_network_error(self, mocker, mock_session):
        """Return None on network error."""
        import requests

        mock_session.get.side_effect = requests.RequestException("Connection failed")
        mocker.patch("mandate_pipeline.linking._get_cached_metadata", return_value=None)

        result = fetch_undl_metadata("A/RES/80/142")

        assert result is None

    def test_fetch_http_error(self, mocker, mock_session):
        """Return None on HTTP error status."""
        import requests

        mock_response = mocker.Mock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("404 Not Found")

        mock_session.get.return_value = mock_response
        mocker.patch("mandate_pipeline.linking._get_cached_metadata", return_value=None)

        result = fetch_undl_metadata("A/RES/80/142")

        assert result is None

    def test_fetch_timeout(self, mocker, mock_session):
        """Return None on timeout."""
        import requests

        mock_session.get.side_effect = requests.Timeout("Request timed out")
        mocker.patch("mandate_pipeline.linking._get_cached_metadata", return_value=None)

        result = fetch_undl_metadata("A/RES/80/142")

        assert result is None


class TestLinkDocumentsWithUndl:
    """Tests for link_documents with UNDL metadata integration."""

    def test_link_via_undl_metadata(self, mocker, mock_session):
        """Link resolution to proposal via UNDL metadata (Pass 0)."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.text = SAMPLE_MARC_XML
        mock_response.raise_for_status = mocker.Mock()

        mock_session.get.return_value = mock_response
        mocker.patch("mandate_pipeline.linking.time.sleep")
        mocker.patch("mandate_pipeline.linking._save_cached_metadata")

        documents = [
            {"symbol": "A/RES/80/142", "title": "Test Resolution"},
            {"symbol": "A/C.2/80/L.35/Rev.1", "title": "Test Draft"},
        ]

        link_documents(documents, use_undl_metadata=True)

        resolution = documents[0]
        proposal = documents[1]

        assert "A/C.2/80/L.35/Rev.1" in resolution["linked_proposal_symbols"]
        assert proposal["linked_resolution_symbol"] == "A/RES/80/142"

    def test_link_fallback_to_symbol_reference(self, mocker, mock_session):
        """Fall back to symbol reference when UNDL has no draft."""
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.text = SAMPLE_MARC_XML_NO_DRAFT
        mock_response.raise_for_status = mocker.Mock()

        mock_session.get.return_value = mock_response
        mocker.patch("mandate_pipeline.linking.time.sleep")
        mocker.patch("mandate_pipeline.linking._save_cached_metadata")

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
        assert "A/80/L.99" in resolution["linked_proposal_symbols"]

    def test_link_undl_disabled(self, mocker):
        """Skip UNDL lookup when disabled."""
        mock_get_session = mocker.patch("mandate_pipeline.linking._get_session")

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
        mock_get_session.assert_not_called()

        # Should still link via symbol_reference
        resolution = documents[0]
        assert "A/80/L.50" in resolution["linked_proposal_symbols"]

    def test_link_skip_already_linked(self, mocker):
        """Skip UNDL lookup for already-linked documents."""
        mock_get_session = mocker.patch("mandate_pipeline.linking._get_session")

        documents = [
            {
                "symbol": "A/RES/80/142",
                "title": "Test Resolution",
                "linked_proposal_symbols": ["A/80/L.1"],  # Already linked
            },
        ]

        link_documents(documents, use_undl_metadata=True)

        # Should not call API for already-linked resolution
        mock_get_session.assert_not_called()


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
        assert proposal["linked_resolution_symbol"] == "A/RES/80/1"

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
        """Symbol-based linking takes precedence over other matches."""
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

    def test_empty_documents_list(self):
        """Empty documents list handled gracefully."""
        documents = []
        link_documents(documents, use_undl_metadata=False)  # Should not raise
        assert documents == []

    def test_proposal_already_linked_not_relinked(self):
        """Proposals already linked to a resolution are skipped."""
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

        # All documents should have final linkage fields
        for doc in documents:
            assert "is_adopted_draft" in doc
            assert "adopted_by" in doc
            assert "linked_proposals" in doc

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
            # Resolution linked via symbol reference
            {
                "symbol": "A/RES/80/2",
                "doc_type": "resolution",
                "title": "80/2. Humanitarian Assistance",
                "agenda_items": ["Item 70"],
                "symbol_references": ["A/80/L.5"],
            },
            # Base proposal (will be linked and adopted)
            {
                "symbol": "A/80/L.1",
                "doc_type": "proposal",
                "title": "Climate Action",
                "agenda_items": ["Item 68"],
                "symbol_references": [],
            },
            # Base proposal (symbol reference candidate)
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

        # Verify RES/80/1 has linked_proposals
        res1 = next(d for d in documents if d["symbol"] == "A/RES/80/1")
        assert len(res1["linked_proposals"]) == 1
        assert res1["linked_proposals"][0]["symbol"] == "A/80/L.1"

        # Verify RES/80/2 has linked_proposals
        res2 = next(d for d in documents if d["symbol"] == "A/RES/80/2")
        assert len(res2["linked_proposals"]) == 1
        assert res2["linked_proposals"][0]["symbol"] == "A/80/L.5"

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
