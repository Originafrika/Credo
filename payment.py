import hashlib
import hmac
import json
import os
import time
import urllib.request
import urllib.error

FEDAPAY_API_KEY = os.environ.get("FEDAPAY_API_KEY", "")
FEDAPAY_WEBHOOK_SECRET = os.environ.get("FEDAPAY_WEBHOOK_SECRET", "")
FEDAPAY_SANDBOX = os.environ.get("FEDAPAY_SANDBOX", "true").lower() == "true"

BASE_URL = "https://sandbox-api.fedapay.com/v1" if FEDAPAY_SANDBOX else "https://api.fedapay.com/v1"

AMOUNTS = {"2500": 2500, "5000": 5000}


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {FEDAPAY_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def create_transaction(session_id: str, phone: str, plan: str, callback_url: str) -> dict | None:
    """Create a FedaPay transaction and return the payment URL."""
    amount = AMOUNTS.get(plan)
    if not amount:
        return None

    data = {
        "description": f"Credo — Rapport de solvabilité {'Complet' if plan == '5000' else 'Simple'}",
        "amount": amount,
        "currency": {"iso": "XOF"},
        "callback_url": callback_url,
        "custom_metadata": {"session_id": session_id, "plan": plan},
        "customer": {
            "phone_number": {"number": int(phone), "country": "TG"},
        },
    }

    try:
        req = urllib.request.Request(
            f"{BASE_URL}/transactions",
            data=json.dumps(data).encode(),
            headers=_headers(),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            tx = json.loads(resp.read().decode("utf-8")).get("transaction") or json.loads(resp.read().decode("utf-8"))
            return tx
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")[:500]
        print(f"[FEDAPAY] create_transaction failed ({e.code}): {body}", flush=True)
        return None
    except Exception as e:
        print(f"[FEDAPAY] create_transaction error: {e}", flush=True)
        return None


def get_payment_url(transaction_id: int) -> str | None:
    """Get the payment link URL for a transaction."""
    try:
        req = urllib.request.Request(
            f"{BASE_URL}/transactions/{transaction_id}/token",
            data=b"{}",
            headers=_headers(),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result.get("url")
    except Exception as e:
        print(f"[FEDAPAY] get_payment_url error: {e}", flush=True)
        return None


def verify_webhook(payload_body: bytes, signature_header: str) -> dict | None:
    """Verify FedaPay webhook signature and parse event."""
    if not FEDAPAY_WEBHOOK_SECRET:
        print("[FEDAPAY] WARNING: WEBHOOK_SECRET not configured — skipping signature verification", flush=True)
    else:
        expected = hmac.new(
            FEDAPAY_WEBHOOK_SECRET.encode(),
            payload_body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(f"sha256={expected}", signature_header):
            print("[FEDAPAY] Invalid webhook signature", flush=True)
            return None

    try:
        event = json.loads(payload_body.decode("utf-8"))
        return event
    except json.JSONDecodeError:
        return None


def handle_webhook_event(event: dict) -> dict | None:
    """Process a verified webhook event and return session_id + status."""
    name = event.get("name", "")
    data = event.get("data", {}).get("object", {})

    if name == "transaction.approved":
        metadata = data.get("custom_metadata", {}) or {}
        session_id = metadata.get("session_id")
        plan = metadata.get("plan")
        return {
            "session_id": session_id,
            "plan": plan,
            "status": "approved",
            "transaction_id": data.get("id"),
            "reference": data.get("reference"),
            "amount": data.get("amount"),
        }

    if name in ("transaction.declined", "transaction.canceled"):
        metadata = data.get("custom_metadata", {}) or {}
        return {
            "session_id": metadata.get("session_id"),
            "status": "failed",
        }

    return None
