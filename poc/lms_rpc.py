"""POC-only JSON-RPC client for loopback-bound test LMS ports."""
import argparse
import json
from urllib.request import Request, urlopen

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("port", type=int, choices=(9002, 9003, 9004))
    parser.add_argument("command", nargs="+")
    args = parser.parse_args()
    payload = json.dumps({"id": 1, "method": "slim.request", "params": ["", args.command]}).encode()
    request = Request(f"http://127.0.0.1:{args.port}/jsonrpc.js", data=payload,
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=15) as response:
        print(json.dumps(json.load(response), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
