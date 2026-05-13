from __future__ import annotations

from typing import Any, overload


import aiohttp
import time
import asyncio
import time

from ...const import (
    ACCESS_TOKEN_LOGIN_RETRIES,
    ACCESS_TOKEN_LOGIN_RETRY_INTERVAL,
    API_ENDPOINT,
    AUTH_DOMAIN,
    BASE_DOMAIN,
    DEFAULT_USER_AGENT,
    MAX_API_FETCH_TIME_WARN,
    PUBLIC_API_ENDPOINT,
    WARN_INTERVAL_API_DURATION,
)
from .. import (
    ErrorsAPIParsing,
    ErrorsAuth,
    ErrorsAuthTokenExpired,
)
from .exceptions import (
    AnycubicAPIParsingError,
    AnycubicAuthError,
    AnycubicAuthTokensExpired,
)
from .auth import AnycubicAuthentication, AnycubicAuthMode
from .http import HTTP_METHODS, AnycubicAPIEndpoint



class AnycubicAPIBase:
    """
    Main API class for Anycubic Cloud.
    Handles authentication and API requests.
    """

    async def get_printers(self) -> list[dict[str, Any]]:
        """
        Fetch the list of printers for the authenticated user.
        Returns a list of printer dicts (raw API response).
        """
        logger = self._get_logger()
        # Ensure we have valid user tokens (may need to exchange access token)
        try:
            tokens_ok = await self.check_api_tokens()
        except Exception as e:
            logger.debug("[Anycubic] get_printers: auth token check failed: %s", e)
            raise
        if not tokens_ok:
            logger.debug("[Anycubic] get_printers: authentication required or tokens expired")
            raise AnycubicAuthError(ErrorsAuth.login_required)

        resp = await self._fetch_api_resp(endpoint=API_ENDPOINT.printer_get_printers)
        logger.debug("[Anycubic] get_printers: raw response=%s", resp)
        if not resp or 'data' not in resp or not isinstance(resp['data'], list):
            # Provide more context in the error to aid debugging
            logger.debug("[Anycubic] get_printers: unexpected response format: %s", resp)
            raise AnycubicAPIParsingError("Failed to fetch printers or invalid response format.")
        return resp['data']


    async def login_with_email_password(self, email: str, password: str) -> None:
        """
        Login with email and password via the Anycubic Cloud API.
        Sets the access_token and user info for further API/MQTT use.
        """
        logger = self._get_logger()
        payload = {
            "email": email,
            "password": password,
            "device_type": "pcf",
        }
        headers = {
            "Content-Type": "application/json",
            "Xx-Device-Type": "pcf",
            "Xx-Version": "1.3.9.4",
            "Xx-Platform": "pc",
            "User-Agent": "AnycubicSlicer/1.3.9.4",
        }
        url = "https://cloud.anycubic.com/v3/public/login"
        async with self._session.post(url, json=payload, headers=headers) as resp:
            data = await resp.json()
        logger.debug("[Anycubic] Email login: sent payload=%s", payload)
        logger.debug("[Anycubic] Email login: server response=%s", data)
        if not data or data.get("code") != 1 or not data.get("data"):
            msg = data.get("msg") if data else "No response"
            logger.error("[Anycubic] Email login FAILED: %s", msg)
            raise AnycubicAuthError(f"Failed to login with email: {msg}")
        token = data["data"].get("token")
        user = data["data"].get("user")
        if not token or not user:
            logger.error("[Anycubic] Email login: missing token or user info!")
            raise AnycubicAuthError("Login succeeded but missing token/user info")
        # Zet authenticatie voor verdere API calls
        self.set_authentication(auth_token=token, auth_mode=None, device_id=None)
        self.anycubic_auth.set_api_user_email(user.get("user_email"))
        self.anycubic_auth.set_api_user_id(user.get("id"))
        logger.debug("[Anycubic] Email login: success, user=%s", user)
    __slots__ = (
        "_base_url",
        "_public_api_root",
        "_session",
        "_sessionjar",
        "_debug_logger",
        "_tokens_changed",
        "_log_api_call_info",
        "_last_warn_api_duration",
        "_anycubic_auth",
    )

    def __init__(
        self,
        session: aiohttp.ClientSession,
        cookie_jar: aiohttp.CookieJar,
        debug_logger: Any = None,
        auth_token: str | None = None,
        auth_mode: AnycubicAuthMode | None = None,
        device_id: str | None = None,
    ) -> None:
        # API
        self._base_url: str = f"https://{BASE_DOMAIN}/"
        self._public_api_root: str = f"{self.base_url}{PUBLIC_API_ENDPOINT}"
        # Internal
        self._session: aiohttp.ClientSession = session
        self._sessionjar: aiohttp.CookieJar = cookie_jar
        self._debug_logger: Any = debug_logger
        self._tokens_changed: bool = False
        self._log_api_call_info: bool = False
        self._last_warn_api_duration: int | None = None
        self._anycubic_auth: AnycubicAuthentication | None = None

        if auth_token:
            self.set_authentication(
                auth_token=auth_token,
                auth_mode=auth_mode,
                device_id=device_id,
            )

    @property
    def base_url(self) -> str:
        return self._base_url

    def set_log_api_call_info(
        self,
        val: bool,
    ) -> None:
        self._log_api_call_info = bool(val)

    @property
    def anycubic_auth(self) -> AnycubicAuthentication:
        if self._anycubic_auth is None:
            raise AnycubicAuthError(ErrorsAuth.missing_auth)
        return self._anycubic_auth

    @property
    def tokens_changed(self) -> bool:
        return self._tokens_changed

    def _log_to_debug(self, msg: str) -> None:
        if self._debug_logger:
            self._debug_logger.debug(msg)

    def _log_to_warn(self, msg: str) -> None:
        if self._debug_logger:
            self._debug_logger.warning(msg)

    def _log_to_error(self, msg: str) -> None:
        if self._debug_logger:
            self._debug_logger.error(msg)

    #
    #
    # API Functions
    # ------------------------------------------

    def _web_headers(self, with_origin: str | None = AUTH_DOMAIN) -> dict[str, Any]:
        header_dict = {}
        if self.anycubic_auth.requires_user_agent:
            header_dict['User-Agent'] = DEFAULT_USER_AGENT

            if with_origin:
                header_dict['Origin'] = f'https://{with_origin}'

        return header_dict

    def _build_api_url(self, endpoint: AnycubicAPIEndpoint) -> str:
        return f"{self._public_api_root}{endpoint.endpoint}"

    @overload
    async def _fetch_ext_resp(
        self,
        method: HTTP_METHODS,
        base_url: str,
        query: dict[str, Any] | None = None,
        params: dict[str, Any] = {},
        extra_headers: dict[str, Any] = {},
        with_origin: str | None = AUTH_DOMAIN,
        put_data: bytes | None = None,
    ) -> dict[Any, Any]: ...

    @overload
    async def _fetch_ext_resp(
        self,
        method: HTTP_METHODS,
        base_url: str,
        query: dict[str, Any] | None = None,
        params: dict[str, Any] = {},
        extra_headers: dict[str, Any] = {},
        with_origin: str | None = AUTH_DOMAIN,
        put_data: bytes | None = None,
        is_json: bool = True,
        return_url: bool = False,
    ) -> dict[Any, Any] | str: ...

    async def _fetch_ext_resp(
        self,
        method: HTTP_METHODS,
        base_url: str,
        query: dict[str, Any] | None = None,
        params: dict[str, Any] | list[Any] | str | None = {},
        extra_headers: dict[str, Any] = {},
        with_origin: str | None = AUTH_DOMAIN,
        put_data: bytes | None = None,
        is_json: bool = True,
        return_url: bool = False,
    ) -> dict[Any, Any] | str:
        import json
        url = base_url
        time_start: float = time.time()
        headers = {**self._web_headers(with_origin=with_origin), **extra_headers}
        # Defensive: ensure headers contain only string keys (aiohttp requires str keys)
        if not isinstance(headers, dict):
            self._log_to_error(f"Request headers not a dict: {type(headers)}")
            headers = dict(headers or {})
        # Remove any keys that are not strings to avoid aiohttp serialization errors
        invalid_keys = [k for k in headers.keys() if not isinstance(k, str)]
        if invalid_keys:
            self._log_to_warn(f"Dropping invalid header keys: {invalid_keys}")
            headers = {k: v for k, v in headers.items() if isinstance(k, str)}
        # Final fallback: coerce all header keys to strings to be safe.
        try:
            headers = {str(k): v for k, v in headers.items()}
        except Exception:
            # If coercion fails, ensure headers is at least a dict with string keys
            headers = {"": ""}

        # Special handling for /v3/public/loginWithAccessToken: send as form data
        is_access_token_login = "/v3/public/loginWithAccessToken" in url
        if method == HTTP_METHODS.POST:
            if is_access_token_login:
                # Send as form data, let aiohttp set Content-Type
                # Remove Content-Type if present
                headers.pop("Content-Type", None)
                data = params if params is not None else {}
                h_coro = self._session.post(url, params=query, data=data, headers=headers)
            else:
                if params is not None and (isinstance(params, dict) or isinstance(params, list)):
                    data = json.dumps(params)
                elif params is not None:
                    data = str(params)
                else:
                    data = None
                h_coro = self._session.post(url, params=query, data=data, headers=headers)
        elif method == HTTP_METHODS.PUT:
            h_coro = self._session.put(url, params=query, data=put_data, headers=headers)
        else:
            h_coro = self._session.get(url, params=query, headers=headers)

        response_url = None

        try:
            async with h_coro as resp:
                if is_json:
                    resp_data: dict[str, Any] | str = await resp.json()
                else:
                    resp_data = await resp.text()

                response_url = resp.url
        except Exception:
            raise AnycubicAPIParsingError(ErrorsAPIParsing.api_error_server_maintenance)

        time_end: float = time.time()
        time_diff: float = time_end - time_start
        over_limit: bool = int(time_diff) > MAX_API_FETCH_TIME_WARN
        if (
            over_limit
            and (
                not self._last_warn_api_duration
                or time_end > self._last_warn_api_duration + WARN_INTERVAL_API_DURATION
            )
        ):
            self._log_to_warn(
                f"Responses from server are taking over {MAX_API_FETCH_TIME_WARN}s (Took {int(time_diff)}s)"
            )
        if self._log_api_call_info:
            self._log_to_debug(
                f"Finished fetching {url} in {time_diff:.2f}s."
            )

        if return_url:
            return str(response_url)
        return resp_data

    async def _fetch_aws_put_resp(self, final_url: str, put_data: bytes) -> dict[Any, Any] | str:
        resp = await self._fetch_ext_resp(
            method=HTTP_METHODS.PUT,
            base_url=final_url,
            is_json=False,
            put_data=put_data,
        )

        if isinstance(resp, str) and len(resp) > 0:
            raise AnycubicAPIParsingError(ErrorsAPIParsing.api_error_aws.format(resp))

        return resp

    async def _fetch_api_resp(
        self,
        endpoint: AnycubicAPIEndpoint,
        query: dict[str, Any] | None = None,
        params: dict[str, Any] = {},
        extra_headers: dict[str, Any] = {},
        with_origin: str | None = AUTH_DOMAIN,
        with_token: bool = True,
    ) -> dict[Any, Any]:
        resp = await self._fetch_ext_resp(
            method=endpoint.method,
            base_url=self._build_api_url(endpoint),
            query=query,
            params=params,
            extra_headers=self.anycubic_auth.get_auth_headers(
                with_token=with_token
            ),
            with_origin=with_origin,
        )
        return resp

    #
    #
    # Login Functions
    # ------------------------------------------

    def set_authentication(
        self,
        auth_token: str | None,
        auth_mode: AnycubicAuthMode | int | None = None,
        device_id: str | None = None,
        auth_access_token: str | None = None,
        auto_pick_token: bool = True,
    ) -> None:
        if not auth_token and not auth_access_token:
            raise AnycubicAuthError(ErrorsAuth.set_auth_missing_token)

        if isinstance(auth_mode, int):
            auth_mode = AnycubicAuthMode(auth_mode)

        if (
            auto_pick_token and (
                not auth_access_token
                and auth_mode == AnycubicAuthMode.SLICER
            )
        ):
            auth_access_token = f"{auth_token}"
            auth_token = None

        # Restore: If an access token is provided but no explicit auth_mode,
        # default to SLICER so the public API headers (Xx-*) match
        # the Slicer Next behaviour expected by the server.
        if auth_access_token and auth_mode is None:
            auth_mode = AnycubicAuthMode.SLICER

        # Heuristic: if caller passed only a token (likely the Slicer
        # access token) and didn't set auth_mode, treat that token as
        # an access token for SLICER. This mirrors de UI behaviour
        # where users paste the Slicer access token into the field.
        if auth_mode is None and auth_token and isinstance(auth_token, str) and '.' in auth_token:
            auth_mode = AnycubicAuthMode.SLICER
            if auto_pick_token and not auth_access_token:
                auth_access_token = f"{auth_token}"
                auth_token = None

        if (
            auto_pick_token and (
                not auth_access_token
                and auth_mode == AnycubicAuthMode.SLICER
            )
        ):
            auth_access_token = f"{auth_token}"
            auth_token = None

        self._anycubic_auth = AnycubicAuthentication(
            auth_token=auth_token,
            auth_mode=auth_mode,
            device_id=device_id,
            auth_access_token=auth_access_token,
        )

    def _get_logger(self):
        # Always return a logger, even if self._logger is missing
        import logging
        return getattr(self, '_logger', logging.getLogger(__name__))

    @staticmethod
    def _is_rate_limited_message(message: Any) -> bool:
        """Return True for known Anycubic throttling messages."""
        msg = str(message or "")
        msg_lower = msg.lower()
        return (
            "too frequent" in msg_lower
            or "too many requests" in msg_lower
            or "request too frequent" in msg_lower
            or "请求过于频繁" in msg
        )

    def get_auth_config_dict(self) -> dict[str, Any]:
        self._tokens_changed = False

        return self.anycubic_auth.get_auth_config_dict()

    def load_auth_config_from_dict(
        self,
        data: dict[str, Any],
        minimal: bool = False,
    ) -> None:
        self.anycubic_auth.load_auth_config_from_dict(
            data,
            minimal=minimal,
        )
        self._log_to_debug("Loaded auth tokens from dict.")

    async def _get_user_token_with_access_token(self) -> None:
        params = self.anycubic_auth.auth_access_token_payload
        logger = self._get_logger()
        logger.debug("[Anycubic] Access-token login: sending payload=%s", params)
        # Force correct POST as form-data, never set Content-Type
        url = self._build_api_url(API_ENDPOINT.auth_sig_token)
        # Build headers using computed auth headers (Xx-*) plus any web headers
        try:
            auth_headers = self.anycubic_auth.get_auth_headers(with_token=False)
        except Exception:
            auth_headers = {}
        web_headers = self._web_headers()
        headers = {**web_headers, **auth_headers}
        # Remove Content-Type so aiohttp will set multipart/form-data correctly
        headers.pop("Content-Type", None)
        # Ensure header keys are strings
        try:
            headers = {str(k): v for k, v in headers.items()}
        except Exception:
            headers = {"": ""}
        async with self._session.post(url, data=params, headers=headers) as resp:
            try:
                data = await resp.json()
            except Exception:
                data = await resp.text()
        logger.debug("[Anycubic] Access-token login: server response=%s", data)
        if not data or not data.get('data'):
            server_message = data.get('msg') if isinstance(data, dict) else str(data)
            if self._is_rate_limited_message(server_message):
                error_message = ErrorsAPIParsing.api_error_rate_limited
                logger.warning("[Anycubic] Access-token login throttled by server: %s", server_message)
                self._log_to_debug(error_message)
                raise AnycubicAPIParsingError(error_message)

            error_message = ErrorsAuth.access_token_login_failed.format(server_message)
            logger.error("[Anycubic] Access-token login FAILED: %s", error_message)
            self._log_to_debug(error_message)
            raise AnycubicAuthError(error_message)
        self.anycubic_auth.set_auth_token(
            data['data']['token']
        )
        # Set user info (email, id) for MQTT login
        if 'user' in data['data']:
            user = data['data']['user']
            logger.debug("[Anycubic] Access-token login: user info from server: %s", user)
            if 'user_email' in user:
                self.anycubic_auth.set_api_user_email(user['user_email'])
            if 'id' in user:
                self.anycubic_auth.set_api_user_id(user['id'])
        else:
            logger.debug("[Anycubic] Access-token login: NO user info in server response!")
        self._log_to_debug("Logged in and retrieved user token with access_token.")

    async def _get_user_token_with_access_token_with_retry(self) -> None:
        retries = ACCESS_TOKEN_LOGIN_RETRIES
        for x in range(retries):
            try:
                await self._get_user_token_with_access_token()
                return
            except (AnycubicAuthError, AnycubicAPIParsingError):
                if x < retries - 1:
                    await asyncio.sleep(ACCESS_TOKEN_LOGIN_RETRY_INTERVAL * (x + 1))
                else:
                    raise

    async def _check_can_access_api(
        self,
    ) -> bool:
        if self.anycubic_auth.requires_access_token:
            try:
                await self._get_user_token_with_access_token_with_retry()
            except AnycubicAuthError:
                return False
        try:
            await self.get_user_info()
            return True
        except AnycubicAuthTokensExpired:
            self._log_to_debug("Tokens expired.")
            return False

    async def check_api_tokens(self) -> bool:
        if not await self._check_can_access_api():
            if self.anycubic_auth.clear_cached_access_user_token():
                self._tokens_changed = True
                self._log_to_debug("Cleared cached user token.")
                return await self._check_can_access_api()
            return False

        return True

    async def get_user_info(
        self,
        raw_data: bool = False,
    ) -> dict[str, Any]:
        resp = await self._fetch_api_resp(endpoint=API_ENDPOINT.user_info)
        if raw_data:
            return resp

        data: dict[str, Any] | None = resp['data']
        if data is None:
            raise AnycubicAuthTokensExpired(ErrorsAuthTokenExpired.invalid_credentials)
        if resp and resp.get('msg') == 'request error':
            raise AnycubicAPIParsingError(ErrorsAPIParsing.api_error_user_server_maintenance)

        self.anycubic_auth.set_api_user_id(data['id'])
        self.anycubic_auth.set_api_user_email(data['user_email'])

        return data
