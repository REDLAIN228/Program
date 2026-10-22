# Brush-size recognition templates

`size-digits.npz` contains rendered digit bitmaps, not font software. They were
generated with Pillow from Open Sans (Regular, Semibold, Bold), DejaVu Sans
(Regular, Bold), and Liberation Sans (Regular, Bold), at sizes 9–17.
The source fonts are not distributed in this repository. They are not required
on the user's computer. `tools/make_size_digits.py` rebuilds the templates from
explicit font file arguments. NumPy loads them with `allow_pickle=False`.

The readers select the configured blue size label, pink opacity label or black
numeric size field. This is not general OCR or automatic recognition of the game timer.
Uncertain, clipped, missing, and out-of-range readings stop mouse drawing.
Tests include separately rendered Noto Sans examples, not screenshots from Roblox.

## Числовой размер в новом плейсе

`tests/fixtures/numeric-size-labels.png` — отдельно от игровых снимков отрисованные чёрные числа 1, 2, 4, 8, 16, 32 на белом фоне (DejaVu Sans Bold, 26 px, ячейки 105×32). Фикстура проверяет отдельную чёрную маску `read_numeric_size`; реальные шрифт и размер игры требуют проверки на Windows. Во время тестов системные шрифты не нужны.
