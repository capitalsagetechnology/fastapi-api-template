import pytest

pytestmark = pytest.mark.asyncio


async def test_logging_middleware_get_exclusion_and_post_inclusion(client, db_session):
    """Verify that HTTP GET requests do not trigger logging to MongoDB, but POST requests do."""
    # Reset call counts
    client.log_mock_task.reset_mock()

    # 1. Trigger GET request (should bypass logging)
    get_res = await client.get("/health")
    assert get_res.status_code == 200
    client.log_mock_task.assert_not_called()

    # 2. Trigger POST request (should invoke Celery logging task)
    post_res = await client.post(
        "/api/v1/auth/login", json={"username": "dummy", "password": "pwd"}
    )
    # Status code will be 401 Unauthorized but the middleware should still log and dispatch to Celery
    assert post_res.status_code == 401
    client.log_mock_task.assert_called_once()

    # Check that the dispatch payload has the correct data
    called_payload = client.log_mock_task.call_args[0][0]
    assert called_payload["method"] == "POST"
    assert called_payload["path"] == "/api/v1/auth/login"
    assert called_payload["status_code"] == 401
    assert "timestamp" in called_payload
