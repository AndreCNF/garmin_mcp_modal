"""Local authentication script for Garmin Connect.

Uses curl_cffi with browser impersonation to bypass Garmin's anti-bot protection,
which blocks the standard `requests` library with 429 errors.

Run this once locally to generate OAuth tokens in ~/.garminconnect, then those tokens
will be mounted into the Modal container via main.py.

Usage:
    uv run python auth.py
"""

import getpass
import os

import curl_cffi.requests
import dotenv
from requests import Session as RequestsSession
from requests.models import Response

dotenv.load_dotenv()


class ImpersonatedSession(RequestsSession):
    """A requests.Session that routes all HTTP calls through curl_cffi with
    browser TLS impersonation to bypass Garmin's anti-bot 429 protection.
    Inheriting from requests.Session keeps garth's internal OAuth1 wiring intact
    (it needs .adapters, .mount, etc.), while curl_cffi handles the actual I/O.
    """

    def __init__(self, impersonate: str = "chrome120"):
        super().__init__()
        self._curl = curl_cffi.requests.Session(impersonate=impersonate)

    def send(self, request, **kwargs):  # type: ignore[override]
        kwargs.pop("proxies", None)  # curl_cffi handles proxies differently
        resp = self._curl.request(
            method=request.method,
            url=request.url,
            headers=dict(request.headers),
            data=request.body,
            **{k: v for k, v in kwargs.items() if k in ("timeout", "verify", "stream")},
        )
        # Wrap the curl_cffi response into a requests.Response so garth is happy
        r = Response()
        r.status_code = resp.status_code
        r.headers.update(resp.headers)
        r._content = resp.content
        r.encoding = resp.encoding
        r.url = resp.url
        r.request = request
        return r


def get_credentials() -> tuple[str, str]:
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")

    if not email:
        email = input("Garmin email: ").strip()
    if not password:
        password = getpass.getpass("Garmin password: ")

    return email, password


def get_mfa() -> str:
    print("\nGarmin MFA required. Check your email/phone for the code.")
    return input("Enter MFA code: ")


def make_curl_session() -> ImpersonatedSession:
    """Create a requests-compatible session that impersonates Chrome to avoid 429s."""
    return ImpersonatedSession(impersonate="chrome120")


def main():
    import garth
    from garminconnect import Garmin

    token_path = os.getenv("GARMINTOKENS", "~/.garminconnect")
    token_base64_path = os.getenv("GARMINTOKENS_BASE64", "~/.garminconnect_base64")
    is_cn = os.getenv("GARMIN_IS_CN", "false").lower() in ("true", "1", "yes")

    print("=== Garmin Connect Authentication ===")
    print(f"Tokens will be saved to: {os.path.expanduser(token_path)}\n")

    email, password = get_credentials()
    print(f"\nAuthenticating as: {email}")

    # Pass the curl_cffi session directly into garth.Client to bypass anti-bot detection.
    # garminconnect.Garmin uses garth internally; we override its garth client after init.
    curl_session = make_curl_session()
    garth_client = garth.Client(session=curl_session)

    garmin = Garmin(
        email=email,
        password=password,
        is_cn=is_cn,
        prompt_mfa=get_mfa,
    )
    # Replace the default garth client with our curl_cffi-backed one
    garmin.garth = garth_client
    garmin.login()

    # Save tokens
    garmin.garth.dump(token_path)
    expanded = os.path.expanduser(token_path)
    print(f"\n✓ OAuth tokens saved to: {expanded}")

    token_base64 = garmin.garth.dumps()
    expanded_b64 = os.path.expanduser(token_base64_path)
    with open(expanded_b64, "w") as f:
        f.write(token_base64)
    print(f"✓ Base64 tokens saved to: {expanded_b64}")

    try:
        full_name = garmin.get_full_name()
        print(f"✓ Logged in as: {full_name}")
    except Exception:
        print("✓ Authentication successful!")

    print("\nYou can now run: uv run modal deploy main.py")


if __name__ == "__main__":
    main()
