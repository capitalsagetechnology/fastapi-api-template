import json
import logging
import time
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.worker.tasks import log_to_mongodb_task

logger = logging.getLogger("api.middleware")


class AsyncIteratorWrapper:
    """Utility class to allow re-reading the response body iterator in middleware."""

    def __init__(self, obj):
        self._it = iter(obj)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            value = next(self._it)
        except StopIteration:
            raise StopAsyncIteration
        return value


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware that logs:
    - Client IP address
    - Request method, path, and duration
    - Request body (safely cached and masked)
    - Response status code and response body (safely cached and masked)
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # 1. Start timing the request
        start_time = time.perf_counter()

        # Determine if logging should be skipped (all GET requests)
        skip_logging = request.method == "GET"

        # 2. Extract Client IP (handling reverse proxies like Cloudflare/Nginx)
        ip_address = request.headers.get("x-forwarded-for")
        if ip_address:
            # Get the first IP in the forwarded list
            ip_address = ip_address.split(",")[0].strip()
        else:
            ip_address = request.client.host if request.client else "unknown"

        # 3. Read and cache the request body for POST/PUT/PATCH requests
        req_body = b""
        if not skip_logging and request.method in ("POST", "PUT", "PATCH"):
            # Ensure we don't block if there is no body or it's a large stream
            content_length = request.headers.get("content-length")
            is_multipart = "multipart/form-data" in request.headers.get(
                "content-type", ""
            )

            # For standard JSON/text requests, we log the body
            if not is_multipart and (
                content_length is None or int(content_length) < 1_000_000
            ):
                req_body = await request.body()

                # Cache the body back in the request object so route handlers can read it
                async def receive():
                    return {
                        "type": "http.request",
                        "body": req_body,
                        "more_body": False,
                    }

                request._receive = receive

        # 4. Process the request
        try:
            response = await call_next(request)
        except Exception as exc:
            duration = time.perf_counter() - start_time
            if not skip_logging:
                logger.error(
                    f"HTTP Exception | IP: {ip_address} | {request.method} {request.url.path} | "
                    f"Duration: {duration:.4f}s | Error: {str(exc)}"
                )
            raise exc

        # 5. Calculate execution duration
        duration = time.perf_counter() - start_time

        # 6. Read and cache the response body (if it is text or json)
        res_body = b""
        content_type = response.headers.get("content-type", "")
        is_loggable_response = "json" in content_type or "text" in content_type

        if is_loggable_response and not skip_logging:
            if hasattr(response, "body"):
                res_body = response.body
            else:
                # Consume response body iterator and re-wrap it so client receives it
                response_body_chunks = [chunk async for chunk in response.body_iterator]
                res_body = b"".join(response_body_chunks)
                response.body_iterator = AsyncIteratorWrapper(response_body_chunks)

        if not skip_logging:
            # 7. Try to parse bodies as JSON (to avoid escaped string logging)
            req_body_obj = None
            if req_body:
                try:
                    req_body_obj = json.loads(req_body.decode("utf-8", errors="ignore"))
                except Exception:
                    req_body_obj = req_body.decode("utf-8", errors="ignore")
            else:
                req_body_obj = "[empty or multipart]"

            res_body_obj = None
            if res_body:
                try:
                    res_body_obj = json.loads(res_body.decode("utf-8", errors="ignore"))
                except Exception:
                    res_body_obj = res_body.decode("utf-8", errors="ignore")
            else:
                res_body_obj = "[binary or empty]"

            # Limit logged response length if it is a string
            if isinstance(res_body_obj, str) and len(res_body_obj) > 5000:
                res_body_obj = res_body_obj[:5000] + "... [TRUNCATED]"

            # Build the base log payload
            log_payload = {
                "status_code": response.status_code,
                "ip_address": ip_address,
                "method": request.method,
                "path": request.url.path,
                "duration_seconds": round(duration, 4),
                "request_body": req_body_obj,
                "response_body": res_body_obj,
            }

            # Log to console as a structured JSON string
            logger.info(json.dumps(log_payload))

            # Dispatch to MongoDB over Celery (including timestamp)
            task_payload = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **log_payload,
            }
            log_to_mongodb_task.delay(task_payload)

        return response
