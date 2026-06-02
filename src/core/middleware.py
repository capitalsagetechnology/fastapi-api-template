import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

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

        # Determine if logging should be skipped (GET requests to storage/assets management API)
        skip_logging = request.method == "GET" and request.url.path.startswith(
            "/api/v1/assets"
        )

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
            # 7. Format bodies for logging (masking is done automatically by Formatter)
            req_body_str = (
                req_body.decode("utf-8", errors="ignore")
                if req_body
                else "[empty or multipart]"
            )
            res_body_str = (
                res_body.decode("utf-8", errors="ignore")
                if res_body
                else "[binary or empty]"
            )

            # Limit logged response length to avoid huge log size on massive responses
            if len(res_body_str) > 5000:
                res_body_str = res_body_str[:5000] + "... [TRUNCATED]"

            logger.info(
                f"HTTP {response.status_code} | IP: {ip_address} | {request.method} {request.url.path} | "
                f"Duration: {duration:.4f}s | "
                f"Req Body: {req_body_str} | Res Body: {res_body_str}"
            )

        return response
