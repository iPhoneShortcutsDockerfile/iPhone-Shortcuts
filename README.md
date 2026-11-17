# iPhone Shortcut JSON Backend (Flask)

## Render
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn --bind 0.0.0.0:$PORT main:app`

環境変数:
- `ADMIN_PASSWORD`: 管理画面/API用パスワード
- `FIREBASE_SERVICE_ACCOUNT_JSON`: FirebaseサービスアカウントJSONを1行のJSON文字列で設定
- `FIRESTORE_DATABASE_ID`: 名前付きFirestoreデータベースを使う場合のみ設定（通常は空欄）

管理画面: `/admin.site`
ヘルスチェック: `/health`

## iPhoneショートカットから登録・上書き
「URLの内容を取得」で `POST https://あなたのドメイン/api/shortcuts`
ヘッダー:
- `Content-Type: application/json`
- `Authorization: Bearer 管理者パスワード`

本文:
```json
{"number":"839251","json":{"name":"sample","items":[1,2,3]}}
```
同じ認証番号に送信すると、以前のJSON全体を新しいJSONで置き換えます（マージしません）。

## 認証番号で取得
`POST /api/lookup`
```json
{"number":"839251"}
```
レスポンスは登録したJSONそのものです。

Firestore collection: `shortcut_json_records`
document ID: 認証番号
field: `payload`
