# Brush-size recognition templates

`size-digits.npz` contains rendered digit bitmaps, not font software. They were
generated with Pillow from Open Sans (Regular, Semibold, Bold), DejaVu Sans
(Regular, Bold), and Liberation Sans (Regular, Bold), at sizes 9–17.
The source fonts are not distributed in this repository. They are not required
on the user's computer. `tools/make_size_digits.py` rebuilds the templates from
explicit font file arguments. NumPy loads them with `allow_pickle=False`.

These templates recognize only the blue brush-size label in the configured
rectangle. This is not general OCR or automatic recognition of the game timer.
Uncertain, clipped, missing, and out-of-range readings stop mouse drawing.
Tests include separately rendered Noto Sans examples, not screenshots from Roblox.
