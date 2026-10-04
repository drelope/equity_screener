from unittest.mock import patch

import pytest
import requests

from src.crispdm.http_retry import Throttle, request_with_backoff


def _response(status_code, headers=None):
    response = requests.Response()
    response.status_code = status_code
    response.url = "https://example.com/api"
    if headers:
        response.headers.update(headers)
    return response


def test_successful_request_is_not_retried():
    response = _response(200)
    session = requests.Session()

    with patch.object(session, "request", return_value=response) as mock_request:
        result = request_with_backoff(session, "GET", "https://example.com/api")

    assert result is response
    assert mock_request.call_count == 1


def test_429_retries_with_exponential_backoff():
    responses = [_response(429), _response(429), _response(200)]
    session = requests.Session()

    with patch.object(session, "request", side_effect=responses) as mock_request:
        with patch("src.crispdm.http_retry.time.sleep") as mock_sleep:
            result = request_with_backoff(
                session,
                "GET",
                "https://example.com/api",
                base_delay=1.0,
                jitter=False,
            )

    assert result.status_code == 200
    assert mock_request.call_count == 3
    assert mock_sleep.call_count == 2
    assert mock_sleep.call_args_list[0][0][0] == pytest.approx(1.0)
    assert mock_sleep.call_args_list[1][0][0] == pytest.approx(2.0)


def test_retry_after_header_is_followed():
    responses = [_response(429, {"Retry-After": "3"}), _response(200)]
    session = requests.Session()

    with patch.object(session, "request", side_effect=responses):
        with patch("src.crispdm.http_retry.time.sleep") as mock_sleep:
            result = request_with_backoff(
                session,
                "GET",
                "https://example.com/api",
                jitter=False,
            )

    assert result.status_code == 200
    assert mock_sleep.call_count == 1
    assert mock_sleep.call_args_list[0][0][0] == pytest.approx(3.0)


def test_retries_exhausted_returns_last_response():
    responses = [_response(429)] * 5
    session = requests.Session()

    with patch.object(session, "request", side_effect=responses):
        with patch("src.crispdm.http_retry.time.sleep"):
            result = request_with_backoff(
                session,
                "GET",
                "https://example.com/api",
                max_retries=2,
                jitter=False,
            )

    assert result.status_code == 429


def test_404_is_not_retried():
    response = _response(404)
    session = requests.Session()

    with patch.object(session, "request", return_value=response) as mock_request:
        result = request_with_backoff(session, "GET", "https://example.com/api")

    assert result.status_code == 404
    assert mock_request.call_count == 1


def test_connection_error_is_retried():
    session = requests.Session()

    with patch.object(
        session,
        "request",
        side_effect=[requests.exceptions.ConnectionError("fail"), _response(200)],
    ) as mock_request:
        with patch("src.crispdm.http_retry.time.sleep"):
            result = request_with_backoff(session, "GET", "https://example.com/api")

    assert result.status_code == 200
    assert mock_request.call_count == 2


def test_throttle_spaces_calls():
    throttle = Throttle(0.1)

    with patch("src.crispdm.http_retry.time.sleep") as mock_sleep:
        throttle.wait()
        throttle.wait()
        throttle.wait()

    assert mock_sleep.call_count == 2
    assert mock_sleep.call_args_list[0][0][0] == pytest.approx(0.1, rel=0.01)
    assert mock_sleep.call_args_list[1][0][0] == pytest.approx(0.2, rel=0.01)


def test_throttle_zero_interval_does_not_sleep():
    throttle = Throttle(0)

    with patch("src.crispdm.http_retry.time.sleep") as mock_sleep:
        throttle.wait()
        throttle.wait()

    assert mock_sleep.call_count == 0
