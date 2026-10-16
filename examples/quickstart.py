"""Run the exact public API examples without a key."""

from bondbyisin import Client

with Client() as client:
    result = client.search("oracle")
    print(f"Returned {result['returned']} of {result['total_matches']} matches")
    print(client.bond("68389XBU8")["bond"])
    print(f"History points: {len(client.history('68389XBU8')['points'])}")
