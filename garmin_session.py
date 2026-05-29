"""curl_cffi adapter for garth's HTTP session.

Garmin's edge fingerprints standard `requests` TLS handshakes and replies 429,
most reliably on the OAuth2 refresh endpoint
(connectapi.garmin.com/oauth-service/oauth/exchange/user/2.0). Routing through
curl_cffi with a Chrome impersonation profile gets past it.

Impersonation is installed at the HTTPAdapter level, not by overriding
`Session.send`, because garth's OAuth1/OAuth2 flow creates a child
`GarminOAuth1Session(parent=client.sess)` that copies `parent.adapters['https://']`
but not the parent's `Session.send`. Adapter-level interception propagates;
session-level does not.

`garth.http.Client.configure()` re-mounts a vanilla HTTPAdapter every time it
runs (called from `__init__`, `loads`, `load`). So we also patch the session's
`mount` to refuse vanilla overrides — otherwise our adapter would be clobbered
the next time tokens are loaded or the client is reconfigured.
"""

import logging
import time

import curl_cffi.requests
import garth
from requests.adapters import HTTPAdapter
from requests.models import Response

logger = logging.getLogger(__name__)


class CurlCffiAdapter(HTTPAdapter):
    """HTTPAdapter routing every send through curl_cffi with browser TLS impersonation."""

    def __init__(self, impersonate: str = "chrome146", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._curl = curl_cffi.requests.Session(impersonate=impersonate)
        self._logged_impersonation = False

    def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
        if not self._logged_impersonation:
            self._logged_impersonation = True
            logger.info(
                "CurlCffiAdapter engaged — impersonate=%r url=%s",
                self._curl.impersonate,
                request.url,
            )

        # Retry on 429 with exponential backoff, matching garth's Retry config
        # (which is configured on the adapter but never exercised because we
        # override send() and bypass super().send()).
        for attempt in range(4):  # 1 initial + 3 retries
            curl_resp = self._curl.request(
                method=request.method,
                url=request.url,
                headers=dict(request.headers),
                data=request.body,
                timeout=timeout,
                verify=verify,
                cert=cert,
                stream=stream,
            )
            if curl_resp.status_code != 429 or attempt == 3:
                break
            delay = 0.5 * (2 ** attempt)
            logger.warning(
                "CurlCffiAdapter got 429 on %s %s (attempt %d/4), "
                "sleeping %.1fs",
                request.method,
                request.url,
                attempt + 1,
                delay,
            )
            time.sleep(delay)

        r = Response()
        r.status_code = curl_resp.status_code
        r.headers.update(curl_resp.headers)
        r._content = curl_resp.content
        r.encoding = curl_resp.encoding
        r.url = curl_resp.url
        r.request = request
        return r


def install_curl_impersonation(client: garth.Client, impersonate: str = "chrome146") -> None:
    """Mount a curl_cffi adapter on garth's session and pin it.

    Pinning is via an instance-level `mount` override that refuses to install a
    non-`CurlCffiAdapter` for `https://`. Without it, the next call to
    `garth.Client.configure()` (inside `loads()`, `login()`'s tokenstore path,
    etc.) would replace our adapter with a vanilla `HTTPAdapter`.
    """
    adapter = CurlCffiAdapter(impersonate=impersonate)
    client.sess.mount("https://", adapter)

    original_mount = client.sess.mount

    def sticky_mount(prefix, new_adapter):
        if prefix == "https://" and not isinstance(new_adapter, CurlCffiAdapter):
            return
        original_mount(prefix, new_adapter)

    client.sess.mount = sticky_mount  # type: ignore[method-assign]
