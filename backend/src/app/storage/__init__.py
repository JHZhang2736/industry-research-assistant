"""MinIO 对象存储客户端封装。"""

from app.storage.minio_client import get_minio, ping_minio

__all__ = ["get_minio", "ping_minio"]
