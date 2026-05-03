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

import dotenv

from garmin_session import install_curl_impersonation

dotenv.load_dotenv()


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


def main():
    from garminconnect import Garmin

    token_path = os.getenv("GARMINTOKENS", "~/.garminconnect")
    token_base64_path = os.getenv("GARMINTOKENS_BASE64", "~/.garminconnect_base64")
    is_cn = os.getenv("GARMIN_IS_CN", "false").lower() in ("true", "1", "yes")

    print("=== Garmin Connect Authentication ===")
    print(f"Tokens will be saved to: {os.path.expanduser(token_path)}\n")

    email, password = get_credentials()
    print(f"\nAuthenticating as: {email}")

    garmin = Garmin(
        email=email,
        password=password,
        is_cn=is_cn,
        prompt_mfa=get_mfa,
    )
    install_curl_impersonation(garmin.garth)
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
