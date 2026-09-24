#!/usr/bin/env python3
"""Capture what Apple actually returns, to debug the checker. Writes site/debug.json.

- Raw pickup answers for the 96GB part in New York, next to everyday accessories that
  Apple Stores always stock (a control: if those say "available", parsing works).
- For each model's Apple Store page: where part numbers, RO_ product codes and 065-xxxx
  option codes appear, so build-to-order (256GB) queries can be built.
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_inventory as ci  # noqa: E402

CONTROLS = ["MX2D3AM/A", "MXK53AM/A", "MXP63AM/A"]  # Apple Pencil Pro, Magic Mouse, AirPods 4
ZIP = "10153"


def snippets(html, pattern, width=160, limit=6):
    out = []
    for m in re.finditer(pattern, html):
        out.append(html[max(0, m.start() - width): m.end() + width])
        if len(out) >= limit:
            break
    return out


def page_report(url):
    ci._failures = 0  # report every section, even after earlier refusals
    try:
        html = ci.http_get(url, headers=ci.PAGE_HEADERS)
    except Exception as exc:
        return {"url": url, "error": str(exc)}
    title = re.search(r"<title>(.*?)</title>", html, re.S)
    return {
        "url": url,
        "length": len(html),
        "title": title.group(1).strip() if title else "",
        "ro_codes": sorted(set(re.findall(r"RO_[A-Z0-9_]{6,}", html)))[:30],
        "z_codes": sorted(set(re.findall(r"\bZ1[A-Z0-9]{2,8}\b", html)))[:30],
        "standard_parts": sorted(set(re.findall(r"\b[MF][A-Z0-9]{4}LL/A\b", html)))[:30],
        "option_code_count": len(set(re.findall(r"065-[A-Z0-9]{4}", html))),
        "option_codes": sorted(set(re.findall(r"065-[A-Z0-9]{4}", html)))[:80],
        "near_part": snippets(html, r"MHL74LL|partNumber|\"part\"", limit=8),
        "near_ro": snippets(html, r"RO_[A-Z0-9_]{6,}", limit=6),
        "near_pickup": snippets(html, r"pickup-message|fulfillment-messages|option\.0", limit=6),
        "near_256": snippets(html, r"256GB|256gb", width=200, limit=4),
    }


def pickup_report(parts, referer):
    ci._failures = 0
    params = {"location": ZIP, **{f"parts.{i}": p for i, p in enumerate(parts)}}
    out = {}
    for name, (url, base) in ci.ENDPOINTS.items():
        try:
            data = json.loads(ci.http_get(url, {**base, **params}, {**ci.HEADERS, "Referer": referer}))
            stores = ci.store_list(data) or []
            out[name] = {
                "store_count": len(stores),
                "first_stores": [
                    {k: s.get(k) for k in ("storeNumber", "storeName", "partsAvailability")}
                    for s in stores[:2]
                ],
                "top_level_keys": sorted(data.get("body", {}).keys()) if isinstance(data, dict) else [],
                "store_keys": sorted(stores[0].keys()) if stores else [],
            }
        except Exception as exc:
            out[name] = {"error": str(exc)}
        ci.pause()
    return out


def main():
    config = json.loads(ci.CONFIG.read_text())
    m96, m256 = config["models"][0], config["models"][1]
    report = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "client": "curl_cffi" if ci.cffi_requests else "urllib",
        "pickup_96gb": pickup_report([m96["variants"][0]["part"]], m96["apple_url"]),
        "pickup_controls": pickup_report(CONTROLS, "https://www.apple.com/shop/accessories/all"),
        "pages": {
            "96gb": page_report(m96["apple_url"]),
            "256gb": [page_report(v["page"]) for v in m256["variants"][:2]],
            "mac_studio_buy": page_report("https://www.apple.com/shop/buy-mac/mac-studio"),
        },
    }
    out = ci.ROOT / "site" / "debug.json"
    out.write_text(json.dumps(report, indent=1))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
