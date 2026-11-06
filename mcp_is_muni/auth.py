"""
IS MU Authentication & Cookie Setup Helper
"""

import sys
import argparse
from .client import ISMuniClient, CONFIG_FILE


def main():
    parser = argparse.ArgumentParser(description="IS MU Authentication & Cookie Setup Helper")
    parser.add_argument("--cookie", "-c", type=str, help="Cookie header string or token from browser")
    parser.add_argument("--status", "-s", action="store_true", help="Check current authentication status")
    parser.add_argument("--clear", action="store_true", help="Clear saved credentials")
    args = parser.parse_args()

    client = ISMuniClient()

    if args.clear:
        if CONFIG_FILE.exists():
            CONFIG_FILE.unlink()
            print(f"[OK] Configuration cleared at {CONFIG_FILE}")
        else:
            print("[INFO] No configuration file found.")
        return

    if args.cookie:
        cookies = client.parse_cookie_input(args.cookie)
        if not cookies:
            print("[ERROR] No valid cookies found in input.")
            sys.exit(1)
        client.save_credentials(cookies)
        print(f"[OK] Saved {len(cookies)} cookies to {CONFIG_FILE}")

    status = client.check_auth_status()
    if status.get("authenticated"):
        print("\n=== IS MU Authentication Successful ===")
        print(f"Student:  {status.get('student_name')}")
        print(f"UCO:      {status.get('uco')}")
        print(f"Semester: {status.get('current_semester')}")
        print(f"URL:      {status.get('url')}")
    else:
        print("\n=== IS MU Authentication Inactive / Expired ===")
        print(status.get("message"))
        print("\nHow to obtain cookies from your browser:")
        print("1. Open https://is.muni.cz/auth/student/?lang=en in Chrome / Firefox.")
        print("2. Open Developer Tools (F12) -> Network tab.")
        print("3. Refresh the page, click the first request ('student/?lang=en').")
        print("4. In 'Request Headers', copy the value of the 'Cookie:' header.")
        print("5. Run:")
        print("   mcp-is-muni-auth --cookie \"__Host-issession=...; __Host-iscreds=...\"")


if __name__ == "__main__":
    main()
