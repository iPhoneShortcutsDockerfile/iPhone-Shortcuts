
import os
import json
import hmac
from functools import wraps

from flask import Flask, request, jsonify, send_from_directory
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__, static_folder="static")
db = None


def init_firestore():
    global db

    if db is not None:
        return db

    raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()

    if not raw:
        raise RuntimeError(
            "FIREBASE_SERVICE_ACCOUNT_JSON is not configured"
        )

    info = json.loads(raw)

    if not firebase_admin._apps:
        cred = credentials.Certificate(info)

        firebase_admin.initialize_app(
            cred,
            {"projectId": info.get("project_id")}
        )

    database_id = os.environ.get("FIRESTORE_DATABASE_ID", "").strip()

    if database_id:
        db = firestore.client(database_id=database_id)
    else:
        db = firestore.client()

    return db


def password_ok(value):
    expected = os.environ.get("ADMIN_PASSWORD", "")

    return (
        bool(expected)
        and isinstance(value, str)
        and hmac.compare_digest(
            value.encode("utf-8"),
            expected.encode("utf-8")
        )
    )


def supplied_password():
    auth = request.headers.get("Authorization", "")

    if auth.lower().startswith("bearer "):
        return auth[7:].strip()

    return (
        request.headers.get("X-Admin-Password")
        or request.args.get("admin_password")
        or (request.get_json(silent=True) or {}).get(
            "admin_password", ""
        )
    )


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not password_ok(supplied_password()):
            return jsonify({
                "error": "管理者パスワードが正しくありません"
            }), 401

        return fn(*args, **kwargs)

    return wrapped


@app.get("/health")
def health():
    return jsonify({"ok": True})


@app.get("/")
def home():
    return jsonify({
        "service": "iPhone Shortcut JSON Backend",
        "admin": "/admin.site"
    })


@app.get("/admin.site")
@app.get("/admin")
def admin():
    return send_from_directory(
        app.static_folder,
        "index.html"
    )


@app.get("/api/records")
@admin_required
def get_records():
    try:
        store = init_firestore().collection(
            "shortcut_json_records"
        )

        records = []

        for doc in store.stream():
            data = doc.to_dict() or {}

            records.append({
                "number": doc.id,
                "json": data.get("payload")
            })

        records.sort(key=lambda x: x["number"])

        return jsonify({"records": records})

    except Exception as e:
        app.logger.exception("Failed to load records")

        return jsonify({"error": str(e)}), 500


@app.put("/api/records")
@admin_required
def put_records():
    body = request.get_json(silent=True) or {}
    records = body.get("records")

    if not isinstance(records, list):
        return jsonify({
            "error": "records は配列で指定してください"
        }), 400

    seen = set()

    try:
        store = init_firestore().collection(
            "shortcut_json_records"
        )

        batch = init_firestore().batch()

        for item in records:
            if not isinstance(item, dict):
                return jsonify({
                    "error": "各項目はオブジェクトで指定してください"
                }), 400

            number = str(item.get("number", "")).strip()
            payload = item.get("json")

            if not number or len(number) > 200:
                return jsonify({
                    "error": "認証番号が空、または長すぎます"
                }), 400

            if number in seen:
                return jsonify({
                    "error": "認証番号が重複しています: " + number
                }), 400

            seen.add(number)

            if not isinstance(payload, (dict, list)):
                return jsonify({
                    "error": "JSON内容はObjectまたはArrayにしてください"
                }), 400

            batch.set(
                store.document(number),
                {"payload": payload}
            )

        existing = list(store.stream())

        for doc in existing:
            if doc.id not in seen:
                batch.delete(store.document(doc.id))

        batch.commit()

        return jsonify({
            "ok": True,
            "count": len(records)
        })

    except Exception as e:
        app.logger.exception("Failed to save records")

        return jsonify({"error": str(e)}), 500


@app.post("/api/shortcuts")
@admin_required
def shortcut_write():
    body = request.get_json(silent=True) or {}

    number = str(body.get("number", "")).strip()
    payload = body.get("json", body.get("payload"))

    if not number:
        return jsonify({
            "error": "number が必要です"
        }), 400

    if not isinstance(payload, (dict, list)):
        return jsonify({
            "error": "json はObjectまたはArrayで指定してください"
        }), 400

    try:
        init_firestore() \
            .collection("shortcut_json_records") \
            .document(number) \
            .set({"payload": payload})

        return jsonify({
            "ok": True,
            "number": number,
            "replaced": True
        })

    except Exception as e:
        app.logger.exception("Failed to write shortcut JSON")

        return jsonify({"error": str(e)}), 500


@app.post("/api/lookup")
def lookup():
    body = request.get_json(silent=True) or {}

    number = str(
        body.get("number", body.get("auth_number", ""))
    ).strip()

    if not number:
        return jsonify({
            "error": "number が必要です"
        }), 400

    try:
        doc = (
            init_firestore()
            .collection("shortcut_json_records")
            .document(number)
            .get()
        )

        if not doc.exists:
            return jsonify({
                "error": "該当する認証番号がありません"
            }), 404

        return jsonify(doc.to_dict().get("payload"))

    except Exception as e:
        app.logger.exception("Failed to lookup JSON")

        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000))
    )
