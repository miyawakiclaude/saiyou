# HireDent｜歯科クリニック採用管理SaaS

> 星の森デンタル向けに開発した、AIを活用した歯科クリニック専用の採用管理Webアプリケーション

![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)
![HTML](https://img.shields.io/badge/HTML-Single%20File-orange)
![AI](https://img.shields.io/badge/AI-Claude%20API-teal)

## 🦷 概要

HireDentは、歯科クリニックの採用業務をまるごとデジタル化するシングルファイルWebアプリです。サーバー不要・インストール不要で、HTMLファイルをブラウザで開くだけで使えます。

## ✨ 機能一覧

| 機能 | 説明 |
|------|------|
| 📊 ダッシュボード | 採用KPI・ファネルチャート・AIインサイトを一覧表示 |
| 📋 求人管理 | 求人票の作成・掲載状況・応募者数の管理 |
| 🗂 応募者ボード | カンバン方式でドラッグ&ドロップ選考管理 |
| ✦ AIスクリーニング | Claude APIによる履歴書評価・面接質問生成・医院マッチ度分析 |
| 📅 面接スケジュール | 週間カレンダーで面接日程を一元管理 |
| 📈 採用分析 | 応募経路別・月次推移のグラフ分析 |

## 🚀 セットアップ

### GitHub Pages で公開する場合

1. このリポジトリをフォーク（または clone）
2. リポジトリの **Settings → Pages** を開く
3. Source を `main` ブランチ、フォルダを `/ (root)` に設定
4. 数分後に `https://<your-username>.github.io/<repo-name>/` で公開される

### ローカルで使う場合

```bash
git clone https://github.com/<your-username>/hiredent.git
cd hiredent
open index.html   # macOS
# または
start index.html  # Windows
```

## 🔑 Claude API の設定

AIスクリーニング機能を使うには、Anthropic の API キーが必要です。

1. [Anthropic Console](https://console.anthropic.com/) でAPIキーを取得
2. `index.html` 内の fetch ヘッダーに `"x-api-key"` を追加：

```js
headers: {
  "Content-Type": "application/json",
  "x-api-key": "YOUR_API_KEY_HERE",   // ← 追加
  "anthropic-version": "2023-06-01",
  "anthropic-dangerous-direct-browser-access": "true"
}
```

> ⚠️ **注意**: APIキーをそのままコードに記載してGitHubに公開しないでください。本番運用では、バックエンドのプロキシ経由で呼び出すことを強く推奨します。

## 📁 ファイル構成

```
hiredent/
├── index.html      # アプリ本体（すべて1ファイルに収録）
└── README.md       # このファイル
```

## 🛠 技術スタック

- **フロントエンド**: Vanilla HTML / CSS / JavaScript（依存ライブラリなし）
- **AI**: Anthropic Claude API（claude-sonnet-4）
- **ホスティング**: GitHub Pages 対応

## 📄 ライセンス

MIT License — 自由に改変・利用可能です。

---

Made with ✦ Claude AI × 星の森デンタル
