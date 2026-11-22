# Focus Room のプロフィール

Discord Developer Portal の各欄に貼り付ける内容です。

## アイコン（General Information → App Icon、Bot → Icon）

`focus-room-icon-1024.png` をアップロードする。Discordでは円形に切り抜かれる（見え方は `focus-room-icon-preview-circle.png`）。
デザインを変えるときは `tools/make_icon.py` を編集して再生成する。

## Description（General Information → Description、最大400文字）

Botのプロフィールの「自己紹介」に表示される。

```
VCに入るだけで、ポモドーロと集中用BGMがスタートする勉強用Botです。
🚀 VC入室・/start で自動開始
📊 勉強時間を自動記録 → /stats /ranking
🍅 ポモドーロタイマー → /pomodoro
🎯 目標とリマインド → /goal /remind
🎵 YouTube MusicのBGM → /music play
⚙️ 設定はまとめて → /setup
```

## Tags（任意、最大5つ）

```
study, pomodoro, productivity, music, voice
```
