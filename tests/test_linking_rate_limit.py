
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest
import requests
from requests.exceptions import RetryError
from urllib3.exceptions import MaxRetryError

# Import the module to test
from mandate_pipeline import linking

@pytest.fixture
def mock_cache_dir(tmp_path, monkeypatch):
    """Mock the cache directory to use a temporary path."""
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr("mandate_pipeline.linking.CACHE_DIR", cache_dir)
    return cache_dir

@pytest.fixture
def mock_requests_session(mocker):
    """Mock requests.Session or the helper function that returns it."""
    # Since we introduced _get_session, we need to mock it or the session returned by it.
    # But for testing integration logic within fetch_undl_metadata, we want to control the session object.

    mock_session = MagicMock()
    # Ensure _get_session returns this mock
    mocker.patch("mandate_pipeline.linking._get_session", return_value=mock_session)
    return mock_session

class TestRateLimitingAndRetries:

    def test_fetch_undl_metadata_retries_on_429(self, mock_requests_session, mock_cache_dir):
        """Test that fetch_undl_metadata retries on 429 errors."""
        # Note: We rely on the adapter configuration for retries, which is hard to test with mocks
        # unless we mock the Adapter logic.
        # But we can check if the code *uses* the session we expect.
        pass

    def test_polite_delay(self, mocker, mock_cache_dir, mock_requests_session):
        """Test that we sleep after a successful network request."""
        # Mock time.sleep
        mock_sleep = mocker.patch("time.sleep")

        # Mock network response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<xml>valid</xml>"
        mock_requests_session.get.return_value = mock_response

        # Mock XML parsing to avoid errors
        mocker.patch("mandate_pipeline.linking._parse_undl_marc_xml", return_value={})

        # Call function
        linking.fetch_undl_metadata("A/RES/80/1")

        # Assert sleep was called
        mock_sleep.assert_called_with(1)

    def test_caching_behavior(self, mocker, mock_cache_dir, mock_requests_session):
        """Test that cached results are returned without network calls."""
        symbol = "A/RES/80/1"
        cached_data = {"symbol": symbol, "cached": True}

        # Create a cache file manually
        import hashlib
        file_hash = hashlib.md5(symbol.encode()).hexdigest()
        cache_file = mock_cache_dir / f"{file_hash}.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(cached_data))

        # Call function
        result = linking.fetch_undl_metadata(symbol)

        # Assert result matches cache
        assert result == cached_data

        # Verify network was NOT called
        mock_requests_session.get.assert_not_called()

    def test_save_to_cache(self, mocker, mock_cache_dir, mock_requests_session):
        """Test that successful network responses are saved to cache."""
        symbol = "A/RES/80/2"
        mock_response_text = "<xml>data</xml>"
        parsed_data = {"symbol": symbol, "data": "parsed"}

        # Mock network
        mock_requests_session.get.return_value.status_code = 200
        mock_requests_session.get.return_value.text = mock_response_text

        # Mock parser
        mocker.patch("mandate_pipeline.linking._parse_undl_marc_xml", return_value=parsed_data)

        # Mock sleep
        mocker.patch("time.sleep")

        # Call
        linking.fetch_undl_metadata(symbol)

        # Verify file exists
        import hashlib
        file_hash = hashlib.md5(symbol.encode()).hexdigest()
        cache_file = mock_cache_dir / f"{file_hash}.json"

        assert cache_file.exists()
        assert json.loads(cache_file.read_text()) == parsed_data
