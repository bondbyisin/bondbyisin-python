"""Set BOND_API_KEY before running. All requests are read-only."""

import os

from bondbyisin import Client

with Client(api_key=os.environ["BOND_API_KEY"]) as client:
    for bond in client.iter_search("oracle", limit=100, max_pages=2):
        print(bond["id"], bond["name"])
    print(client.zspread("68389XBU8"))
    print(client.swap_zspread("68389XBU8"))
    print(client.swap_curves("USD"))
