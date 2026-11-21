"""End-to-end read-only JSON-RPC checks on the isolated LMS 9.2 plugin."""
import json
from urllib.request import Request, urlopen


def rpc(*command):
    payload = json.dumps({"id": 1, "method": "slim.request",
                          "params": ["", list(command)]}).encode()
    request = Request("http://127.0.0.1:9002/jsonrpc.js", data=payload,
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def main():
    server = rpc("serverstatus", "0", "10")["result"]
    if server.get("version") != "9.2.0" or server.get("httpport") != "9002":
        raise RuntimeError("Wrong LMS target")
    status = rpc("phoneticsearch", "status", "?")["result"]
    if status.get("state") != "ready":
        raise AssertionError(status)
    for query, expected_match in (("Alphaville", "exact"),
                                  ("alpha will", "phonetic"),
                                  ("alfa will", "phonetic")):
        result = rpc("phoneticsearch", "0", "20", f"query:{query}",
                     "type:artist")["result"]
        hits = result.get("results_loop", [])
        if (result.get("index_state") != "ready" or not hits
                or hits[0]["name"] != "Alphaville"
                or hits[0]["match_type"] != expected_match):
            raise AssertionError((query, result))
    limited = rpc("phoneticsearch", "0", "1", "query:alfa will", "type:artist")["result"]
    if limited.get("count") != 1 or len(limited.get("results_loop", [])) != 1:
        raise AssertionError(limited)
    short = rpc("phoneticsearch", "0", "20", "query:a", "type:artist")["result"]
    if any(hit["match_type"] == "phonetic" for hit in short.get("results_loop", [])):
        raise AssertionError(short)
    bad = rpc("phoneticsearch", "0", "20", "query:test", "type:bogus")
    if bad.get("result", {}).get("error") != "invalid_parameter":
        raise AssertionError(bad)
    injection = rpc("phoneticsearch", "0", "20", "query:x' OR 1=1 --",
                    "type:artist")["result"]
    if injection.get("index_state") != "ready":
        raise AssertionError(injection)
    print("version=9.2 status=ready exact=Alphaville "
          "alpha_will=Alphaville alfa_will=Alphaville "
          "limit=1 short_no_fuzzy=1 bad_type=rejected injection=safe")


if __name__ == "__main__":
    main()
