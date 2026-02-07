"""Test for Vercel build script."""

import sys
import json
from pathlib import Path
import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))


def test_vercel_build_script_imports():
    """Test that the build script can import all required modules."""
    from mandate_pipeline.generation import (
        generate_unified_explorer_page,
        generate_data_json,
        build_igov_decision_documents,
        ensure_document_sessions,
    )
    from mandate_pipeline.detection import load_checks
    from mandate_pipeline.igov import load_igov_decisions_all
    
    # If we get here, all imports worked
    assert True


def test_vercel_build_with_empty_data(tmp_path):
    """Test that build script handles empty data gracefully."""
    from mandate_pipeline.generation import (
        generate_unified_explorer_page,
        generate_data_json,
    )
    from mandate_pipeline.detection import load_checks
    
    # Create empty config
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    checks_file = config_dir / "checks.yaml"
    checks_file.write_text("checks: []")
    
    # Create output dir
    output_dir = tmp_path / "docs"
    output_dir.mkdir()
    
    # Generate with empty data
    checks = []
    documents = []
    
    generate_unified_explorer_page(documents, checks, output_dir)
    generate_data_json(documents, checks, output_dir)
    
    # Verify outputs exist
    assert (output_dir / "index.html").exists()
    assert (output_dir / "data.json").exists()
    
    # Verify data.json structure
    with open(output_dir / "data.json") as f:
        data = json.load(f)
        assert "documents" in data
        assert "checks" in data
        assert len(data["documents"]) == 0


def test_session_type_handling():
    """Test that session sorting handles mixed int/str types."""
    from mandate_pipeline.generation import ensure_document_sessions
    
    # Create documents with mixed session types
    documents = [
        {"symbol": "A/80/L.1", "session": 80},
        {"symbol": "A/79/L.1", "session": "79"},
        {"symbol": "A/78/L.1", "session": "78"},
        {"symbol": "A/77/L.1"},  # No session
    ]
    
    # This should not raise an error
    ensure_document_sessions(documents)
    
    # Verify all documents have sessions now
    for doc in documents:
        assert "session" in doc
        # Session should be either int or str, but set
        assert doc["session"] is not None
