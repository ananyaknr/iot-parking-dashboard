"""Bridge to the camera/parking service (vvryw/intelligence-parking-lot).

The parking service (FastAPI, default http://127.0.0.1:8000) owns cameras, Gemini
classification, PaddleOCR, bays, visits, decisions and photos. This dashboard only
forwards requests to it through its own authenticated backend, so the browser never
talks to port 8000 and the private photo bucket stays behind the parking service.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid

DEFAULT_URL = "http://127.0.0.1:8000"
JSON_LIMIT = 4 * 1024 * 1024
MEDIA_LIMIT = 16 * 1024 * 1024
READ_TIMEOUT = 4
FRAME_TIMEOUT = 9        # the service waits up to 8 s for an ESP32-CAM still
ANALYZE_TIMEOUT = 60     # Gemini primary 8 s + fallback 15 s + OCR, with margin
COMMIT_TIMEOUT = 20
CAMERAS = ("entrance", "exit")


class ParkingUnavailable(Exception):
    """The parking service could not be reached or answered with an error."""

    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


def base_url() -> str:
    url = os.environ.get("PARKING_API_URL", DEFAULT_URL).strip().rstrip("/")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.query or parsed.fragment:
        raise ParkingUnavailable("PARKING_API_URL must be an http(s) base URL")
    return url


def _detail(body: bytes, fallback: str) -> str:
    try:
        detail = json.loads(body).get("detail")
    except (ValueError, AttributeError):
        detail = None
    return detail if isinstance(detail, str) and detail else fallback


def _fetch(path, limit, accept, timeout=READ_TIMEOUT, method="GET", body=None, content_type=None):
    headers = {"Accept": accept}
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(base_url() + path, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(limit + 1)
            if len(data) > limit:
                raise ParkingUnavailable("Parking service response too large", 502)
            return data, response.headers
    except urllib.error.HTTPError as exc:
        # Keep the parking service's own explanation (e.g. "Camera unavailable", 409 conflicts).
        message = _detail(exc.read(64 * 1024), f"Parking service returned HTTP {exc.code}")
        raise ParkingUnavailable(message, exc.code if 400 <= exc.code < 600 else 502) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ParkingUnavailable("Parking service unreachable") from exc


def _json(data: bytes) -> dict:
    try:
        result = json.loads(data)
    except ValueError as exc:
        raise ParkingUnavailable("Parking service returned invalid JSON", 502) from exc
    if not isinstance(result, dict):
        raise ParkingUnavailable("Parking service returned an unexpected payload", 502)
    return result


def get_json(path: str) -> dict:
    return _json(_fetch(path, JSON_LIMIT, "application/json")[0])


def status() -> dict:
    return get_json("/parking/status")


def history(limit: int) -> dict:
    return get_json(f"/parking/history?limit={int(limit)}")


def media(media_id: str) -> bytes:
    data, headers = _fetch(f"/parking/media/{urllib.parse.quote(media_id)}", MEDIA_LIMIT, "image/jpeg")
    if not headers.get("Content-Type", "").startswith("image/jpeg"):
        raise ParkingUnavailable("Parking service returned a non-JPEG photo", 502)
    return data


def camera_frame(camera: str):
    """Fresh JPEG from the chosen ESP32-CAM, plus the service's capture time in ms."""
    if camera not in CAMERAS:
        raise ParkingUnavailable("camera must be entrance or exit", 400)
    data, headers = _fetch(f"/camera/snapshot?camera={camera}", MEDIA_LIMIT, "image/jpeg", FRAME_TIMEOUT)
    if not headers.get("Content-Type", "").startswith("image/jpeg"):
        raise ParkingUnavailable("Camera returned a non-JPEG frame", 502)
    return data, headers.get("X-Camera-Ms")


def _multipart(fields: dict, file_field: str, filename: str, file_type: str, file_bytes: bytes):
    boundary = "----parking" + uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
                  f"Content-Type: {file_type}\r\n\r\n").encode() + file_bytes + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def analyze(image: bytes, image_type: str, camera: str, plate_bbox=None, previous_observation_id=None) -> dict:
    fields = {"camera": camera}
    if plate_bbox:
        fields["plate_bbox"] = plate_bbox
    if previous_observation_id:
        fields["previous_observation_id"] = previous_observation_id
    body, content_type = _multipart(fields, "image", "capture.jpg", image_type, image)
    data, _ = _fetch("/parking/analyze", JSON_LIMIT, "application/json", ANALYZE_TIMEOUT, "POST", body, content_type)
    return _json(data)


def commit(observation_id: str, request_id: str) -> dict:
    body = json.dumps({"observation_id": observation_id, "request_id": request_id}).encode()
    data, _ = _fetch("/parking/commit", JSON_LIMIT, "application/json", COMMIT_TIMEOUT, "POST", body, "application/json")
    return _json(data)


STREAM_TIMEOUT = 12      # longest wait for the next preview frame before the stream is dropped
STREAM_CHUNK = 64 * 1024


def camera_stream(camera: str):
    """Open the parking service's MJPEG preview (multipart/x-mixed-replace, ~4 fps).

    Returns (content_type, response). The caller must close the response."""
    if camera not in CAMERAS:
        raise ParkingUnavailable("camera must be entrance or exit", 400)
    request = urllib.request.Request(base_url() + f"/camera/stream?camera={camera}", headers={"Accept": "multipart/x-mixed-replace"})
    try:
        response = urllib.request.urlopen(request, timeout=STREAM_TIMEOUT)
    except urllib.error.HTTPError as exc:
        raise ParkingUnavailable(_detail(exc.read(64 * 1024), "Camera unavailable"), exc.code if 400 <= exc.code < 600 else 502) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ParkingUnavailable("Parking service unreachable") from exc
    content_type = response.headers.get("Content-Type", "")
    if not content_type.startswith("multipart/x-mixed-replace"):
        response.close()
        raise ParkingUnavailable("Camera preview is not an MJPEG stream", 502)
    return content_type, response
