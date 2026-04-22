from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import urllib.request

BOARD_SLUG = "XEcHPHkgCZkQyHHaogG77M"
BOARD_UUID = "f4d89289-cf8b-40b0-9877-2983b8cfe310"
MIXPANEL_URL = "https://mixpanel.com/api/app/public/dashboard-cards"
VERIFY_URL = f"https://mixpanel.com/api/app/public/verify/{BOARD_UUID}/"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

CARDS = {
    "atm_30d":      89647758,
    "card_30d":     89647759,
    "atm_24h":      89647760,
    "card_24h":     89647761,
    "crypto_30d":   89647762,
    "pe_deposit_30d":    89647763,
    "pe_deposit_24h":    89647764,
    "pe_withdrawal_24h": 89647765,
    "pe_withdrawal_30d": 89647766,
}

CARD_LABELS = {
    "atm_30d":           "ATM 30 Days",
    "card_30d":          "Card Spend 30 Days",
    "atm_24h":           "ATM 24 Hours",
    "card_24h":          "Card Spend 24 Hours",
    "crypto_30d":        "Crypto Withdrawal 30 Days",
    "pe_deposit_30d":    "Punto Express Deposit 30 Days",
    "pe_deposit_24h":    "Punto Express Deposit 24 Hours",
    "pe_withdrawal_24h": "Punto Express Withdrawal 24 Hours",
    "pe_withdrawal_30d": "Punto Express Withdrawal 30 Days",
}


def get_auth_cookie():
    password = os.environ.get("LIMITS_PASSWORD", "").strip()
    body = json.dumps({"password": password}).encode()
    req = urllib.request.Request(VERIFY_URL, data=body, headers={
        "Content-Type": "application/json",
        "Origin": "https://mixpanel.com",
        "Referer": f"https://mixpanel.com/public/{BOARD_SLUG}",
        "User-Agent": UA,
    })
    with urllib.request.urlopen(req, timeout=10) as resp:
        cookies = [
            val.split(";")[0].strip()
            for name, val in resp.getheaders()
            if name.lower() == "set-cookie"
        ]
        return "; ".join(cookies)


def fetch_card(key, bid, auth_cookie):
    body = json.dumps({
        "uuid": BOARD_UUID,
        "bookmark_id": bid,
        "endpoint": "insights",
        "query_origin": "dashboard_public"
    }).encode()
    req = urllib.request.Request(MIXPANEL_URL, data=body, headers={
        "Content-Type": "application/json",
        "Origin": "https://mixpanel.com",
        "Referer": f"https://mixpanel.com/public/{BOARD_SLUG}",
        "User-Agent": UA,
        "Cookie": auth_cookie,
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    series = data["results"]["series"]
    metric = list(series.keys())[0]
    return key, {k: v for k, v in series[metric].items() if not k.startswith("$")}


def fetch_user(distinct_id):
    auth_cookie = get_auth_cookie()

    all_cards = {}
    with ThreadPoolExecutor(max_workers=9) as ex:
        futures = {ex.submit(fetch_card, key, bid, auth_cookie): key for key, bid in CARDS.items()}
        for f in as_completed(futures):
            key, users = f.result()
            all_cards[key] = users

    result = {}
    found_any = False
    for key in CARDS:
        user_data = all_cards[key].get(distinct_id)
        if user_data:
            found_any = True
            amount = user_data.get("all", 0)
            result[key] = {"amount": round(amount, 2), "label": CARD_LABELS[key]}
        else:
            result[key] = {"amount": None, "label": CARD_LABELS[key]}

    if not found_any:
        return None, "not_found"

    return result, None


class handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        uid = parse_qs(urlparse(self.path).query).get("id", [""])[0].strip()
        if not uid:
            self._json({"error": "missing_id"})
            return
        try:
            user, error = fetch_user(uid)
        except Exception as e:
            self._json({"error": str(e)})
            return

        if error == "not_found":
            self._json({"error": "not_found"})
        elif error:
            self._json({"error": error})
        else:
            self._json(user)

    def _json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)
