import os
import json
import hmac
from functools import wraps

from flask import Flask, request, jsonify, send_from_directory
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__, static_folder="static")
db = None
COLLECTION = "shortcut_json_records"


def init_firestore():
    global db
    if db is not None:
        return db
    raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_JSON is not configured")
    info = json.loads(raw)
    if not firebase_admin._apps:
        cred = credentials.Certificate(info)
        firebase_admin.initialize_app(cred, {"projectId": info.get("project_id")})
    database_id = os.environ.get("FIRESTORE_DATABASE_ID", "").strip()
    db = firestore.client(database_id=database_id) if database_id else firestore.client()
    return db


def password_ok(value):
    expected = os.environ.get("ADMIN_PASSWORD", "")
    return bool(expected and isinstance(value, str) and
                hmac.compare_digest(value.encode("utf-8"), expected.encode("utf-8")))


def request_body():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def supplied_password():
    auth = request.headers.get("Authorization", "").strip()
    if auth:
        return auth[7:].strip() if auth.lower().startswith("bearer ") else auth
    body = request_body()
    return (request.headers.get("X-Admin-Password")
            or request.args.get("admin_password")
            or body.get("admin_password", ""))


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not password_ok(supplied_password()):
            return jsonify({"error": "管理者パスワードが正しくありません"}), 401
        return fn(*args, **kwargs)
    return wrapped


def valid_dictionary(value):
    """Allow nested dictionaries whose leaf values are all text."""
    return (
        isinstance(value, dict)
        and all(
            isinstance(k, str)
            and (isinstance(v, str) or valid_dictionary(v))
            for k, v in value.items()
        )
    )


def dictionary_matches(expected, incoming):
    """Match configured keys recursively; extra incoming keys are allowed."""
    if not isinstance(expected, dict) or not isinstance(incoming, dict):
        return False
    for key, value in expected.items():
        if key not in incoming:
            return False
        actual = incoming[key]
        if isinstance(value, dict):
            if not dictionary_matches(value, actual):
                return False
        elif not isinstance(actual, str) or actual != value:
            return False
    return True


def normalize_rule(value):
    if not isinstance(value, dict):
        raise ValueError("各ルールはオブジェクトで指定してください")
    post = value.get("post", {})
    response = value.get("response", {})
    if not valid_dictionary(post):
        raise ValueError("POSTはTextのキーと値を持つ辞書にしてください")
    if not valid_dictionary(response):
        raise ValueError("返却する内容はTextのキーと値を持つ辞書にしてください")
    if not post:
        raise ValueError("POSTの項目を1つ以上設定してください")
    if not response:
        raise ValueError("返却する内容を1つ以上設定してください")
    return {"post": post, "response": response}


def flatten_keys(value):
    for key, child in value.items():
        yield key
        if isinstance(child, dict):
            yield from flatten_keys(child)


@app.get("/health")
def health():
    return jsonify({"ok": True})


@app.get("/")
def home():
    return jsonify({"service": "POST Dictionary Backend", "admin": "/admin.site"})


@app.get("/admin.site")
@app.get("/admin")
def admin():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/records")
@admin_required
def get_records():
    try:
        store = init_firestore().collection(COLLECTION)
        records = []
        for doc in store.stream():
            data = doc.to_dict() or {}
            # Ignore old auth-code records: this version starts with POST rules only.
            if isinstance(data.get("post"), dict) and isinstance(data.get("response"), dict):
                records.append({"id": doc.id, "post": data["post"], "response": data["response"]})
        records.sort(key=lambda x: x["id"])
        return jsonify({"records": records})
    except Exception as e:
        app.logger.exception("Failed to load records")
        return jsonify({"error": str(e)}), 500


@app.put("/api/records")
@admin_required
def put_records():
    raw_records = request_body().get("records")
    if not isinstance(raw_records, list):
        return jsonify({"error": "records は配列で指定してください"}), 400

    prepared = []
    try:
        for item in raw_records:
            prepared.append(normalize_rule(item))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    try:
        store = init_firestore().collection(COLLECTION)
        existing = list(store.stream())
        # Replace the rule set completely; IDs are generated by Firestore.
        for start in range(0, len(existing), 450):
            batch = init_firestore().batch()
            for doc in existing[start:start + 450]:
                batch.delete(doc.reference)
            batch.commit()

        for start in range(0, len(prepared), 450):
            batch = init_firestore().batch()
            for rule in prepared[start:start + 450]:
                ref = store.document()
                batch.set(ref, rule)
            batch.commit()

        return jsonify({"ok": True, "count": len(prepared)})
    except Exception as e:
        app.logger.exception("Failed to replace rules")
        return jsonify({"error": str(e)}), 500


@app.post("/api/shortcuts")
@admin_required
def shortcut_write():
    body = request_body()
    try:
        rule = normalize_rule(body)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    try:
        ref = init_firestore().collection(COLLECTION).document()
        ref.set(rule)
        return jsonify({"ok": True, "id": ref.id})
    except Exception as e:
        app.logger.exception("Failed to add rule")
        return jsonify({"error": str(e)}), 500


@app.post("/api/lookup")
def lookup():
    incoming = request_body()
    if not incoming:
        return jsonify({"error": "POSTの辞書をJSONで送信してください"}), 400

    try:
        store = init_firestore().collection(COLLECTION)
        matches = []
        for doc in store.stream():
            rule = doc.to_dict() or {}
            expected = rule.get("post")
            response = rule.get("response")
            if not valid_text_dictionary(expected) or not valid_dictionary(response):
                continue
            # A rule matches when every configured POST key/value is present and identical.
            if expected and all(
                isinstance(incoming.get(key), str) and incoming.get(key) == value
                for key, value in expected.items()
            ):
                matches.append((len(expected), doc.id, response))

        if not matches:
            return jsonify({"error": "一致するPOST設定がありません"}), 404

        # Prefer the most specific matching dictionary; stable ID tie-breaker.
        matches.sort(key=lambda item: (-item[0], item[1]))
        return jsonify(matches[0][2])
    except Exception as e:
        app.logger.exception("Failed to lookup POST dictionary")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
