"""Small live API smoke test; no financial data or credentials are printed."""

import argparse
import json
import os
from datetime import datetime, timezone

from bondbyisin import AuthenticationError, Client, __version__


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-key", action="store_true", help="Require an authenticated API test"
    )
    args = parser.parse_args()
    api_key = os.environ.get("BOND_API_KEY") or os.environ.get("BONDBYISIN_API_KEY")
    if args.require_key and not api_key:
        parser.error("Set BOND_API_KEY to an active API subscription key; no key was supplied")

    checks = []
    with Client(api_key="", max_retries=1) as client:
        result = client.search("oracle")
        assert isinstance(result["results"], list) and result["returned"] == len(result["results"])
        assert "next_page" in result
        checks.append("public_search")
        bond = client.bond("68389XBU8")
        assert bond["bond"]["id"] == "68389XBU8"
        checks.append("public_bond")
        history = client.history("68389XBU8")
        assert history["points"] and all("date" in p for p in history["points"])
        checks.append("public_history")
        curve = client.sovereign_curve("India")
        assert curve["country"] == "India" and isinstance(curve["curve"], list)
        checks.append("public_government_curve")
        swaps = client.swap_curves("USD")
        assert swaps and "error" not in swaps
        checks.append("public_swap_curve")
        try:
            client.search("apple", limit=1)
        except AuthenticationError:
            checks.append("anonymous_non_example_rejected")
        else:
            raise AssertionError(
                "A non-example query unexpectedly bypassed the API subscription requirement"
            )
    if api_key:
        with Client(api_key=api_key, max_retries=1) as client:
            results = client.search("apple", limit=1)
            assert isinstance(results["results"], list) and results["results"]
            checks.append("authenticated_search")
            rows = list(client.iter_search("oracle", limit=1, max_pages=2))
            assert len(rows) == 2 and rows[0]["id"] != rows[1]["id"]
            checks.append("authenticated_pagination")
            identifier = rows[0]["id"]
            assert client.bond(identifier)["bond"]["id"] == identifier
            checks.append("authenticated_bond")
    print(
        json.dumps(
            {
                "package": "bondbyisin",
                "version": __version__,
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "passed": checks,
                "authenticated": "passed" if api_key else "not run: API key unavailable",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
