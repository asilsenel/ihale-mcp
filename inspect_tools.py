import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

MCP_URL = "https://ihalemcp.fastmcp.app/mcp"

def list_tools():
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {}
    }

    resp = requests.post(
        MCP_URL,
        json=payload,
        timeout=30,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )

    print("HTTP status:", resp.status_code)
    print("Content-Type:", resp.headers.get("Content-Type"))
    print("RAW BODY:\n", resp.text[:2000])  # ilk 2000 char yeter

    try:
        data = resp.json()
    except Exception:
        print("\nJSON parse edilemedi, body yukarıda.")
        return

    print("\nJSON parsed:")
    print(json.dumps(data, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    list_tools()
