import json
import os
import secrets
from functools import wraps

import firebase_admin
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from firebase_admin import credentials, firestore

load_dotenv()

app = Flask(__name__, static_folder="static")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
SERVICE_ACCOUNT_JSON = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "")
DATABASE_ID = os.getenv("FIRESTORE_DATABASE_ID", "").strip()

_db = None
_db_error = None


def get_db():
    global _db, _db_error
    if _db is not None:
        return _db
    if _db_error:
        raise RuntimeError(_db_error)
    try:
        if not SERVICE_ACCOUNT_JSON:
            raise RuntimeError(
                "FIREBASE_SERVICE_ACCOUNT_JSON is empty. Set the Firebase service account JSON."
            )
        info = json.loads(SERVICE_ACCOUNT_JSON)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(credentials.Certificate(info))
        _db = (
            firestore.client(database_id=DATABASE_ID)
            if DATABASE_ID
            else firestore.client()
        )
        return _db
    except Exception as exc:
        _db_error = str(exc)
        raise RuntimeError(_db_error)


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not ADMIN_PASSWORD:
            return jsonify({"error": "ADMIN_PASSWORD is not configured"}), 503
        supplied = request.headers.get("X-Admin-Password", "")
        if not supplied or not secrets.compare_digest(supplied, ADMIN_PASSWORD):
            return jsonify({"error": "管理者パスワードが違います"}), 401
        return fn(*args, **kwargs)
    return wrapper


@app.get("/")
def home():
    return send_from_directory("static", "index.html")


@app.get("/health")
def health():
    # UptimeRobot can monitor this endpoint.
    return jsonify({"ok": True})


@app.post("/api/lookup")
def lookup():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"ok": False, "error": "JSON object is required"}), 400
    number = str(body.get("number", "")).strip()
    if not number:
        return jsonify({"ok": False, "error": "number is required"}), 400

    try:
        snap = get_db().collection("shortcut_json_records").document(number).get()
    except Exception as exc:
        app.logger.exception("Firestore lookup failed")
        return jsonify({"ok": False, "error": "Backend database error"}), 503

    if not snap.exists:
        return jsonify({"ok": False, "error": "Invalid number"}), 401

    payload = (snap.to_dict() or {}).get("payload")
    # Return the stored JSON value itself, without an extra wrapper.
    return jsonify(payload)


@app.get("/api/records")
@admin_required
def list_records():
    try:
        docs = get_db().collection("shortcut_json_records").stream()
        result = [
            {"number": doc.id, "payload": (doc.to_dict() or {}).get("payload")}
            for doc in docs
        ]
        return jsonify(result)
    except Exception:
        app.logger.exception("Firestore list failed")
        return jsonify({"error": "Backend database error"}), 503


@app.put("/api/records")
@admin_required
def save_record():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "JSON object is required"}), 400
    number = str(body.get("number", "")).strip()
    if not number or len(number) > 100:
        return jsonify({"error": "number must be 1 to 100 characters"}), 400
    if "payload" not in body:
        return jsonify({"error": "payload is required"}), 400

    try:
        get_db().collection("shortcut_json_records").document(number).set({
            "payload": body["payload"]
        })
        return jsonify({"ok": True})
    except Exception:
        app.logger.exception("Firestore save failed")
        return jsonify({"error": "Backend database error"}), 503


@app.delete("/api/records/<path:number>")
@admin_required
def delete_record(number):
    try:
        get_db().collection("shortcut_json_records").document(number).delete()
        return jsonify({"ok": True})
    except Exception:
        app.logger.exception("Firestore delete failed")
        return jsonify({"error": "Backend database error"}), 503


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
