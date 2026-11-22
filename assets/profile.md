# Focus Room のプロフィール

Discord Developer Portal の各欄に貼り付ける内容です。

## アイコン（General Information → App Icon、Bot → Icon）

`focus-room-icon-1024.png` をアップロードする。Discordでは円形に切り抜かれる（見え方は `focus-room-icon-preview-circle.png`）。
デザインを変えるときは `tools/make_icon.py` を編集して再生成する。

## Description（General Information → Description、最大400文字）

Botのプロフィールの「自己紹介」に表示される。

```
勉強用VCの集中をサポートするBotです。
📊 VCにいる時間を自動で記録 → /stats /ranking
🍅 VCごとのポモドーロタイマー → /pomodoro start
🎯 1日の目標とリマインド → /goal /remind
🎵 YouTube Musicから集中用BGMを再生 → /music play
⚙️ 管理者向け設定 → /studyconfig
```

## Tags（任意、最大5つ）

```
study, pomodoro, productivity, music, voice
```
