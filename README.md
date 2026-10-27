<div align="center">

<img src="assets/github-project-banner.svg" alt="REDLAIN Draw Engine 4.0" width="100%"/>

<br/>

**Draw ideas. Automate strokes. Experiment with AI.**

A desktop drawing toolkit built by REDLAIN for creative workflows and Roblox drawing experiences.

[![Download](https://img.shields.io/badge/Download-Windows%20x64%20·%204.0.0-C84550?style=flat-square&logo=windows&logoColor=white)](https://github.com/REDLAIN228/Program/releases/latest)
[![Python](https://img.shields.io/badge/Python-3.11--3.13-3565A8?style=flat-square&logo=python&logoColor=white)](pyproject.toml)
[![Windows](https://img.shields.io/badge/Windows-10%20%2F%2011-2147E8?style=flat-square&logo=windows&logoColor=white)](START_HERE_RU.md)
[![Version](https://img.shields.io/badge/Version-4.0-183DCE?style=flat-square)](V4_GUIDE_RU.md)
[![Source](https://img.shields.io/badge/Source-Available-26396B?style=flat-square)](.)

**[⬇️ Download](https://github.com/REDLAIN228/Program/releases/latest)** · **[🚀 Quick start](#-quick-start)** · **[✨ What's new](#-whats-new-in-40)** · **[📚 Documentation](#-documentation)** · **[💬 Devlog](https://t.me/redlain_devlog)**

</div>

---

## ✦ About

**REDLAIN Draw Engine 4.0** (formerly Anime Drawer) turns images into planned drawing strokes and executes them through ordinary Windows mouse input in a Roblox drawing place. No injection, client modification or hidden game APIs.

Built as a personal project, developed iteratively, and shared openly.

> **Important:** A working local test canvas does not guarantee compatibility with every Roblox drawing place. Pick the matching game profile and run **TEST DRAW** before drawing. After updating from 3.0, run **Speed calibration** again. Live Roblox validation of 4.0 is still pending.

## ✨ What's new in 4.0

| | Change | Measured result |
|:--:|---|---|
| ⚡ | **Precise input timing on Windows** | Short waits used to be rounded up to the ~15.6 ms Windows timer tick. On the same plan the accepted trace is identical: **2.3–3.0×** faster with a swatch-palette profile, **1.5–1.8×** faster stroke movement on game profiles |
| 🎨 | **Cleaner outlines in Human 3.0** | Near-identical dark shades are merged, so the pink halo around outlines is gone (portrait match 93.7% → 97.0%) |
| 🖥️ | **New interface** | Drawing / Projects / Settings sections, a large Preview, a RUN bar that says *why* RUN is blocked, compact mode |
| 🤖 | **REDLAIN Assistant** | An original 2.5D robot artist that reacts only to real engine events and stops while the game receives input |
| 🌌 | **Calm motion system** | Animated background and transitions, with "Minimal motion", "No motion" and "Weak PC" modes |
| 🔎 | **Discover fixed** | Wikimedia Commons search works again (updated User-Agent per their policy) |

Raw numbers and the full audit: [V4 report — RU](docs/V4_REPORT_RU.md).

## 🚀 Quick start

**Ready-made program (no Python needed):**

1. Download **[RedlainDrawEngine-4.0.0-win64.zip](https://github.com/REDLAIN228/Program/releases/latest)** from Releases.
2. Extract the **whole** `RedlainDrawEngine` folder, keeping `_internal` next to the EXE, and run **`RedlainDrawEngine.exe`**.
3. Go to **Settings → Game profile**, pick the profile for your place, then run **TEST DRAW** on a clean white canvas.
4. In **Drawing**: Import → «Весь холст / 100%» → **BALANCED** → **PREVIEW** → **RUN**.

**From source:** install Python **3.11–3.13** on Windows 10/11 x64, extract the repository ZIP and run **`run.bat`**.

**F8** — pause & save / resume · **F9** — emergency stop. Projects and settings stay in `%LOCALAPPDATA%\AnimeDrawer` across updates.

## 📚 Documentation

| Guide | Description |
|---|---|
| [Start here — RU](START_HERE_RU.md) | Fast setup and first launch |
| [4.0 guide — RU](V4_GUIDE_RU.md) | New interface, modes, pause/resume, animations, updating from 3.0 |
| [4.0 report — RU](docs/V4_REPORT_RU.md) | Function audit, raw speed and quality measurements, limitations |
| [Roblox setup — RU](ROBLOX_START_RU.md) | Old place: HSV wheel and free brush slider |
| [New Roblox place — RU](NEW_PLACE_RU.md) | New place: numeric RGB popup palette |
| [Pause and resume — RU](AUTO_PAUSE_RU.md) | Recover and continue a drawing |
| [Windows/Roblox checks — RU](docs/WINDOWS_ROBLOX_TEST_RU.md) | Acceptance checks and limitations |
| [3.0 guide — RU](V3_GUIDE_RU.md) · [Full technical manual — RU](FULL_MANUAL_RU.md) | Earlier documentation, preserved |

## 🔧 Built with

**Python · PySide6 · NumPy · OpenCV · Windows input automation**

Source structure: `app/` (application), `app/ui/` (interface, motion, assistant), `tests/` (272 automated tests), `tools/` (benchmarks and smoke checks), `assets/` (visual assets).

## 💬 Follow the devlog

I'm **REDLAIN** — experimenting with Roblox development, AI tools, creative coding, and ideas that sometimes work unexpectedly well.

Find development notes, updates, free tools and real behind-the-scenes stories in **[REDLAIN / DEVLOG on Telegram](https://t.me/redlain_devlog)**.

<div align="center">

**Made with curiosity by [@REDLAIN228](https://github.com/REDLAIN228)**

*Building · Breaking · Learning*

</div>
