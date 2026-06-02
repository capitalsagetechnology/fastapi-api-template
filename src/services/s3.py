import asyncio
import logging
import uuid

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from src.core.config import settings

logger = logging.getLogger("services.s3")


class S3Service:
    """
    Central storage service wrapping S3 commands.
    In development, it connects to LocalStack S3 (or MinIO) via endpoint_url.
    In production, it connects to AWS S3.
    """

    def __init__(self):
        # Configure client connection
        self.s3_client = boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION,
            endpoint_url=settings.S3_ENDPOINT_URL,
            config=Config(signature_version="s3v4"),
        )
        self.bucket_name = settings.S3_BUCKET_NAME
        self._ensure_bucket_exists()

    def _ensure_bucket_exists(self):
        """Create bucket if it does not exist, primarily for dev/LocalStack environments."""
        try:
            self.s3_client.head_bucket(Bucket=self.bucket_name)
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")
            if error_code in ("404", "NoSuchBucket"):
                logger.info(
                    f"S3 Bucket '{self.bucket_name}' not found. Creating bucket..."
                )
                try:
                    if settings.AWS_REGION == "us-east-1":
                        self.s3_client.create_bucket(Bucket=self.bucket_name)
                    else:
                        self.s3_client.create_bucket(
                            Bucket=self.bucket_name,
                            CreateBucketConfiguration={
                                "LocationConstraint": settings.AWS_REGION
                            },
                        )
                    logger.info(f"S3 Bucket '{self.bucket_name}' created successfully.")
                except Exception as ex:
                    logger.warning(
                        f"Could not create bucket '{self.bucket_name}': {ex}. Proceeding."
                    )
            else:
                logger.warning(f"Error checking bucket existence: {e}")
        except Exception as e:
            logger.warning(
                f"Failed to check S3 bucket availability (endpoint might be offline): {e}. Proceeding."
            )

    async def upload_file(
        self, file_content: bytes, filename: str, content_type: str
    ) -> str:
        """
        Uploads raw file content to S3 in a non-blocking thread pool.
        Returns:
            The public URL of the uploaded asset.
        """
        ext = filename.split(".")[-1] if "." in filename else ""
        # Create a unique filename prefix to avoid collisions
        unique_id = uuid.uuid4().hex
        key = f"assets/{unique_id}"
        if ext:
            key = f"{key}.{ext}"

        logger.info(
            f"Uploading file '{filename}' as key '{key}' to bucket '{self.bucket_name}'..."
        )

        # Run synchronous boto3 upload in standard threadpool to not block the event loop
        try:
            # Note: We try to set ACL='public-read'. If bucket settings block ACLs (Bucket Owner Enforced),
            # this might raise a ClientError. We handle the fallback without ACL.
            try:
                await asyncio.to_thread(
                    self.s3_client.put_object,
                    Bucket=self.bucket_name,
                    Key=key,
                    Body=file_content,
                    ContentType=content_type,
                    ACL="public-read",
                )
            except ClientError as e:
                # If AccessDenied because of blocked ACLs, upload without ACL and rely on bucket policies
                if "AccessDenied" in str(e) or "Access Control List" in str(e):
                    logger.warning(
                        "ACL 'public-read' is blocked by bucket policy. Retrying upload without ACL..."
                    )
                    await asyncio.to_thread(
                        self.s3_client.put_object,
                        Bucket=self.bucket_name,
                        Key=key,
                        Body=file_content,
                        ContentType=content_type,
                    )
                else:
                    raise e
        except Exception as e:
            logger.error(f"S3 file upload failed: {e}")
            raise RuntimeError(f"S3 file upload failed: {e}")

        # Formulate return URL
        if settings.S3_ENDPOINT_URL:
            # e.g., LocalStack URL style
            return f"{settings.S3_ENDPOINT_URL}/{self.bucket_name}/{key}"
        else:
            # AWS S3 standard URL style
            return f"https://{self.bucket_name}.s3.{settings.AWS_REGION}.amazonaws.com/{key}"


# Singleton instance
s3_service = S3Service()
