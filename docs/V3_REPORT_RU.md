# REDLAIN DRAW ENGINE 3.0 — отчёт об изменениях

Модернизирован существующий Python/PySide6-проект; GUI-фреймворк и рабочие профили не заменены. История, AI-провайдер, калибровка, импорт/захват, экспорт, таймер, Legacy и Vector 2.0 сохранены. Программа использует только обычный пользовательский ввод и снимки экрана; внедрения в Roblox нет.

## Новые модули

| Модуль | Ответственность |
| --- | --- |
| app/human.py | CPU-сегментация цветовых масс, 7 упорядоченных виртуальных этапов, соединённые безопасные траектории, адаптивные калиброванные кисти, режимы FAST/BALANCED/MASTERPIECE, ограниченная коррекция покрытия |
| app/canvas_fill.py | Геометрическая маска добавленных полей; 8 реальных способов заполнения, растеризованный текст только внутри полей |
| app/projects.py | Формат проекта 3, неизменяемые SHA256-ресурсы, исходник/Preview/маски/сегментация/план, атомарные контрольные точки, резервный манифест, проверка холста, отдельная очередь дисковых записей |
| app/telemetry.py | Реальные счётчики ввода, ожиданий и пути; разложение прогнозируемых затрат |
| app/speed_calibration.py | Четыре реальных тестовых штриха и анализ регистрации/геометрии, привязка принятой скорости к калибровке |
| app/input_lock.py | Эксклюзивная межпроцессная OS-блокировка внешнего ввода, автоматическое освобождение после смерти процесса |
| app/event_log.py | Ротируемый журнал сохранений, состояния и ошибок |
| app/discover.py | Официальный Wikimedia Commons API, атрибуция, ограниченные HTTPS-загрузки, кэш, избранное и локальный анализ сложности |
| app/ui/v3.py + v3_actions.py | Шесть новых разделов поверх существующего контроллера; жизненный цикл проекта, безопасный Resume, фоновые jobs, проверка перед выходом |
| app/ui/live_core.py | Реальная карта завершённых мазков и активной траектории, 7 взвешенных сегментов, ETA и анимация завершения; восстановленный растр готовится вне UI |
| app/ui/fill_editor.py | Интерактивный редактор только добавленных полей, немедленный предпросмотр текста/цвета/положения |
| app/ui/discover.py | Реальная сетка результатов и детальная карточка, Preview/Import/Favorite/Open Original, cancellable worker |
| app/ui/projects_page.py | Карточки работ, Dashboard и CONTINUE YOUR MASTERPIECE |

## Изменения в прежнем ядре

Plan/Stroke получили совместимые stage/kind и настройки Human. DrawingExecutor публикует реальные события ввода и подтверждённый курсор исполнения, сохраняет по таймеру/этапам/паузе, восстанавливает точный журнал и накопленное время, сбрасывает кэш контроллеров после Resume. Выполненные индексы не повторяются. При автопаузе неподтверждённый хвост откатывается к последней визуальной проверке. Цвет/размер/Enter, защищённые зоны и выход мыши за холст остаются под проверкой.

Скорости дополнены Agile · 8 / Rapid · 9 / Sprint · 10. Human снижает скорость на важных и резких участках; более редкие samples разрешены только после прохождения реального теста в соответствующем профиле. Скорости не отключают подтверждение игровых контролов. Неисправность ввода возвращает осторожную выборку.

Live Art Core не использует случайный прогресс: цвет появляется после stroke_complete, световая точка получает позиции реального ввода, rewind удаляет неподтверждённый хвост. ETA опирается на стоимость траекторий/переключений и измеренную производительность. При паузе нет искусственного роста. Старые progress/timer data-targets сохранены для совместимости, обычная загрузочная полоса скрыта.

GUI сохраняет прежние ограничения конфликтующих операций. Планирование, загрузка проектов/превью/кэша, Discover и редактор полей используют фоновые работы; дисковый writer не обращается к Qt. Его сообщения забирает UI-таймер. Логотип R/курсор/траектория — оригинальный SVG, прозрачные PNG и многомасштабный Windows ICO; используется в заголовке, окне, плавающей иконке и splash. Windows build/CI обновлены под RedlainDrawEngine.

## Запуск и зависимости

Windows: распаковать весь проект → **run.bat**. Python 3.11–3.13 x64; первый запуск ставит pinned requirements автоматически в короткий путь. Ручной запуск: `python -m pip install -r requirements.txt`, затем `python main.py`. Локальная проверка без игры: `run.bat --test-canvas`. Версия: `python main.py --version`.

Новые runtime-пакеты не требуются: существующие PySide6, OpenCV headless, NumPy, Pillow, MSS, httpx, keyring. Тяжёлые нейросети не добавлены. В облачном окружении зависимости установлены; uv pip check проверил 33 совместимых пакета. Для EXE нужны Windows и build.bat; для тестов requirements-dev.txt. Исходный ZIP не содержит собранного Windows EXE.

Данные остаются в `%LOCALAPPDATA%\AnimeDrawer`. Копировать проект на другой ПК нужно вместе со всей `projects/.assets`. Контрольные точки не заменяют серверное сохранение самого Roblox. На неизвестном холсте Resume требует явного подтверждения и предлагает повторную калибровку; другой физический размер не принимается. Старый несохранённый запуск 2.0 из памяти не восстанавливается после его закрытия.

[Пошаговое руководство](../V3_GUIDE_RU.md) · [измерения, результаты тестов и ограничения](V3_VALIDATION_RU.md) · [нативная проверка Windows/Roblox](WINDOWS_ROBLOX_TEST_RU.md).

## Изменённые файлы

<!-- FILE LIST -->
- [.github/workflows/windows.yml](../.github/workflows/windows.yml)
- [README.md](../README.md)
- [START_HERE_RU.md](../START_HERE_RU.md)
- [V3_GUIDE_RU.md](../V3_GUIDE_RU.md)
- [app/automation.py](../app/automation.py)
- [app/canvas_fill.py](../app/canvas_fill.py)
- [app/discover.py](../app/discover.py)
- [app/event_log.py](../app/event_log.py)
- [app/human.py](../app/human.py)
- [app/input_lock.py](../app/input_lock.py)
- [app/main.py](../app/main.py)
- [app/models.py](../app/models.py)
- [app/planner.py](../app/planner.py)
- [app/projects.py](../app/projects.py)
- [app/speed_calibration.py](../app/speed_calibration.py)
- [app/storage.py](../app/storage.py)
- [app/telemetry.py](../app/telemetry.py)
- [app/ui/common.py](../app/ui/common.py)
- [app/ui/discover.py](../app/ui/discover.py)
- [app/ui/fill_editor.py](../app/ui/fill_editor.py)
- [app/ui/floating.py](../app/ui/floating.py)
- [app/ui/instruments.py](../app/ui/instruments.py)
- [app/ui/intelligence.py](../app/ui/intelligence.py)
- [app/ui/live_core.py](../app/ui/live_core.py)
- [app/ui/panel.py](../app/ui/panel.py)
- [app/ui/projects_page.py](../app/ui/projects_page.py)
- [app/ui/v3.py](../app/ui/v3.py)
- [app/ui/v3_actions.py](../app/ui/v3_actions.py)
- [app/windows.py](../app/windows.py)
- [assets/redlain-icon.png](../assets/redlain-icon.png)
- [assets/redlain-icon.svg](../assets/redlain-icon.svg)
- [assets/redlain-logo.png](../assets/redlain-logo.png)
- [assets/redlain-logo.svg](../assets/redlain-logo.svg)
- [assets/redlain-monochrome.png](../assets/redlain-monochrome.png)
- [assets/redlain-monochrome.svg](../assets/redlain-monochrome.svg)
- [assets/redlain.ico](../assets/redlain.ico)
- [docs/V3_REPORT_RU.md](../docs/V3_REPORT_RU.md)
- [docs/V3_VALIDATION_RU.md](../docs/V3_VALIDATION_RU.md)
- [docs/V3_WORK_LOG.md](../docs/V3_WORK_LOG.md)
- [docs/WINDOWS_ROBLOX_TEST_RU.md](../docs/WINDOWS_ROBLOX_TEST_RU.md)
- [docs/v3-baseline.json](../docs/v3-baseline.json)
- [docs/v3-benchmark.json](../docs/v3-benchmark.json)
- [docs/v3-live-paused.png](../docs/v3-live-paused.png)
- [docs/v3-workspace-compact.png](../docs/v3-workspace-compact.png)
- [docs/v3-workspace.png](../docs/v3-workspace.png)
- [pyproject.toml](../pyproject.toml)
- [tests/conftest.py](../tests/conftest.py)
- [tests/test_canvas_fill.py](../tests/test_canvas_fill.py)
- [tests/test_discover.py](../tests/test_discover.py)
- [tests/test_human.py](../tests/test_human.py)
- [tests/test_input_lock.py](../tests/test_input_lock.py)
- [tests/test_live_core.py](../tests/test_live_core.py)
- [tests/test_panel.py](../tests/test_panel.py)
- [tests/test_projects.py](../tests/test_projects.py)
- [tests/test_speed_calibration.py](../tests/test_speed_calibration.py)
- [tests/test_v3_ui.py](../tests/test_v3_ui.py)
- [tools/benchmark_v3.py](../tools/benchmark_v3.py)
- [tools/gui_startup_smoke.py](../tools/gui_startup_smoke.py)
- [tools/render_brand.py](../tools/render_brand.py)
- [tools/v3_visual_smoke.py](../tools/v3_visual_smoke.py)
- [tools/windows_build.py](../tools/windows_build.py)
