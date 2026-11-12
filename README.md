# market-dashboard

毎朝 06:30 頃（日本時間）に市場データを取得し、米国・日本・半導体の3分野の「現金比率の目安」と7銘柄の判定をスマホ向けのページに出す個人用ダッシュボードです。判定が変わった日や取得に失敗した日は Gmail に通知します。費用はかかりません（GitHub 無料プラン・FRED 無料 API・Gmail）。

> **注意**: このリポジトリと GitHub Pages のページは**公開**です（無料プランで Pages を使う条件）。検索エンジンに載らないよう `noindex` と `robots.txt` を設定済みですが、URL は他人に広めないでください。リポジトリやページに保有情報・メールアドレスは置きません。API キーなどは Secrets に入れます。判定は投資助言ではなく、参考表示です。

## セットアップ（最初の1回）

すべて GitHub の Web 画面で行えます。パスワードやキーの入力はご自身でお願いします。

1. **公開リポジトリを作る**
   GitHub で新しいリポジトリを **Public** で作り、このコードをブランチ `main` に push します。手元のブランチは `master` なので、リモートを登録したあと `git push -u origin master:main` で送ります。
2. **FRED の API キーを取る**
   https://fredaccount.stlouisfed.org/apikeys でアカウントを作り（無料）、API キーを発行します。
3. **Gmail のアプリパスワードを作る**
   Google アカウントで「2段階認証」を有効にしてから、アプリパスワードを発行します。手順: https://support.google.com/accounts/answer/185833
4. **Secrets を登録する**
   リポジトリの Settings → Secrets and variables → Actions → New repository secret で、次の4つを登録します。

   | 名前 | 中身 |
   |---|---|
   | `FRED_API_KEY` | 手順2のキー |
   | `GMAIL_ADDRESS` | 送信元の Gmail アドレス |
   | `GMAIL_APP_PASSWORD` | 手順3のアプリパスワード |
   | `NOTIFY_TO` | 通知を受け取るアドレス |

   Gmail の3つ（`GMAIL_ADDRESS`・`GMAIL_APP_PASSWORD`・`NOTIFY_TO`）は**任意**です。登録しなければメールは一切送られず、ページの更新はそのまま行われ、Actions も緑で終わります（手順3も不要）。

5. **GitHub Pages を有効にする**
   Settings → Pages → Build and deployment で Source を「Deploy from a branch」、Branch を `main`、フォルダを `/docs` にして Save します。ページの URL は `https://<ユーザー名>.github.io/<リポジトリ名>/` です。
6. **初回の実行（Actions の画面から手動で）**
   Actions → 左の「daily」→「Run workflow」を開き、
   1. まず `mode` を **backfill** にして実行（過去1年分の判定をさかのぼって計算。通知は送りません）
   2. 完了したら `mode` を **daily** にしてもう一度実行
   以降は毎朝自動で動きます。

   - backfill は**最初の1回だけ**の手順です。daily が一度でも履歴を書いたあとは、backfill を実行しても何も書き換えずに失敗（赤）で終わります。やり直したいときは `docs/data/history.json` を削除してから backfill → daily の順に実行し直してください。
   - さかのぼり計算では手入力の予想PERを使わないため、セットアップ直後の最初の数回の daily で比率が1回変わり、【判定変更】が届くことがあります。比率が下がる方向は2回連続の評価日で確定するルール（設計書 7.2）なので、数日遅れて届くこともあります。故障ではありません。
   - daily を市場の取引時間中に手動で実行しても、まだ確定していない当日の値は使いません（東京は 15:45、ニューヨークは現地 16:15 を過ぎるまで当日分を除外）。
7. **スマホのホーム画面に追加**
   スマホでページを開き、ブラウザの共有メニューから「ホーム画面に追加」を選びます。

## 週1回の手入力（TOPIX・SOX の予想PER）

予想PERは自動で取れないため手入力です。週に1回ほど、日経電子版などで確認して更新してください。

1. リポジトリの `config/manual.yaml` を開き、右上の鉛筆アイコン（Edit）を押します。
2. `value`（PERの値）と `updated`（更新日、`2026-11-12` の形式）を書き換えます。
3. 「Commit changes」を押して保存します。次の実行から反映されます。

```yaml
topix_per: {value: 13.7, updated: 2026-11-12}
sox_per: {value: 14.2, updated: 2026-11-12}
```

更新から14日を超えると、画面で警告色になります。

## 判定ルールを変える

点数表・段階表・閾値は `config/rules.yaml` にあります。同じように Web 画面から編集して保存します。

- `bands`: 指標ごとの点数表（上から順に評価。`le` は以下、`lt` は未満）
- `ratio_steps`: 合計点から現金比率への変換
- `verdict_table`: 比率ごとの銘柄判定（通常 / レバレッジ）
- `stale_limits`・`manual_overdue_days`・`stale_page_hours`: 前回値を使う期間や警告を出すまでの日数・時間

銘柄と分野の割り振りは `config/tickers.yaml` です。YAML の書式を壊すと実行が失敗するので、編集後は Actions が緑で終わるか確認してください。

## 画面の状態ラベル

| 表示 | 意味 |
|---|---|
| 取得 | 今回の実行で取得できた値 |
| 前回値（11/08） | 今回は取得に失敗。前回成功した値と日付を使っている（一定期間まで） |
| 手入力（11/05更新） | `config/manual.yaml` の値 |
| 取得失敗 | 取れず、使える前回値もない。その指標は判定に使わない |

月次・四半期の指標（CPI など）は、公表周期のため日付が古くても失敗ではありません。ページ上部の「最終更新」から36時間以上たつと赤い帯が出ます。Actions が止まっているサインです。

## 失敗したとき

- **Actions の daily が赤（×）になった**: メール送信に失敗したか、プログラムが落ちたかのどちらかです。メールの失敗の場合でも、データの更新と保存は先に済んでいるので、ページは更新されています。Actions の該当実行を開いてログを確認してください。Gmail の場合はアプリパスワードや Secrets の入力ミスが多い原因です。
- **ページに「市場データを取得できていません」の赤い帯が出た**: Yahoo Finance から株価指数を取れていません。比率と判定は帯に書かれた日の終値時点のまま据え置かれ、取れなくなった日と回復した日にそれぞれ1通メールが届きます。多くは一時的なもので、翌日以降に自然に戻ります。
- 赤になると GitHub から失敗の通知メールが届きます（通知設定による）。
- `test` ワークフローは push のたびにテストを実行します。

## 開発者向け

```
pip install -r requirements.txt && pip install -e .
python -m pytest -q
python -m dash daily            # 日次実行（Gmail 用の環境変数がなければ通知しない）
python -m dash backfill --days 365   # 初回のみ。daily の履歴があると何もせず終了コード1
```
