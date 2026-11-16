"""结构映射的缓存：同一份模板只让模型看一次表头。

指纹 = 表头候选行文本 + 列数 + 文件类型。
缓存后端：默认内存；配了 MAPPING_CACHE_BUCKET 就用 S3（跨进程复用）。
"""

from __future__ import annotations

import json
import os


class MemoryCache:
    """进程内缓存（测试与本地跑用）。"""

    def __init__(self) -> None:
        self._data: dict[str, dict] = {}

    def get(self, fingerprint: str) -> dict | None:
        return self._data.get(fingerprint)

    def put(self, fingerprint: str, mapping: dict) -> None:
        self._data[fingerprint] = mapping


class S3Cache:
    """S3 缓存：key = <prefix><fingerprint>.json。"""

    def __init__(self, bucket: str, prefix: str = "mapping_cache/", region: str = "ap-southeast-2") -> None:
        import boto3

        self.bucket = bucket
        self.prefix = prefix
        self.client = boto3.client("s3", region_name=region)

    def get(self, fingerprint: str) -> dict | None:
        try:
            raw = self.client.get_object(Bucket=self.bucket, Key=f"{self.prefix}{fingerprint}.json")["Body"].read()
            return json.loads(raw.decode("utf-8"))
        except Exception:  # noqa: BLE001  不存在或读失败都当作未命中
            return None

    def put(self, fingerprint: str, mapping: dict) -> None:
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=f"{self.prefix}{fingerprint}.json",
                Body=json.dumps(mapping, ensure_ascii=False).encode("utf-8"),
                ContentType="application/json",
            )
        except Exception:  # noqa: BLE001  缓存写失败不影响本次解析
            pass


_DEFAULT: MemoryCache | S3Cache | None = None


def default_cache() -> MemoryCache | S3Cache:
    """按环境变量选后端；默认内存。"""
    global _DEFAULT
    if _DEFAULT is None:
        bucket = os.environ.get("MAPPING_CACHE_BUCKET") or os.environ.get("PDF_BUCKET")
        if bucket:
            _DEFAULT = S3Cache(bucket, os.environ.get("MAPPING_CACHE_PREFIX", "mapping_cache/"))
        else:
            _DEFAULT = MemoryCache()
    return _DEFAULT


