# Начните здесь — REDLAIN DRAW ENGINE 3.0

1. Установите Python 3.11–3.13 x64 с python.org. Python Launcher должен быть включён либо Python добавлен в PATH. Python 3.14+ пока не поддерживается.
2. Распакуйте **весь ZIP**, например в `C:\REDLAIN`. Не запускайте файлы внутри архива.
3. Дважды нажмите **run.bat**. Первый запуск установит библиотеки; готового EXE в исходном ZIP нет. При ошибке окно остаётся открытым, журнал — `logs/startup.log`.
4. Откройте **[инструкцию 3.0](V3_GUIDE_RU.md)**. Импорт — Workspace → Image / AI. Новый алгоритм — Human Engine → Human 3.0 → BALANCED. Для всего холста: Drawing Settings → Весь холст → 100%.
5. Сначала Settings → TOOLS → LOCAL CANVAS → TEST DRAW. Затем импорт картинки → PREVIEW → RUN. Для Roblox предварительно проверьте игровой профиль, размер кисти и TEST DRAW.
6. Для сохранения: **Pause & Save → дождаться Saved → выход через меню иконки R**. После запуска — Dashboard → Continue / Projects → Resume. Нужно открыть ту же сохранённую работу в самой игре; пустой холст не восстанавливается из контрольной точки приложения.

F8 — пауза/продолжение, F9 — остановка. STOP в 3.0 оставляет сохранённую контрольную точку. Новый RUN и Resume — разные действия; для незавершённого проекта нажимайте **Resume**.

Настройки и проекты: `%LOCALAPPDATA%\AnimeDrawer` — прежнее имя папки сохранено для совместимости. Окружение Python автоматически размещается в коротком пути `%LOCALAPPDATA%\AD\envs`, чтобы не упираться в лимит длины пути Windows.

Скорости Agile · 8 / Rapid · 9 / Sprint · 10 включены в список. Сначала выполните **Settings → SPEED CALIBRATION · real canvas** на чистом холсте. Быстрый режим не должен подменять регистрацию штрихов пропусками.

[Подробная инструкция](V3_GUIDE_RU.md) · [проверки и реальные измерения](docs/V3_VALIDATION_RU.md) · [сценарий проверки Roblox](docs/WINDOWS_ROBLOX_TEST_RU.md).

Сборка EXE выполняется на Windows через `build.bat`; результат `dist\RedlainDrawEngine\RedlainDrawEngine.exe`. Переносите всю папку `RedlainDrawEngine`, включая `_internal`. В облачной Linux-среде Windows-сборка и живой Roblox не выполнялись.
