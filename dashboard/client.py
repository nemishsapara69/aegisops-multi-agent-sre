import os

import httpx
from dotenv import load_dotenv

load_dotenv()


def base_url():
    return os.environ.get("AEGIS_URL", "http://127.0.0.1:8000")


def users():
    """Reads the demo users from AEGIS_API_KEYS in .env (key:name:role:permission)."""
    out = []
    for part in os.environ.get("AEGIS_API_KEYS", "").split(","):
        bits = [b.strip() for b in part.strip().split(":")]
        if len(bits) == 4 and all(bits):
            out.append({"key": bits[0], "name": bits[1], "role": bits[2], "perm": bits[3]})
    return out


def call(method, path, key=None, json=None, timeout=30):
    """Returns (status_code, data). Status 0 means the API could not be reached."""
    headers = {"X-API-Key": key} if key else {}
    try:
        response = httpx.request(method, base_url() + path, headers=headers, json=json, timeout=timeout)
    except httpx.HTTPError as exc:
        return 0, {"detail": "Cannot reach the API at " + base_url() + " (" + type(exc).__name__
                             + "). Is the server running?"}
    try:
        data = response.json()
    except ValueError:
        data = {"detail": response.text[:200]}
    return response.status_code, data