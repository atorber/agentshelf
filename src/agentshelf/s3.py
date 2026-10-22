from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit
from xml.etree import ElementTree

import httpx

from agentshelf.errors import LibraryError

EMPTY_HASH = hashlib.sha256(b"").hexdigest()


class S3Client:
    def __init__(
        self,
        *,
        endpoint: str,
        region: str,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
        path_style: bool,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.region = region
        self.bucket = bucket
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.path_style = path_style
        self._transport = transport

    def put_file(self, key: str, path: Path, *, content_type: str = "application/zip") -> None:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        with path.open("rb") as handle:
            self._call("PUT", key, body=handle, payload_hash=digest.hexdigest(), content_type=content_type)

    def delete(self, key: str) -> None:
        self._call("DELETE", key)

    def download(self, key: str, dest: Path) -> None:
        with self._session() as client:
            response = self._send(client, "GET", key, stream=True)
            try:
                self._raise_for_status(response)
                with dest.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)
            except Exception:
                dest.unlink(missing_ok=True)
                raise
            finally:
                response.close()

    def list_objects(self, prefix: str) -> list[dict]:
        items: list[dict] = []
        token = ""
        while True:
            query = {"list-type": "2", "prefix": prefix, "max-keys": "200"}
            if token:
                query["continuation-token"] = token
            root = self._call("GET", "", query=query, xml=True)
            for node in _children(root, "Contents"):
                key = _text(node, "Key")
                if not key.startswith(prefix):
                    continue
                name = key[len(prefix) :]
                if not name or "/" in name:
                    continue
                items.append(
                    {
                        "name": name,
                        "size_bytes": int(_text(node, "Size") or "0"),
                        "created_at": _text(node, "LastModified"),
                    }
                )
            if _text(root, "IsTruncated").lower() != "true" or len(items) >= 200:
                break
            token = _text(root, "NextContinuationToken")
            if not token:
                break
        return items[:200]

    def list_tree(self, prefix: str) -> list[dict]:
        items: list[dict] = []
        token = ""
        while len(items) < 100_000:
            query = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
            if token:
                query["continuation-token"] = token
            root = self._call("GET", "", query=query, xml=True)
            for node in _children(root, "Contents"):
                key = _text(node, "Key")
                if not key.startswith(prefix):
                    continue
                name = key[len(prefix) :]
                if not name or name.endswith("/"):
                    continue
                items.append(
                    {
                        "name": name,
                        "size_bytes": int(_text(node, "Size") or "0"),
                        "etag": _text(node, "ETag").strip().strip('"').lower(),
                    }
                )
            if _text(root, "IsTruncated").lower() != "true":
                return items
            token = _text(root, "NextContinuationToken")
            if not token:
                return items
        raise LibraryError(400, "云端目录里的文件过多")

    def _call(self, method: str, key: str, *, body=None, payload_hash: str = EMPTY_HASH, query: dict | None = None, content_type: str = "", xml: bool = False):
        with self._session() as client:
            response = self._send(client, method, key, body=body, payload_hash=payload_hash, query=query, content_type=content_type)
            try:
                self._raise_for_status(response)
                if xml:
                    return _xml(response)
                response.read()
                return None
            finally:
                response.close()

    def _session(self) -> httpx.Client:
        return httpx.Client(transport=self._transport, timeout=httpx.Timeout(30.0, read=300.0), follow_redirects=False)

    def _send(self, client: httpx.Client, method: str, key: str, *, body=None, payload_hash: str = EMPTY_HASH, query: dict | None = None, content_type: str = "", stream: bool = False) -> httpx.Response:
        url, canonical_uri, host = self._target(key)
        amz_date = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        headers = {
            "host": host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        if content_type:
            headers["content-type"] = content_type
        headers["authorization"] = _authorization(
            method,
            canonical_uri,
            query or {},
            {name: value for name, value in headers.items() if name != "authorization"},
            payload_hash,
            self.access_key_id,
            self.secret_access_key,
            self.region,
            amz_date,
        )
        if query:
            url = f"{url}?{_canonical_query(query)}"
        try:
            return client.send(client.build_request(method, url, headers=headers, content=body), stream=stream)
        except httpx.TimeoutException as exc:
            raise LibraryError(502, "S3 响应超时") from exc
        except httpx.HTTPError as exc:
            raise LibraryError(502, "无法连接 S3") from exc

    def _target(self, key: str) -> tuple[str, str, str]:
        parts = urlsplit(self.endpoint)
        encoded = "/".join(quote(part, safe="-_.~") for part in key.split("/") if part)
        if self.path_style:
            canonical = f"/{quote(self.bucket, safe='-_.~')}" + (f"/{encoded}" if encoded else "")
            host = parts.netloc
        else:
            canonical = f"/{encoded}" if encoded else "/"
            host = f"{self.bucket}.{parts.netloc}"
        return urlunsplit((parts.scheme, host, canonical, "", "")), canonical, host

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        raise LibraryError(502, _error_message(response))


def _authorization(method, canonical_uri, query, headers, payload_hash, access_key, secret, region, amz_date) -> str:
    signed_names = sorted(headers)
    canonical_headers = "".join(f"{name}:{_header_value(headers[name])}\n" for name in signed_names)
    signed = ";".join(signed_names)
    canonical = "\n".join([method, canonical_uri, _canonical_query(query), canonical_headers, signed, payload_hash])
    scope = f"{amz_date[:8]}/{region}/s3/aws4_request"
    request_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, request_hash])
    signature = hmac.new(_signing_key(secret, amz_date[:8], region), to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, SignedHeaders={signed}, Signature={signature}"


def _signing_key(secret: str, date: str, region: str) -> bytes:
    key = hmac.new(f"AWS4{secret}".encode("utf-8"), date.encode("utf-8"), hashlib.sha256).digest()
    key = hmac.new(key, region.encode("utf-8"), hashlib.sha256).digest()
    key = hmac.new(key, b"s3", hashlib.sha256).digest()
    return hmac.new(key, b"aws4_request", hashlib.sha256).digest()


def _canonical_query(query: dict[str, str]) -> str:
    pairs = sorted((quote(key, safe="-_.~"), quote(value, safe="-_.~")) for key, value in query.items())
    return "&".join(f"{key}={value}" for key, value in pairs)


def _header_value(value: str) -> str:
    return " ".join(value.strip().split())


def _xml(response: httpx.Response) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(response.read())
    except ElementTree.ParseError as exc:
        raise LibraryError(502, "S3 返回了无法识别的内容") from exc


def _children(node: ElementTree.Element, name: str) -> list[ElementTree.Element]:
    return [child for child in list(node) if _local(child.tag) == name]


def _text(node: ElementTree.Element, name: str) -> str:
    for child in _children(node, name):
        return child.text or ""
    return ""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _error_message(response: httpx.Response) -> str:
    code = ""
    try:
        code = _text(ElementTree.fromstring(response.read()), "Code")
    except ElementTree.ParseError:
        code = ""
    messages = {
        "AccessDenied": "访问被拒绝，请检查密钥、Bucket 和目录权限",
        "InvalidAccessKeyId": "Access Key 无效",
        "SignatureDoesNotMatch": "密钥校验失败，请检查 Secret Key、区域和地址风格",
        "NoSuchBucket": "找不到这个 Bucket",
        "PermanentRedirect": "区域或访问地址不匹配",
        "AuthorizationHeaderMalformed": "请求签名无效，请检查区域和访问地址",
    }
    if code in messages:
        return messages[code]
    if response.status_code == 403:
        return "访问被拒绝，请检查密钥、Bucket 和目录权限"
    return f"S3 返回 {response.status_code}"


def aws_example_signature() -> str:
    """AWS 文档中的 GET Object 示例，用来核对签名实现。"""
    headers = {
        "host": "examplebucket.s3.amazonaws.com",
        "range": "bytes=0-9",
        "x-amz-content-sha256": EMPTY_HASH,
        "x-amz-date": "20130524T000000Z",
    }
    return _authorization(
        "GET",
        "/test.txt",
        {},
        headers,
        EMPTY_HASH,
        "AKIAIOSFODNN7EXAMPLE",
        "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "us-east-1",
        "20130524T000000Z",
    )
