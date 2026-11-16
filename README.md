# iPhoneショートカット用 JSON バックエンド（Flask版）

## 構成
- Backend: Python + Flask
- Production server: Gunicorn
- Database: Firebase Firestore
- Admin UI: HTML / CSS / JavaScript
- iPhone Shortcut: HTTP POST + JSON

## Renderへのデプロイ
1. ZIPを展開してGitHubリポジトリにアップロード
2. RenderでWeb Serviceを作成
3. RuntimeはPython
4. Build Command: `pip install -r requirements.txt`
5. Start Command: `gunicorn main:app`
6. Environmentに以下を登録
   - `ADMIN_PASSWORD`: 長くランダムな管理者パスワード
   - `FIREBASE_SERVICE_ACCOUNT_JSON`: FirebaseサービスアカウントJSON全体（1行）
   - `FIRESTORE_DATABASE_ID`: 通常は空欄でOK

## UptimeRobot
監視URL：
`https://あなたのRenderドメイン/health`

Monitor typeはHTTP(s)を選択してください。
※ UptimeRobotによる定期アクセスは稼働確認には使えますが、ホスティング側のスリープ・停止を必ず防げる保証はありません。

## 管理画面
`https://あなたのRenderドメイン/`

管理者パスワードを入力して、認証番号ごとの返却JSONを作成・編集できます。
辞書（Object）と序列（Array）のみ対応し、相互に入れ子にできます。

## iPhoneショートカット
「URLの内容を取得」を設定：
- URL: `https://あなたのRenderドメイン/api/lookup`
- 方法: POST
- 要求本文: JSON
- キー: `number`
- 値: 登録した認証番号

送信例：
```json
{"number":"839251"}
```

登録番号が正しければ、管理画面で保存したJSONそのものを返します。
未登録ならHTTP 401でエラーJSONを返します。

## API
- `GET /health` : UptimeRobot用のヘルスチェック
- `POST /api/lookup` : 認証番号を照合してJSONを返す
- `GET /api/records` : 管理者用・登録一覧
- `PUT /api/records` : 管理者用・登録/更新
- `DELETE /api/records/<number>` : 管理者用・削除

管理APIは `X-Admin-Password` ヘッダーで保護しています。
認証番号は現在、再利用可能です（ワンタイムではありません）。
