<p align="center">
  <img src="assets/banner.png" alt="Focus Room — 勉強用VCの集中をサポートする Discord Bot" width="100%">
</p>

<p align="center">
  <a href="https://discord.com/oauth2/authorize?client_id=1573705154710999161&permissions=3238912&scope=bot%20applications.commands&integration_type=0"><img src="https://img.shields.io/badge/Discord-サーバーに追加-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="サーバーに追加"></a>
  <!-- SUPPORT_SERVER_BADGE -->
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white" alt="Python 3.12">
  <img src="https://img.shields.io/badge/discord.py-2.7-5865F2?logo=discord&logoColor=white" alt="discord.py 2.7">
  <img src="https://img.shields.io/badge/SQLite-003B57?logo=sqlite&logoColor=white" alt="SQLite">
  <img src="https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white" alt="Docker">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/rattokun-1/focus-room-bot?color=FFB852" alt="MIT License"></a>
</p>

<p align="center">
  <b>VCに入るだけで、ポモドーロとBGMがスタート。</b><br>
  勉強時間は自動で記録され、ランキングと目標で「続ける」を後押しします。
</p>

---

## ✨ できること

<table>
  <tr>
    <td width="50%" valign="top">
      <h3>🚀 入室で自動スタート</h3>
      決めたVCに入るか <code>/start</code> を実行するだけで、ポモドーロと集中用BGMが同時に始まります。<code>/stop</code> でまとめて終了します。
    </td>
    <td width="50%" valign="top">
      <h3>📊 勉強時間の自動記録</h3>
      VCにいる時間を自動で記録します。<code>/stats</code> で今日・今週・累計の時間と順位がわかります。マイクやカメラの状態は問いません。
    </td>
  </tr>
  <tr>
    <td valign="top">
      <h3>🍅 ポモドーロ</h3>
      VCごとに作業と休憩を切り替え、VCのチャットでメンションして知らせます。プリセットから時間を選べます。
    </td>
    <td valign="top">
      <h3>🎵 集中用BGM</h3>
      YouTube Music・YouTube の曲、プレイリスト、アルバム、ライブ配信を再生します。Spotify のURLにも対応しています。
    </td>
  </tr>
  <tr>
    <td valign="top">
      <h3>🏆 ランキングと目標</h3>
      日・週のランキングを毎朝自動で投稿します。1日の目標を達成すると通知し、決めた時刻にDMでリマインドします。
    </td>
    <td valign="top">
      <h3>⚙️ かんたん設定</h3>
      <code>/setup</code> のパネルから、メニューとボタンですべての設定を変更できます。チャットの自動削除も設定できます。
    </td>
  </tr>
</table>

## 🏁 はじめかた

1. 上の **「サーバーに追加」** ボタンから、Focus Room をサーバーに招待します
2. `/setup` を開き、「🚀 自動開始」で集中用のVCと流す音楽を選びます
3. そのVCに入れば、ポモドーロとBGMが始まります 🎧

## 📖 コマンド

| コマンド | 内容 |
|---|---|
| `/setup` | 設定パネル（本人にだけ表示）。サーバー全体の項目は「サーバー管理」権限が必要です |
| `/start` ・ `/stop` | 参加中のVCで、ポモドーロとBGMを開始・終了します |
| `/stats [member]` | 今日・今週・累計の勉強時間、順位、目標の進み具合を表示します |
| `/ranking [period]` | 今日／今週／昨日／先週のランキング（上位10人）を表示します |
| `/pomodoro start` `status` `pause` `resume` `stop` | ポモドーロを操作します。時間を省略すると、サーバーの既定値を使います |
| `/goal set` `show` `clear` | 1日の目標時間を設定・表示・削除します |
| `/remind set` `show` `clear` | 毎日決めた時刻（例：`21:00`）にDMでリマインドします |
| `/music play` `recommend` | 曲名・URL・プレイリストで再生します。`recommend` は勉強向けのおすすめを選びます |
| `/music pause` `resume` `skip` `stop` `loop` `shuffle` `volume` `queue` | 再生を操作します。返信は本人にだけ表示されます |
| `/studyconfig …` | 記録するVC、通知先、ランキング投稿、チャットの自動削除を個別に設定します |

<details>
<summary><b>動作の詳細</b></summary>

- 記録するVCを指定していない場合は、AFKチャンネル以外のすべてのVCとステージを記録します。Botのアカウントは記録しません。
- 日付と週の区切りは `BOT_TIMEZONE`（初期値は日本時間）に従います。週は月曜に始まり、日をまたぐ分は日ごとに分けて集計します。
- Botが止まっていた間の記録は、最後に生存を確認した時刻（毎分更新）で打ち切ります。
- 自動開始は、すでにポモドーロやBGMが動いているときは何もしません。BGMは全曲ループで流し続けます。
- VCが無人になると、ポモドーロは終了し、Botは1〜2分で退出します。ポモドーロはメモリ上で管理しているため、再起動すると止まります。
- リマインドは、その時刻に勉強中の人と、その日の目標を達成済みの人には送りません。
- チャットの自動削除は10分ごとに確認し、ピン留めしたメッセージは残します。

</details>

---

## 🛠 自分でホストする

<details>
<summary><b>1. Botを作成して招待する</b></summary>

1. [Discord Developer Portal](https://discord.com/developers/applications) でアプリケーションを作成し、「Bot」タブでトークンを発行します（トークンは `.env` にだけ書き、Gitに含めないでください）。
2. **Privileged Gateway Intents は不要**です。すべてオフのままで動きます。
3. scopes に `bot` と `applications.commands` を選び、次の権限で招待します（整数値 `3238912`）。

   | 権限 | 用途 |
   |---|---|
   | View Channels / Send Messages / Embed Links | 通知、記録とランキングの表示 |
   | Manage Messages / Read Message History | チャットの自動削除 |
   | Connect / Speak | BGMの再生 |

アイコンと説明文の例は [assets/profile.md](assets/profile.md) にあります。

</details>

<details>
<summary><b>2. 環境変数</b></summary>

`.env.example` を `.env` にコピーして、値を入れます。

| 変数 | 必須 | 説明 |
|---|---|---|
| `DISCORD_TOKEN` | ○ | Botのトークン |
| `DEV_GUILD_ID` | | 開発用サーバーのID。指定すると、そのサーバーだけにコマンドがすぐ反映されます（未指定なら全サーバーに登録） |
| `DATABASE_PATH` | | SQLiteの保存先（初期値 `data/study.db`） |
| `BOT_TIMEZONE` | | 集計に使うタイムゾーン（初期値 `Asia/Tokyo`） |
| `FFMPEG_PATH` | | FFmpegの実行ファイル（初期値 `ffmpeg`） |
| `MUSIC_DEFAULT_VOLUME` | | BGMの初期音量（%、初期値 15） |
| `LOG_DEBUG` | | 詳しいログを出すロガー名（カンマ区切り） |

</details>

<details>
<summary><b>3. 起動する（Docker / ローカル）</b></summary>

**Docker（おすすめ）**：FFmpeg入りのイメージを作って常駐させます。記録は `./data/study.db` に保存されます。`compose.yml` の `user: "1000:1000"` は、`./data` を持つユーザーの uid と gid に合わせてください。

```sh
docker compose up -d --build
docker compose logs -f
```

**ローカル**：Python 3.12以上と、BGMを使う場合はFFmpegが必要です。

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt      # Windows: .venv\Scripts\pip
.venv/bin/python -m study_bot                  # Windows: .venv\Scripts\python
```

systemdで動かす場合の設定例は [study-focus-bot.service](study-focus-bot.service) にあります。

</details>

<details>
<summary><b>4. テストと構成</b></summary>

```sh
pip install pytest
python -m pytest -q
```

テストはDiscordに接続せずに、集計、日付の区切り、入退室の判定、ポモドーロ、自動開始、設定パネル、コマンド登録を確認します。

```
study_bot/
  __main__.py    起動処理（python -m study_bot）
  bot.py         Discordクライアント、入退室イベント、自動開始、定期処理
  commands.py    スラッシュコマンド
  setup_view.py  /setup の設定パネル
  db.py          SQLite（セッション、設定、目標、リマインド、自動削除）
  tracking.py    入退室からセッションを開始・終了する判定
  pomodoro.py    ポモドーロの状態遷移
  music.py       yt-dlp と FFmpeg による再生キュー
  timeutil.py    日付・週の区切りと時刻の表記
  formatting.py  ランキングと目標の表示文字列
assets/          アイコン、バナー、プロフィール文
tools/           アイコンとバナーの生成スクリプト（Pillowが必要）
tests/           pytest
```

</details>

## ⚠️ 注意

- **音声のE2EE（DAVE）**：`davey` を 0.1 系に固定しています。davey 0.2.0 と discord.py 2.7.1 の組み合わせでは、暗号化されていない音声が送られて無音になります（Discordのデバッグ画面で「Decrypt Failures」だけが増えます）。discord.py を更新するときは、BGMが鳴ることを確かめてから固定を外してください。
- Botは聞き取りオフ（self-deaf）にせずにVCに入りますが、受信した音声は処理も保存もしません。
- **YouTubeの利用規約**は、公式プレイヤー以外での再生を制限しています。BGM機能は自己責任でご利用ください。再生できなくなった場合は、yt-dlp を更新してください。
- 同じトークンのBotを複数の場所で同時に動かすと、コマンドに二重で応答します。

## 📄 ライセンスとポリシー

- [MIT License](LICENSE)
- [プライバシーポリシー](PRIVACY.md) ・ [利用規約](TERMS.md)
