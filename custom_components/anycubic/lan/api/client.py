"""LAN HTTP API client for Anycubic printers."""

from __future__ import annotations

import base64
import hashlib
import json
import random
import string
import time
import urllib.parse

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from ..const import INFO_ENDPOINT, LAN_HTTP_PORT, LAN_HTTP_SCHEME
from ..models import ControlInfo, DiscoveryInfo


class AnycubicAPI:
    """HTTP API client for LAN printer discovery and auth payload decoding."""

    def __init__(self, host: str):
        self.host = host
        self.base_url = f"{LAN_HTTP_SCHEME}://{host}:{LAN_HTTP_PORT}"
        self.discovery_data: DiscoveryInfo = {}
        self.printer_data: dict[str, str] = {}

    def discover(self):
        """Discover printer details via /info and /ctrl endpoints."""
        self.discovery_data = self._get_info()
        ctrl_data = self._get_ctrl()
        self.printer_data = self._decrypt_printer_data(ctrl_data)
        return self.printer_data

    def _get_info(self) -> DiscoveryInfo:
        url = f"{self.base_url}{INFO_ENDPOINT}"
        try:
            resp = requests.get(url, timeout=5)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            raise RuntimeError(f"Error contacting /info on printer at {self.host}: {exc}") from exc

    def _get_ctrl(self) -> ControlInfo:
        token = self.discovery_data["token"]
        ctrl_url = self.discovery_data["ctrlInfoUrl"]

        ts = int(round(time.time() * 1000))
        nonce = "".join(random.choices(string.ascii_letters + string.digits, k=6))
        did = "".join(random.choices(string.ascii_uppercase + string.digits, k=32))
        sign = self._generate_sign(token, ts, nonce)

        params = {"ts": ts, "nonce": nonce, "sign": sign, "did": did}
        try:
            resp = requests.post(ctrl_url, params=params, timeout=5)
            resp.raise_for_status()
            json_resp = resp.json()
            if json_resp.get("code") != 200:
                raise RuntimeError(f"/ctrl returned error code: {json_resp}")
            return {
                "encrypted_info": json_resp["data"]["info"],
                "local_token": json_resp["data"]["token"],
                "http_token": token,
            }
        except requests.RequestException as exc:
            raise RuntimeError(f"Error contacting /ctrl on printer at {self.host}: {exc}") from exc

    def _generate_sign(self, token, ts, nonce):
        first_md5 = hashlib.md5(token[:16].encode()).hexdigest()
        combined = f"{first_md5}{ts}{nonce}"
        second_md5 = hashlib.md5(combined.encode()).hexdigest()
        return urllib.parse.quote(urllib.parse.quote(second_md5, safe=""))

    def _decrypt_printer_data(self, data: ControlInfo):
        encrypted_data = base64.b64decode(data["encrypted_info"])
        key = data["http_token"][16:32].encode()
        iv = data["local_token"].encode().ljust(16, b"\0")

        cipher = AES.new(key, AES.MODE_CBC, iv)
        decrypted = unpad(cipher.decrypt(encrypted_data), AES.block_size)
        return json.loads(decrypted.decode("utf-8"))

    def get_model_name(self):
        return self.printer_data.get("modelName") or "Anycubic"
