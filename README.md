<p align="center">
  <img src="assets/focus-room-icon-512.png" width="160" alt="Focus Room のアイコン">
</p>

<h1 align="center">Focus Room</h1>

<p align="center">
  勉強用ボイスチャンネル（VC）での集中をサポートする Discord Bot<br>
  <sub>Python · discord.py · SQLite · yt-dlp</sub>
</p>

---

Focus Room は、みんなで勉強する Discord サーバー向けの Bot です。VC にいる時間を自動で記録し、ランキングや目標で続ける気持ちを支えます。ポモドーロタイマーと集中用 BGM もそろっています。VC に入るだけで、ポモドーロと BGM を自動で始めることもできます。

## 主な機能

- 🚀 **自動開始**：指定した VC に入るか `/start` を実行すると、ポモドーロと BGM を一緒に開始します
- 📊 **勉強時間の自動記録**：VC にいる時間を記録し、今日・今週・累計の時間と順位を表示します。マイクやカメラの状態は問いません
- 🏆 **ランキング**：今日・今週・昨日・先週のランキングを表示し、毎日決まった時刻に自動投稿もできます
- 🍅 **ポモドーロ**：VC ごとに作業と休憩を切り替え、VC のチャットでメンションして知らせます
- 🎯 **目標とリマインド**：1日の目標を達成すると通知し、指定した時刻に DM でリマインドします
- 🎵 **集中用 BGM**：YouTube Music・YouTube の曲、プレイリスト、アルバム、ライブ配信を再生します。Spotify の URL を渡すと、同じ曲を探して再生します
- 🧹 **チャットの自動削除**：チャンネル（VC のチャットも可）のメッセージを、指定した時間がたったら消します
- ⚙️ **設定パネル**：`/setup` から、メニューとボタンで設定をまとめて変更できます

## コマンド

| コマンド | 内容 |
|---|---|
| `/setup` | 設定パネル。自動開始、記録する VC、ポモドーロの既定時間、通知・ランキング投稿・チャットの自動削除、音楽の既定値、自分の目標とリマインドを設定します。パネルは本人にだけ表示され、サーバー全体の項目は「サーバー管理」権限が必要です |
| `/start` / `/stop` | 参加中の VC で、集中セッション（ポモドーロと BGM）を開始・終了します |
| `/stats [member]` | 今日・今週・累計の勉強時間、順位、目標の進み具合を表示します |
| `/ranking [period]` | ランキング（今日／今週／昨日／先週）の上位10人を表示します |
| `/pomodoro start` `status` `pause` `resume` `stop` | ポモドーロの開始、残り時間の確認、一時停止、再開、終了。開始時に時間を省略すると、サーバーの既定値を使います |
| `/goal set` `show` `clear` | 1日の目標時間を設定・表示・削除します |
| `/remind set` `show` `clear` | 毎日指定した時刻（例：`21:00`）に DM でリマインドします |
| `/music play query [source]` | 曲名か URL で再生します。プレイリストは最大50曲を一括で追加し、キューは最大100曲です |
| `/music recommend [theme]` | 勉強向けのおすすめ曲を選んで再生します |
| `/music pause` `resume` `skip` `stop` `loop` `shuffle` `volume` `queue` | 再生の操作をします。`/music` の返信は本人にだけ表示されます |
| `/studyconfig …` | 記録する VC、通知先、ランキング投稿、チャットの自動削除を個別に設定します（「サーバー管理」権限が必要） |

<details>
<summary>動作の詳細</summary>

- 記録する VC を指定していない場合は、AFK チャンネル以外のすべての VC とステージを記録します。Bot のアカウントは記録しません。
- 日付と週の区切りは `BOT_TIMEZONE`（初期値は日本時間）に従います。週は月曜に始まり、日をまたぐセッションは日ごとに分けて集計します。
- Bot が止まっていた間の記録は、最後に生存を確認した時刻（毎分更新）で打ち切ります。再起動すると、その時点で VC にいる人の記録を再開します。
- 自動開始は、すでにポモドーロや BGM が動いているときは何もしません。BGM は全曲ループで流し続けます。
- VC が無人になると、ポモドーロは終了し、Bot は1〜2分で退出します。ポモドーロはメモリ上で管理しているため、再起動すると止まります。
- リマインドは、その時刻に勉強中の人と、その日の目標を達成済みの人には送りません。DM を受け取れない人には、通知チャンネルでメンションします。
- チャットの自動削除は10分ごとに確認し、ピン留めしたメッセージは残します。

</details>

## セットアップ

### 1. Bot を作成して招待する

1. [Discord Developer Portal](https://discord.com/developers/applications) でアプリケーションを作成します。
2. 「Bot」タブでトークンを発行します。トークンは `.env` にだけ書き、Git に含めないでください。
3. **Privileged Gateway Intents は不要**です。すべてオフのままで動きます。
4. 「OAuth2 → URL Generator」で、scopes に `bot` と `applications.commands` を選び、次の権限にチェックを入れて招待します。

   | 権限 | 用途 |
   |---|---|
   | View Channels / Send Messages / Embed Links | 通知、記録とランキングの表示 |
   | Manage Messages / Read Message History | チャットの自動削除 |
   | Connect / Speak | BGM の再生 |

   permissions の整数値は `3238912` です。招待 URL の例（`CLIENT_ID` を置き換えてください）：

   ```
   https://discord.com/oauth2/authorize?client_id=CLIENT_ID&permissions=3238912&scope=bot%20applications.commands&integration_type=0
   ```

アイコンと説明文の例は [assets/profile.md](assets/profile.md) にあります。

### 2. 環境変数

`.env.example` を `.env` にコピーして、値を入れます。

| 変数 | 必須 | 説明 |
|---|---|---|
| `DISCORD_TOKEN` | ○ | Bot のトークン |
| `DEV_GUILD_ID` | | 開発用サーバーの ID。指定すると、そのサーバーにコマンドがすぐ反映されます（未指定の場合はグローバルに登録され、反映に時間がかかることがあります） |
| `DATABASE_PATH` | | SQLite の保存先（初期値 `data/study.db`） |
| `BOT_TIMEZONE` | | 集計に使うタイムゾーン（初期値 `Asia/Tokyo`） |
| `FFMPEG_PATH` | | FFmpeg の実行ファイル（初期値 `ffmpeg`） |
| `MUSIC_DEFAULT_VOLUME` | | BGM の初期音量（%、初期値 15） |
| `LOG_DEBUG` | | 詳しいログを出すロガー名（カンマ区切り。例：`discord.voice_state,discord.player`） |

### 3-a. Docker で動かす（おすすめ）

FFmpeg 入りのイメージを作って、常駐させます。

```sh
docker compose up -d --build
docker compose logs -f
```

記録は `./data/study.db` に保存されます。`compose.yml` の `user: "1000:1000"` は、`./data` を持つホスト側ユーザーの uid と gid に合わせてください。

### 3-b. ローカルで動かす

Python 3.12 以上と、BGM を使う場合は FFmpeg が必要です。

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt      # Windows: .venv\Scripts\pip
.venv/bin/python -m study_bot                  # Windows: .venv\Scripts\python
```

systemd で動かす場合の設定例は [study-focus-bot.service](study-focus-bot.service) にあります。

### テスト

```sh
pip install pytest
python -m pytest -q
```

テストは Discord に接続せずに、集計、日付の区切り、入退室の判定、ポモドーロ、自動開始、設定パネル、コマンド登録を確認します。

## 構成

```
study_bot/
  __main__.py    起動処理（python -m study_bot）
  bot.py         Discord クライアント、入退室イベント、自動開始、定期処理
  commands.py    スラッシュコマンド
  setup_view.py  /setup の設定パネル（ボタン・メニュー・フォーム）
  db.py          SQLite（セッション、設定、目標、リマインド、自動削除）
  tracking.py    入退室からセッションを開始・終了する判定
  pomodoro.py    ポモドーロの状態遷移
  music.py       yt-dlp と FFmpeg による再生キュー
  timeutil.py    日付・週の区切りと時刻の表記
  formatting.py  ランキングと目標の表示文字列
assets/          アイコンとプロフィール文
tools/           アイコン生成スクリプト（Pillow が必要）
tests/           pytest
```

## 注意

- **音声の E2EE（DAVE）**：Discord の音声にはエンドツーエンド暗号化への対応が必要なため、`davey` を 0.1 系に固定しています。davey 0.2.0 と discord.py 2.7.1 を組み合わせると、DAVE のセッションが準備完了にならず、暗号化されていない音声が送られて無音になります（Discord のデバッグ画面で「Decrypt Failures」だけが増えます）。discord.py を更新するときは、BGM が鳴ることを確かめてから固定を外してください。暗号化できていない場合は、ログに警告が出ます。
- Bot は聞き取りオフ（self-deaf）にせずに VC に入ります。受信した音声は処理しません。
- **YouTube の利用規約**は、公式プレイヤー以外での再生を制限しています。BGM 機能は、個人や小規模なサーバーで、自己責任のもとで使ってください。再生できなくなった場合は、yt-dlp を更新してください（Docker の場合は `docker compose build --no-cache`）。
- 同じトークンの Bot を複数の場所で同時に動かすと、コマンドに二重で応答します。
