# 投資判断ダッシュボード 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 毎朝 GitHub Actions で市場データを取得し、米国・日本・半導体の3分野のキャッシュ比率の目安と7銘柄の判定・理由を計算して、GitHub Pages のスマホ向けページに表示し、変化があれば Gmail で通知する。

**Architecture:** 計算はすべて Python（`src/dash/`）で行い、`docs/data/latest.json` と `docs/data/history.json` を書き出す。ページ（`docs/index.html` + `app.js`）は表示だけを担当する。取得・指標計算・点数・判定・理由文・履歴・通知はそれぞれ別モジュールの純粋関数に分け、`pipeline.py` がつなぐ。

**Tech Stack:** Python 3.12（ローカル検証は 3.12 以上）、yfinance、pandas、requests、PyYAML、pytest／素の HTML+JS、Chart.js 4.4.1（cdnjs）／GitHub Actions、GitHub Pages、Gmail SMTP

**Spec:** `docs/superpowers/specs/2026-11-12-market-dashboard-design.md`（必ず併読すること。点数表・判定表の値はそこが正）

## Global Constraints

- 取得に失敗した値を、ハードコードした既定値で埋めない。どの指標も状態 `live` / `stale` / `manual` / `missing` のどれかを必ず持つ（仕様 6.2）。
- リポジトリ・ページ・JSON に、保有情報、個人情報、メールアドレス、APIキーを置かない。秘密情報は環境変数（Secrets）`FRED_API_KEY` `GMAIL_ADDRESS` `GMAIL_APP_PASSWORD` `NOTIFY_TO` からのみ読む。
- ページには `<meta name="robots" content="noindex,nofollow">` を入れ、`docs/robots.txt` は `User-agent: *` / `Disallow: /` にする。
- キャッシュ比率は `0, 10, 20, 35, 50, 70, 90` のどれかの値だけを取る。
- 点数表・段階表・判定表・閾値は `config/rules.yaml` に置き、コードに数値を直書きしない（テストの期待値は除く）。
- 外部への通信は `src/dash/fetch_*.py` の中だけで行う。それ以外のモジュールは純粋関数にし、テストではネットワークを使わない。
- UI の文言は日本語。フッターに「個人の判断補助であり投資助言ではありません」と表示する。
- 外部スクリプトは `https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js` だけ。
- スケジュールは毎日 `30 21 * * *`（UTC、06:30 JST）と手動実行（workflow_dispatch）。

## Review Focus

1. **CNN が毎日拒否され続ける**：`fg` は毎回 `missing` になる。判定は他の指標で続け、取得失敗メールは失敗が始まった日に1通だけ届く（Task 8）。
2. **土日・祝日の実行**：`^GSPC` と `^N225` の最新日付が前回の評価と同じなら、履歴に追記せず、判定変更メールも出さない。ただし `latest.json` の `generated_at` は更新し、ページに誤った警告帯は出ない（Task 9）。
3. **上場1年未満・空データの銘柄**（キオクシア `285A.T` など）：手元にある期間で高値比を計算し、空なら `drop_pct=None` として、その銘柄だけ「データなし」と表示する。クラッシュしない（Task 2、Task 6）。
4. **`config/manual.yaml` の壊れ・空欄・日付なし**：該当の手入力指標だけ `missing` になり、実行全体は止まらない（Task 1、Task 4）。
5. **初回実行（`latest.json` も `history.json` もない）**：前回値なしとして動き、前日比・判定変化は空欄、通知は出さない（Task 7、Task 9）。

---

## ファイル構成

```
market-dashboard/
├ pyproject.toml                 … パッケージ dash（src レイアウト）、pytest 設定
├ requirements.txt               … yfinance, pandas, requests, PyYAML, pytest
├ config/
│   ├ tickers.yaml               … 銘柄・分野・性質メモ・レバ/補正フラグ
│   ├ rules.yaml                 … 指標の帯（bands）、SOX複合ルール、比率の段階表、判定表、閾値
│   └ manual.yaml                … topix_per, sox_per とそれぞれの更新日
├ src/dash/
│   ├ models.py                  … Metric, AreaResult, TickerResult などのデータクラス
│   ├ config.py                  … YAML の読み込みと検証
│   ├ indicators.py              … 高値比・連続日数・前年比などの純粋計算
│   ├ fetch_yahoo.py / fetch_fred.py / fetch_cnn.py … 取得（リトライ付き）
│   ├ metrics.py                 … 生データ → 指標（状態つき）
│   ├ scoring.py                 … 点数・分野合計・保留・比率・ヒステリシス
│   ├ verdict.py                 … 銘柄判定
│   ├ reasons.py                 … 理由文
│   ├ history.py                 … 履歴の読み書き・評価日判定・N日前の検索
│   ├ notify.py                  … 通知内容の差分作成・Gmail 送信
│   ├ pipeline.py                … daily / backfill の組み立てと JSON 書き出し
│   └ __main__.py                … CLI: python -m dash daily|backfill
├ tests/                         … 各モジュールに対応する test_*.py と fixtures/
├ docs/                          … index.html, app.js, style.css, robots.txt, manifest.webmanifest, icon.svg, data/
├ .github/workflows/daily.yml
└ README.md
```

## 共通の型（Task 1 で定義。以降のタスクはこの名前を使う）

```python
# src/dash/models.py
Status = Literal["live", "stale", "manual", "missing"]

@dataclass
class Metric:
    key: str                 # 例 "fg", "sox_drop"
    label: str               # 例 "Fear & Greed"
    value: float | None      # missing のとき None
    status: Status
    as_of: str | None        # 観測日 "YYYY-MM-DD"（manual は更新日）
    unit: str = ""           # "%", "倍", "日", "ドル", ""
    stale_evals: int = 0     # stale になってからの評価日数
    extra: dict = field(default_factory=dict)   # 例 sox: {"days": 99, "peak_date": ...}

@dataclass
class Contribution:
    key: str                 # 指標キー（"sox_combo" のような複合ルールも可）
    points: int | None       # missing なら None

@dataclass
class AreaResult:
    area: str                # "us" | "jp" | "semi"
    points: int
    ratio: int               # ヒステリシス適用後
    raw_ratio: int           # 段階表で出した値（適用前）
    ratio_excl_manual: int   # manual 指標を除いて計算した比率（つなぎ目の段差確認用）
    on_hold: bool
    pending_down: int | None # 下げ待ちの候補比率（1回目を満たした状態）
    contributions: list[Contribution]
    missing: list[str]       # missing だった指標キー
    reason: str = ""
    prev_ratio: int | None = None   # 直前の評価日の ratio（初回は None）

@dataclass
class TickerResult:
    symbol: str; name: str; area: str
    price: float | None
    drop_pct: float | None   # 52週高値からの下落率（正の数、%）
    verdict: str             # "買い増し" | "保有" | "利確 1/4" | "利確 1/3" | "利確 1/2" | "全利確" | "データなし"
    reason: str = ""
    prev_verdict: str | None = None # 直前の評価日の verdict（初回は None）
```

分野ごとの指標キー（`config/rules.yaml` の `areas` に書く）：
- `us`: `fg`, `ndx_drop`, `us10y_streak`
- `jp`: `n225_drop`, `topix_per`, `usdjpy_1m`
- `semi`: `sox_combo`, `sox_per`, `fg`, `capex_gdp`
- `common`（全分野に加算）: `gdp_spread`, `cpi_yoy`, `wti`

---

### Task 1: 土台・設定ファイル・データクラス

**Files:**
- Create: `pyproject.toml`, `requirements.txt`, `.gitignore`（`.venv/`, `__pycache__/`, `.pytest_cache/`）
- Create: `src/dash/__init__.py`, `src/dash/models.py`, `src/dash/config.py`
- Create: `config/tickers.yaml`, `config/rules.yaml`, `config/manual.yaml`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `models.py` の上記の型一式
- Produces: `load_tickers(path: Path) -> list[TickerConfig]`。`TickerConfig(symbol: str, name: str, area: str, note: str, leveraged: bool = False, cautious_when_area_ratio_ge: int | None = None)`
- Produces: `load_rules(path: Path) -> dict`（YAML をそのまま dict で返す。必須キー `areas`, `bands`, `sox_combo`, `ratio_steps`, `verdict_table`, `adjust`, `stale_limits`, `hold_missing_fraction` がなければ `ValueError`）
- Produces: `load_manual(path: Path, today: date) -> dict[str, Metric]`（キー `topix_per`, `sox_per`。正常なら `status="manual"`、`as_of=更新日`、`extra={"days_since_update": n, "overdue": n > 14}`。値・日付が欠けている／YAML が壊れているときは、その指標だけ `missing` で返し、例外を出さない）

`config/tickers.yaml` の中身（仕様5の表どおり）：VTI(us)、1321.T「NF日経225」(jp)、NVDA・SOXL(`leveraged: true`)・6146.T「ディスコ」・7735.T「SCREEN」・285A.T「キオクシア」(`cautious_when_area_ratio_ge: 35`)、すべて semi。`note` に仕様5の「性質メモ」を書き写す。

`config/rules.yaml` の中身：
- `bands`：指標ごとの帯のリスト。帯は `{lt: x, points: p}`（x 未満）か `{le: x, points: p}`（x 以下）を上から順に評価し、最後は `{points: p}`（それ以外）。仕様7.3の表をこの形に写す。例：
  - `fg`: `le 9 → -3`, `le 10 → -2`, `le 20 → -1`, `lt 70 → 0`, `le 80 → 2`, それ以外 `3`
  - `ndx_drop`: `lt 10 → 0`, `le 15 → -1`, それ以外 `0`
  - `us10y_streak`: `le 0 → 0`, `le 30 → 1`, `lt 90 → 0`, それ以外 `-1`
  - `cpi_yoy`: `lt 3.0 → 0`, `lt 3.5 → -1`, それ以外 `1`
  - `usdjpy_1m`（%、マイナス＝円高）: `le -5 → 2`, `le -3 → 1`, それ以外 `0`
  - 残り（`n225_drop`, `topix_per`, `sox_per`, `capex_gdp`, `gdp_spread`, `wti`）も仕様7.3どおりに書く
- `sox_combo`: `{deep_drop: 28, days_min: 25, days_max: 45, deep_in_window: -3, deep_outside: -1, high_drop_lt: 5, high_fg_ge: 70, high_points: 2}`
- `ratio_steps`: `[{le: -6, ratio: 0}, {le: -3, ratio: 10}, {le: 1, ratio: 20}, {le: 3, ratio: 35}, {le: 5, ratio: 50}, {le: 7, ratio: 70}, {ratio: 90}]`
- `verdict_table`: 比率 → `{normal: ..., leveraged: ...}`（仕様7.4の表。90% の leveraged は `全利確`）
- `verdict_levels`: `["買い増し", "保有", "利確 1/4", "利確 1/3", "利確 1/2", "全利確"]`（補正で1段階動かすための順序）
- `adjust`: `{deep_drop_pct: 30, deep_drop_max_area_ratio: 35}`
- `stale_limits`（評価日数）: `{daily: 3, monthly: 25, quarterly: 70}`
- `hold_missing_fraction: 0.5`（missing の数が分野の指標数×0.5 を**超えたら**保留）
- `manual_overdue_days: 14`、`stale_page_hours: 36`

`config/manual.yaml`：`topix_per: {value: 13.7, updated: 2026-11-12}`、`sox_per: {value: 14.2, updated: 2026-11-12}`。初期値はユーザーの元資料の値。README でユーザーが更新する。

- [ ] **Step 1: 失敗するテストを書く** — `tests/test_config.py`
  - `test_load_tickers_has_seven_with_areas`：7銘柄、`SOXL.leveraged is True`、`285A.T.cautious_when_area_ratio_ge == 35`、分野は us 1 / jp 1 / semi 5
  - `test_load_rules_missing_key_raises`：`bands` を消した一時 YAML で `ValueError`
  - `test_load_manual_ok`：`today=2026-11-20`、更新日 2026-11-05 → `status=="manual"`、`extra["days_since_update"]==15`、`extra["overdue"] is True`
  - `test_load_manual_broken_entry_is_missing`：`sox_per: {value: null}` → `sox_per.status=="missing"`、`topix_per` は manual のまま
  - `test_load_manual_broken_yaml_is_all_missing`：中身が `":::"` のファイル → 2指標とも missing、例外なし
- [ ] **Step 2: 実行して失敗を確認** — `python -m pytest tests/test_config.py -v` → FAIL（モジュールがない）
- [ ] **Step 3: models.py、config.py、3つの YAML を実装**
- [ ] **Step 4: 実行して成功を確認** — 同じコマンド → 5 passed
- [ ] **Step 5: コミット** — `git add -A && git commit -m "feat: project scaffold, config loaders and models"`

---

### Task 2: 指標の純粋計算

**Files:**
- Create: `src/dash/indicators.py`
- Test: `tests/test_indicators.py`

**Interfaces:**
- Consumes: なし（pandas の `Series`。index は昇順の `DatetimeIndex`、値は float）
- Produces:
  - `drawdown_from_high(closes: pd.Series, window_days: int = 365) -> tuple[float, int, str] | None` … 最終日から暦日 365 日以内の最高値に対する下落率（正の%、小数1桁）、高値日から最終日までの**営業日数**（＝高値日より後の行数）、高値日。空なら `None`。期間が1年未満でもあるデータで計算する
  - `streak_above(series: pd.Series, threshold: float) -> int` … 最終行から遡って `>= threshold` が続く行数。最終行が未満なら 0
  - `yoy_pct(series: pd.Series, periods: int) -> float | None` … `(最終 / periods行前 - 1) * 100`（小数2桁）。行が足りなければ `None`
  - `change_pct_days(series: pd.Series, days: int) -> float | None` … 最終日から暦日 `days` 日前以前で最も近い値に対する変化率（%）
  - `ratio_pct(numer: pd.Series, denom: pd.Series) -> float | None` … 両方に共通する最新日付での `numer / denom * 100`（小数1桁）
  - `as_of(series: pd.Series, d: date) -> pd.Series` … `d` 以前に切り詰めた Series（さかのぼり計算用）

- [ ] **Step 1: 失敗するテストを書く**
  - `test_drawdown_basic`：100,120,90（3営業日）→ `(25.0, 1, <120の日付>)`
  - `test_drawdown_short_history`：5行だけでも計算できる
  - `test_drawdown_empty_returns_none`
  - `test_drawdown_ignores_peak_older_than_window`：400日前の 200 は無視し、窓内の最高値で計算する
  - `test_streak_above_counts_consecutive`：`[4.6, 4.4, 4.5, 4.6, 4.7]` → 3。`[4.6, 4.4]` → 0
  - `test_yoy_pct_monthly`：13行で最終が先頭の1.037倍 → `3.7`
  - `test_yoy_pct_insufficient_none`
  - `test_change_pct_days_yen`：30日前 150、最新 142.5 → `-5.0`
  - `test_ratio_pct_aligns_dates`：PNFI と GDP の最新日付がずれていても共通日付で 14.2
- [ ] **Step 2: 実行して失敗を確認** — `python -m pytest tests/test_indicators.py -v` → FAIL
- [ ] **Step 3: indicators.py を実装**
- [ ] **Step 4: 実行して成功を確認** — 9 passed
- [ ] **Step 5: コミット** — `git commit -m "feat: indicator calculations"`

---

### Task 3: データ取得（Yahoo / FRED / CNN）

**Files:**
- Create: `src/dash/fetch_yahoo.py`, `src/dash/fetch_fred.py`, `src/dash/fetch_cnn.py`, `src/dash/http.py`（リトライ付き GET）
- Test: `tests/test_fetch.py`（`monkeypatch` で HTTP と yfinance を差し替える。ネットワークは使わない）

**Interfaces:**
- Produces: `get_with_retry(url: str, *, params: dict | None = None, headers: dict | None = None, timeout: int = 30, retries: int = 2, backoff: float = 2.0) -> requests.Response`（`raise_for_status` 済み。全試行失敗で最後の例外を送出）
- Produces: `fetch_closes(symbols: list[str], period: str = "2y") -> dict[str, pd.Series]` … 銘柄ごとに `yf.Ticker(s).history(period=period, interval="1d")["Close"]`。index はタイムゾーンを外して日付だけにする。失敗・空の銘柄は**辞書に入れない**（例外を外に出さない）。失敗理由は `logging.warning`
- Produces: `fetch_fred(series_id: str, api_key: str, start: str = "2023-01-01") -> pd.Series` … `https://api.stlouisfed.org/fred/series/observations`、`params={series_id, api_key, file_type: "json", observation_start: start}`。値 `"."` は捨てる。失敗時は例外を送出（呼び出し側で missing にする）
- Produces: `fetch_fear_greed() -> pd.Series` … `https://production.dataviz.cnn.io/index/fearandgreed/graphdata`。ブラウザ相当の `User-Agent` と `Referer: https://edition.cnn.com/` を付ける。`fear_and_greed_historical.data`（`x`=ミリ秒、`y`=値）があれば履歴として返し、なければ `fear_and_greed.score` 1点の Series。失敗時は例外を送出
- 取得する Yahoo シンボル（定数 `MARKET_SYMBOLS` を `fetch_yahoo.py` に置く）：`^GSPC ^NDX ^SOX ^N225 JPY=X CL=F` ＋ tickers.yaml の7銘柄
- FRED シリーズ（定数 `FRED_SERIES` を `fetch_fred.py` に置く）：`DGS10 GDP CPIAUCSL EFFR PNFI`

- [ ] **Step 1: 失敗するテストを書く**
  - `test_get_with_retry_retries_then_succeeds`：1回目タイムアウト、2回目 200 → 成功し、呼び出し回数は2（`time.sleep` も差し替える）
  - `test_get_with_retry_raises_after_all_fail`
  - `test_fetch_fred_drops_dot_values`：`{"observations":[{"date":"2026-10-01","value":"4.5"},{"date":"2026-10-02","value":"."}]}` → 長さ1
  - `test_fetch_fear_greed_uses_history`：`historical.data` 2点 → 長さ2の Series
  - `test_fetch_closes_skips_failed_symbol`：`285A.T` の yfinance が例外 → 返り値にそのキーがなく、他は入る
- [ ] **Step 2: 実行して失敗を確認** — `python -m pytest tests/test_fetch.py -v` → FAIL
- [ ] **Step 3: 実装**
- [ ] **Step 4: 実行して成功を確認** — 5 passed
- [ ] **Step 5: 実データでの手動確認（テストではない）** — `python -c "from dash.fetch_yahoo import fetch_closes; print({k: len(v) for k, v in fetch_closes(['^SOX','285A.T']).items()})"` で2つとも行数が出ること。CNN と FRED は失敗してもよい（結果をコミットメッセージに書く）
- [ ] **Step 6: コミット** — `git commit -m "feat: data fetchers with retry"`

---

### Task 4: 生データ → 状態つき指標

**Files:**
- Create: `src/dash/metrics.py`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Consumes: Task 2 の関数、Task 1 の `Metric`、`load_manual` の結果
- Produces: `RawData` データクラス：`closes: dict[str, pd.Series]`、`fred: dict[str, pd.Series]`、`fg: pd.Series | None`、`errors: dict[str, str]`（取得元ごとの失敗理由）
- Produces: `compute_metrics(raw: RawData, asof: date | None, manual: dict[str, Metric] | None) -> dict[str, Metric]` … `asof` が与えられたら全 Series を `as_of` で切り詰める（さかのぼり用）。`manual=None` なら `topix_per` / `sox_per` は**キー自体を入れない**（さかのぼりでは使わない）。作る指標と計算：
  - `fg`（最新値）、`ndx_drop` / `n225_drop`（`drawdown_from_high` の下落率）
  - `sox_drop`（下落率。`extra={"days": 営業日数, "peak_date": ...}`）
  - `us10y`（DGS10 最新）、`us10y_streak`（`streak_above(DGS10, 4.5)`）
  - `gdp_yoy`（`yoy_pct(GDP, 4)`）、`gdp_spread`（`gdp_yoy - us10y`）
  - `cpi_yoy`（`yoy_pct(CPIAUCSL, 12)`）、`wti`、`usdjpy_1m`（`change_pct_days(JPY=X, 30)`）
  - `capex_gdp`（`ratio_pct(PNFI, GDP)`）、`effr`（参考表示のみ。点数なし）
  - 入力が欠けている指標は `status="missing", value=None`。`gdp_spread` は片方でも欠ければ missing
  - `as_of` は使った Series の最終日付
- Produces: `carry_forward(current: dict[str, Metric], previous: dict[str, Metric] | None, limits: dict, freq: dict[str, str]) -> dict[str, Metric]` … `current` で missing の指標について、`previous` に値があり `previous.stale_evals + 1 <= limits[freq[key]]` なら、前回の値と `as_of` で `status="stale"`、`stale_evals+1` にする。前回が live/manual なら `stale_evals=1` から数える。それ以外は missing のまま
- Produces: 定数 `METRIC_FREQ: dict[str, str]`（`daily` / `monthly` / `quarterly`）と `METRIC_LABELS: dict[str, tuple[str, str]]`（ラベル, 単位）

- [ ] **Step 1: 失敗するテストを書く**（`tests/fixtures/` に小さな合成 Series を作るヘルパーを置く）
  - `test_compute_metrics_all_live`：全部そろった RawData → `sox_drop.extra["days"]` が正しく、`gdp_spread == gdp_yoy - us10y`
  - `test_compute_metrics_fred_missing`：`fred={}` → `us10y_streak`、`gdp_spread`、`cpi_yoy`、`capex_gdp` が missing で、`ndx_drop` は live
  - `test_compute_metrics_asof_truncates`：`asof` を半年前にすると `sox_drop` の値が変わる
  - `test_compute_metrics_backfill_has_no_manual_keys`：`manual=None` → `"topix_per" not in result`
  - `test_carry_forward_daily_within_limit`：前回 live の fg=17 → 今回 missing なら `stale`、値 17、`stale_evals==1`
  - `test_carry_forward_daily_exceeds_limit`：前回 `stale_evals==3` → missing のまま
  - `test_carry_forward_no_previous`：`previous=None` → missing のまま
- [ ] **Step 2: 実行して失敗を確認** — `python -m pytest tests/test_metrics.py -v` → FAIL
- [ ] **Step 3: 実装**
- [ ] **Step 4: 実行して成功を確認** — 7 passed
- [ ] **Step 5: コミット** — `git commit -m "feat: metrics with live/stale/manual/missing status"`

---

### Task 5: 点数・分野合計・保留・比率・ヒステリシス

**Files:**
- Create: `src/dash/scoring.py`
- Test: `tests/test_scoring.py`

**Interfaces:**
- Consumes: `Metric`, `Contribution`, `AreaResult`、rules dict
- Produces:
  - `band_points(value: float, bands: list[dict]) -> int`
  - `sox_combo_points(sox_drop: Metric, fg: Metric | None, cfg: dict) -> int | None` … `sox_drop` が missing なら None。下落≥28 かつ 25≤日柄≤45 → -3、下落≥28 → -1、下落<5 かつ fg が使えて ≥70 → +2、それ以外 0
  - `score_area(area: str, metrics: dict[str, Metric], rules: dict, apply_hold: bool = True, exclude_manual: bool = False) -> tuple[int, list[Contribution], list[str], bool]` … （合計点, 内訳, missing キー, 保留か）。対象指標は `rules["areas"][area] + rules["areas"]["common"]`。metrics にキーがない指標は「対象外」として分母からも外す（さかのぼりの手入力PER）。`exclude_manual=True` なら manual の指標も分母ごと外す。保留は `apply_hold` かつ `len(missing) > len(対象) * hold_missing_fraction`
  - `points_to_ratio(points: int, steps: list[dict]) -> int`
  - `apply_hysteresis(raw_ratio: int, prev_ratio: int | None, prev_pending: int | None) -> tuple[int, int | None]` … （採用比率, 次回の pending）。仕様7.2：上げは即日。下げは、前回の pending があり今回も `raw_ratio < prev_ratio` なら `max(raw_ratio, prev_pending)` を採用して pending を消す。前回の pending がなければ比率は据え置き、pending に `raw_ratio` を入れる。`prev_ratio is None` なら `raw_ratio` をそのまま使う
  - `evaluate_area(area, metrics, rules, prev: dict | None, apply_hold=True) -> AreaResult` … 上の関数をまとめる。`prev` は前回の評価日の `{"ratio", "pending_down"}`。保留のときは `ratio = prev["ratio"]`（前回がなければ 20）、`pending_down` は前回のまま。`ratio_excl_manual` は `exclude_manual=True` で出した点数を段階表にかけた値（ヒステリシスなし）

- [ ] **Step 1: 失敗するテストを書く**（rules は `config/rules.yaml` を読み込んで使う）
  - `test_fg_bands`：`[(9,-3),(10,-2),(17,-1),(20,-1),(21,0),(69,0),(70,2),(80,2),(81,3)]`
  - `test_cpi_bands`：`[(2.9,0),(3.0,-1),(3.4,-1),(3.5,1)]`
  - `test_us10y_streak_bands`：`[(0,0),(1,1),(30,1),(31,0),(89,0),(90,-1)]`
  - `test_sox_combo`：(31.7, 99日)→-1、(31.7, 30日)→-3、(20, 10日)→0、(3, fg 75)→2、(3, fg missing)→0
  - `test_points_to_ratio`：`[(-7,0),(-6,0),(-5,10),(-3,10),(-2,20),(1,20),(2,35),(4,50),(7,70),(8,90)]`
  - `test_hysteresis_up_immediate`：`(50, 35, None) -> (50, None)`
  - `test_hysteresis_down_needs_two`：`(20, 50, None) -> (50, 20)`、続けて `(35, 50, 20) -> (35, None)`
  - `test_hysteresis_down_interrupted`：`(20, 50, None) -> (50, 20)`、続けて `(50, 50, 20) -> (50, None)`
  - `test_hold_semi_four_missing`：半導体の7指標中4つが missing → `on_hold True`、3つなら False
  - `test_hold_keeps_previous_ratio`：保留時は前回の比率 35 のまま
  - `test_backfill_absent_manual_not_counted`：`topix_per` キーなしの日本分野で、missing が2つ（5指標中）なら保留にならない
  - `test_ratio_excl_manual`：`sox_per` が manual で -2 点のとき、`ratio_excl_manual` は -2 を除いた比率
- [ ] **Step 2: 実行して失敗を確認** — `python -m pytest tests/test_scoring.py -v` → FAIL
- [ ] **Step 3: 実装**
- [ ] **Step 4: 実行して成功を確認** — 12 passed
- [ ] **Step 5: コミット** — `git commit -m "feat: area scoring, hold rule and hysteresis"`

---

### Task 6: 銘柄判定と理由文

**Files:**
- Create: `src/dash/verdict.py`, `src/dash/reasons.py`
- Test: `tests/test_verdict.py`, `tests/test_reasons.py`

**Interfaces:**
- Consumes: `TickerConfig`, `AreaResult`, `Metric`, `indicators.drawdown_from_high`
- Produces: `ticker_verdict(t: TickerConfig, area_ratio: int, drop_pct: float | None, rules: dict) -> tuple[str, list[str]]` … （判定, 効いた補正の説明リスト）。`drop_pct is None` → `("データなし", [])`。手順：`verdict_table[area_ratio]` の normal/leveraged → 下落≥30 かつ 比率≤35 なら1段階強気寄り（`verdict_levels` で1つ左。左端で止める）→ `cautious_when_area_ratio_ge` があり比率がそれ以上なら1段階警戒寄り（1つ右）。通常銘柄が `全利確` にならないよう、通常銘柄は `利確 1/2` で止める
- Produces: `metric_phrase(m: Metric) -> str` … 例：`"SOX 高値比-31.7%（日柄99日）"`、stale なら末尾に `"（前回値 11/08）"`、manual なら `"（手入力 11/05）"`、overdue なら `"（手入力 11/05・要更新）"`
- Produces: `area_reason(result: AreaResult, metrics: dict[str, Metric]) -> str` … 点数の絶対値が大きい順に、0点でない指標を最大3つ `metric_phrase` でつなぎ、`／` で区切る。0点以外がなければ `"目立ったシグナルなし"`。保留なら先頭に `"判定保留（データ不足）："`
- Produces: `ticker_reason(t: TickerConfig, tr_drop: float | None, area: AreaResult, metrics: dict[str, Metric], adjustments: list[str]) -> str` … `"高値から-22.0%。" + 上位1〜2指標のフレーズ + "。" + t.note + 補正説明` の1〜2文

`sox_combo` のフレーズは `sox_drop` の Metric を使う。`gdp_spread` は `"名目GDP−10年債 +1.15%"` の形。

- [ ] **Step 1: 失敗するテストを書く**
  - `test_verdict_table`：通常銘柄で 0→買い増し、20→保有、35→保有、50→利確 1/4、70→利確 1/3、90→利確 1/2。SOXL で 35→利確 1/3、90→全利確
  - `test_verdict_deep_drop_bullish_shift`：通常銘柄、下落 32%、比率 20 → 買い増し
  - `test_verdict_deep_drop_no_shift_when_cautious`：下落 32%、比率 50 → 利確 1/4
  - `test_verdict_kioxia_cautious_shift`：285A.T、比率 35、下落 10% → 利確 1/4
  - `test_verdict_no_data`：`drop_pct=None` → データなし
  - `test_metric_phrase_stale_and_manual`
  - `test_area_reason_top3_by_abs_points`：内訳 `[fg -1, sox_combo -3, capex 0, cpi +1, sox_per -2]` → sox → sox_per → (fg か cpi) の順で3つ
  - `test_area_reason_hold_prefix`
- [ ] **Step 2: 実行して失敗を確認** — `python -m pytest tests/test_verdict.py tests/test_reasons.py -v` → FAIL
- [ ] **Step 3: 実装**
- [ ] **Step 4: 実行して成功を確認** — 8 passed
- [ ] **Step 5: コミット** — `git commit -m "feat: ticker verdicts and reason text"`

---

### Task 7: 履歴と評価日の判定

**Files:**
- Create: `src/dash/history.py`
- Test: `tests/test_history.py`

**Interfaces:**
- 履歴ファイルの形（`docs/data/history.json`）：
  ```json
  {"entries": [{"date": "2026-11-12", "backfill": false,
    "market_dates": {"us": "2026-11-11", "jp": "2026-11-12"},
    "areas": {"us": {"ratio": 25, "raw_ratio": 25, "ratio_excl_manual": 25, "points": 2, "on_hold": false, "pending_down": null}},
    "verdicts": {"SOXL": "利確 1/3"}}]}
  ```
- Produces: `load_history(path: Path) -> list[dict]`（ファイルがない・壊れている → `[]`。壊れていたら `logging.error`）
- Produces: `save_history(path: Path, entries: list[dict]) -> None`（日付で昇順。同じ日付は後から来たもので置き換える）
- Produces: `is_new_evaluation(market_dates: dict[str, str], last_entry: dict | None) -> bool` … `last_entry is None` → True。`us` か `jp` のどちらかの日付が前回と違えば True
- Produces: `entry_near(entries: list[dict], target: date) -> dict | None` … `target` 以前で最も近い日付のエントリ（なければ None）

- [ ] **Step 1: 失敗するテストを書く**
  - `test_load_history_missing_file_empty`、`test_load_history_corrupt_empty`
  - `test_save_history_replaces_same_date`
  - `test_is_new_evaluation_weekend_false`：前回 `{us: 11-07, jp: 11-07}`、今回も同じ → False
  - `test_is_new_evaluation_one_market_holiday_true`：us だけ進んだ → True
  - `test_entry_near_week_ago`：11/03, 11/05, 11/10 があり target=11/05 → 11/05。target=11/04 → 11/03
- [ ] **Step 2: 実行して失敗を確認** — `python -m pytest tests/test_history.py -v` → FAIL
- [ ] **Step 3: 実装**
- [ ] **Step 4: 実行して成功を確認** — 6 passed
- [ ] **Step 5: コミット** — `git commit -m "feat: history storage and evaluation-day detection"`

---

### Task 8: 通知（差分作成と Gmail 送信）

**Files:**
- Create: `src/dash/notify.py`
- Test: `tests/test_notify.py`

**Interfaces:**
- Consumes: `latest.json` の dict（Task 9 の形）
- Produces: `build_notifications(prev: dict | None, curr: dict, page_url: str) -> list[tuple[str, str]]` … （件名, 本文）のリスト。`prev is None` なら `[]`。
  - **判定変更**：`curr["evaluated"]` が True のときだけ。分野の `ratio` が前回と違う、または銘柄の `verdict` が違う（ただし保留中の分野とその銘柄は比較しない）。件名 `【判定変更】半導体 30%→40% / SOXL 保有→利確 1/3`（変化を `/` で並べ、件名が長ければ先頭2件＋`ほかN件`）。本文に変化した分野・銘柄の理由文とページ URL
  - **取得状態の変化**：指標の `status` が missing 以外→missing になったもの、missing→missing 以外に戻ったもの。分野の `on_hold` が変わったもの。件名 `【取得失敗】Fear & Greed, CPI` / `【回復】Fear & Greed`。evaluated が False の実行でも出す
  - 同じ状態が続いている間は何も出さない
- Produces: `send_gmail(subject: str, body: str, env: Mapping[str, str]) -> None` … `smtplib.SMTP_SSL("smtp.gmail.com", 465)`、`env["GMAIL_ADDRESS"]` / `env["GMAIL_APP_PASSWORD"]` でログインし、`env["NOTIFY_TO"]` へ送る。どれかが未設定なら `logging.warning` して送らない（例外にしない）

- [ ] **Step 1: 失敗するテストを書く**
  - `test_no_prev_no_notifications`
  - `test_ratio_and_verdict_change_subject`：semi 30→40、SOXL 保有→利確 1/3 → 件名が `【判定変更】半導体 30%→40% / SOXL 保有→利確 1/3`
  - `test_not_evaluated_skips_verdict_changes`：evaluated=False → 判定変更は出ない
  - `test_fetch_failure_once`：fg が live→missing で1件。次の実行で missing→missing なら0件
  - `test_recovery_notified`：missing→live で `【回復】` 1件
  - `test_on_hold_area_not_compared`：保留中の分野の比率差は判定変更に入らない
  - `test_send_gmail_missing_env_does_not_raise`
- [ ] **Step 2: 実行して失敗を確認** — `python -m pytest tests/test_notify.py -v` → FAIL
- [ ] **Step 3: 実装**
- [ ] **Step 4: 実行して成功を確認** — 7 passed
- [ ] **Step 5: コミット** — `git commit -m "feat: change-based gmail notifications"`

---

### Task 9: パイプラインと CLI（daily / backfill）

**Files:**
- Create: `src/dash/pipeline.py`, `src/dash/__main__.py`
- Test: `tests/test_pipeline.py`（取得関数を差し替えた合成データで通しで動かす）

**Interfaces:**
- Consumes: Task 1〜8 のすべて
- `latest.json` の形（ページと通知が読む）：
  ```json
  {"generated_at": "2026-11-12T06:31:05+09:00", "evaluated": true,
   "market_dates": {"us": "2026-11-11", "jp": "2026-11-12"},
   "metrics": {"fg": {"label": "Fear & Greed", "value": 17, "unit": "", "status": "live", "as_of": "2026-11-11", "stale_evals": 0, "extra": {}}},
   "areas": {"semi": {"ratio": 40, "prev_ratio": 35, "raw_ratio": 40, "ratio_excl_manual": 50, "points": 4, "on_hold": false, "pending_down": null,
             "contributions": [{"key": "sox_combo", "points": -1}], "missing": [], "reason": "..."}},
   "tickers": [{"symbol": "SOXL", "name": "SOXL", "area": "semi", "price": 31.2, "drop_pct": 45.1, "verdict": "利確 1/3", "prev_verdict": "保有", "reason": "..."}],
   "page_url": "..."}
  ```
- Produces: `Fetchers` データクラス（`closes`, `fred`, `fear_greed` の3つの呼び出し可能オブジェクト）と `default_fetchers(env) -> Fetchers`（`FRED_API_KEY` がなければ FRED の取得関数は常に例外を出す）
- Produces: `collect_raw(fetchers: Fetchers, symbols: list[str]) -> RawData` … 取得元ごとに try/except し、失敗理由を `errors` に入れる
- Produces: `run_daily(root: Path, fetchers: Fetchers, now: datetime, send: Callable[[str, str], None] | None) -> dict` … 手順：
  1. 設定を読む → `collect_raw` → `compute_metrics(asof=None, manual=load_manual(...))` → 前回の `latest.json` の metrics で `carry_forward`
  2. `market_dates` = `^GSPC` と `^N225` の最終日付。`is_new_evaluation(market_dates, 履歴の最後)` を判定
  3. 評価日なら、各分野を `evaluate_area(prev=履歴の最後の分野)` で計算し、銘柄判定・理由文を作り、履歴に追記する。評価日でなければ、分野と銘柄は前回の `latest.json` の値を引き継ぎ、指標と `generated_at` だけ更新する
  4. `prev_ratio` / `prev_verdict` は直前の評価日の値（履歴の最後から2番目ではなく、追記前の最後）
  5. `docs/data/latest.json` を書く → `build_notifications(前回latest, 今回latest, page_url)` を `send` に渡す（`send is None` なら送らない）
  6. `page_url` は環境変数 `PAGE_URL`（なければ空文字）
- Produces: `run_backfill(root: Path, fetchers: Fetchers, today: date, days: int = 365) -> int` … 1回だけ取得し、`^GSPC` と `^N225` の取引日の和集合（過去 `days` 日）を古い順に回す。各日について `compute_metrics(asof=d, manual=None)`、`evaluate_area(apply_hold=False, prev=前の日)`、銘柄判定をして `backfill: true` のエントリを作る（理由文は作らない）。既存の履歴があれば、`backfill: false` のエントリは上書きしない。通知はしない。作ったエントリ数を返す
- Produces: `__main__.py` … `python -m dash daily` / `python -m dash backfill [--days 365]`。root はカレントディレクトリ。daily では `send = lambda s, b: send_gmail(s, b, os.environ)`

- [ ] **Step 1: 失敗するテストを書く**（tmp_path に config と docs/data を作る）
  - `test_first_run_writes_latest_no_notifications`：履歴なし → latest.json と history.json（1件）ができ、`send` は呼ばれない
  - `test_weekend_run_not_evaluated`：同じ市場日付で2回目 → `evaluated False`、履歴は1件のまま、`generated_at` は更新されている
  - `test_cnn_blocked_fg_missing_and_single_failure_mail`：1回目 fg live、2回目（新しい日付）で fear_greed が例外 → fg が stale（値は前回）。stale の上限を超えるまで続け、missing になった実行でだけ `【取得失敗】` が1回送られる
  - `test_manual_yaml_broken_continues`：manual.yaml を壊しても実行が終わり、`topix_per.status == "missing"`
  - `test_backfill_creates_entries_without_hold`：合成データ 30 営業日 → 30 件、すべて `backfill: true`、どの分野も `on_hold False`
  - `test_backfill_keeps_daily_entries`：既存の `backfill: false` の日付は上書きされない
- [ ] **Step 2: 実行して失敗を確認** — `python -m pytest tests/test_pipeline.py -v` → FAIL
- [ ] **Step 3: 実装**
- [ ] **Step 4: 全テストを実行** — `python -m pytest -q` → all passed
- [ ] **Step 5: 実データで試す（テストではない）** — `FRED_API_KEY` なしで `python -m dash backfill` → `python -m dash daily`。`docs/data/latest.json` で、Yahoo 由来の指標が live、FRED 由来が missing、手入力が manual になっていることを確認。過去1年の各分野の比率の分布（0/10/20/35/50/70/90 の日数）を数えてコミットメッセージに書く
- [ ] **Step 6: コミット** — `git commit -m "feat: daily and backfill pipeline with CLI"`（`docs/data/*.json` はこの時点ではコミットしない。`.gitignore` には入れず、Task 11 の Actions が書く）

---

### Task 10: スマホ向けページ

**Files:**
- Create: `docs/index.html`, `docs/app.js`, `docs/style.css`, `docs/robots.txt`, `docs/manifest.webmanifest`, `docs/icon.svg`
- Create: `docs/data/sample-latest.json`, `docs/data/sample-history.json`（表示確認用。`?sample=1` のときだけ読む）
- Test: ブラウザで手動確認（下記 Step）。ロジックは持たないので単体テストは書かない

**Interfaces:**
- Consumes: Task 9 の `latest.json` と `history.json`
- 画面（仕様9、モックアップ E 案）：
  1. ヘッダー：`最終更新 11/12 06:31`。`now - generated_at > 36時間` なら赤い帯「更新が止まっています（最終 11/10 06:31）」
  2. タブ：`🇺🇸 米国 25%` `🇯🇵 日本 15%` `🔬 半導体 40%`。前回から比率が変わったタブには小さな点。保留中の分野はグレー
  3. 選択中の分野：大きな比率、前回比（`▲10` / `▼5` / `±0`）、折れ線グラフ（Chart.js の line、縦軸 0〜90、`普段 20%` の点線、期間ボタン 1か月／3か月／1年、`backfill: true` の区間は薄い色の点線）、今日（白）・前日（グレー `#aab6cc`）・1週前（紫 `#b58cff`）・1か月前（青 `#7aa2ff`）の点と凡例（`entry_near` と同じ規則で JS 側でも探す）、理由文、`missing` / stale / 期限切れ手入力の注記
  4. 銘柄リスト：名前、判定バッジ（買い増し＝緑、保有＝グレー、利確・全利確＝オレンジ、データなし＝グレーの点線枠）、価格と高値比、判定が変わっていれば `前日 保有 → 今日 利確 1/3`、理由文の全文
  5. 「指標の詳細」（`<details>`）：各指標の値、状態、観測日、点数
  6. フッター：投資助言ではない旨
- 最後に選んだタブは `localStorage` の `md.tab` に保存（try/catch で囲む）
- 色はモックアップのダーク配色。幅 360px で横スクロールが出ないこと
- `fetch('data/latest.json', {cache: 'no-store'})`。読めなければ「データを読み込めませんでした」と表示

- [ ] **Step 1: sample JSON を作る** — `python -m dash daily` の出力（Task 9 Step 5）をコピーし、半導体の SOXL が `prev_verdict` 付きで変化している状態にする
- [ ] **Step 2: ページを実装**
- [ ] **Step 3: ブラウザで確認** — `.claude/launch.json` に `python -m http.server 8000 --directory docs` を登録し、preview で `http://localhost:8000/?sample=1` を開く。375×812 で確認すること：3タブの切り替え、グラフの期間切り替え、4色の点と凡例、判定変化の表示、`<details>` の開閉、コンソールエラーなし
- [ ] **Step 4: 古いデータの警告を確認** — sample の `generated_at` を3日前にして赤帯が出ること
- [ ] **Step 5: スクリーンショットを撮り、コミット** — `git commit -m "feat: mobile dashboard page"`

---

### Task 11: GitHub Actions と README

**Files:**
- Create: `.github/workflows/daily.yml`, `.github/workflows/test.yml`, `README.md`

**Interfaces:**
- `daily.yml`：`on: schedule: - cron: '30 21 * * *'` と `workflow_dispatch`（入力 `mode`: `daily` | `backfill`、既定 `daily`）。`permissions: contents: write`。`concurrency: daily`。Python 3.12、`pip install -r requirements.txt`、`pip install -e .`、`python -m dash ${{ inputs.mode || 'daily' }}`、環境変数 `FRED_API_KEY` `GMAIL_ADDRESS` `GMAIL_APP_PASSWORD` `NOTIFY_TO`（Secrets）、`PAGE_URL`（`https://${{ github.repository_owner }}.github.io/${{ github.event.repository.name }}/`）。最後に `docs/data/` に差分があれば `github-actions[bot]` として commit & push（`git pull --rebase` してから push）
- `test.yml`：push / pull_request で `python -m pytest -q`
- `README.md`（日本語）：仕様12の手順1〜6をそのまま手順化する。加えて、初回は Actions の画面で `mode=backfill` を手動実行し、その後 `daily` を手動実行すること。Gmail のアプリパスワードの作り方へのリンク（https://support.google.com/accounts/answer/185833）。FRED API キーの取得先（https://fredaccount.stlouisfed.org/apikeys）。`config/rules.yaml` と `config/manual.yaml` の編集方法

- [ ] **Step 1: ワークフローを書く**
- [ ] **Step 2: 構文を確認** — `python -c "import yaml,sys; [yaml.safe_load(open(f)) for f in sys.argv[1:]]" .github/workflows/daily.yml .github/workflows/test.yml` がエラーなく終わる
- [ ] **Step 3: README を書く**
- [ ] **Step 4: コミット** — `git commit -m "ci: daily workflow, tests workflow and setup guide"`

---

### Task 12: 公開と初回実行（ユーザーと一緒に行う）

ここからはユーザーのアカウント操作を含む。認証情報の入力はユーザーが行い、実装者は代行しない。

- [ ] **Step 1: ユーザーに確認してから** GitHub に公開リポジトリ `market-dashboard` を作り、push する（`gh repo create` はユーザーの了承を得てから）
- [ ] **Step 2: ユーザーが Secrets を登録** — `FRED_API_KEY`、`GMAIL_ADDRESS`、`GMAIL_APP_PASSWORD`、`NOTIFY_TO`
- [ ] **Step 3: ユーザーが Pages を有効化** — main ブランチの `/docs`
- [ ] **Step 4: Actions で `backfill` を手動実行し、続けて `daily` を手動実行** — 両方成功すること。`latest.json` で FRED 由来の指標が live になっていること、CNN の結果（live か missing か）を確認する
- [ ] **Step 5: スマホで開いて確認** — ユーザーの端末で表示とホーム画面への追加を確認してもらう
- [ ] **Step 6: 点数表の調整会** — 過去1年の比率の推移をユーザーと見て、`config/rules.yaml` を必要に応じて調整する（仕様14）
