"""
Converts an integer amount (Rials) into Persian words -- e.g. 305841000 ->
"سیصد و پنج میلیون و هشتصد و چهل و یک هزار". Pure Python, no dependencies,
so it stays consistent with the rest of the offline stack.

Used by the payslip to print net pay in words under the numeric total, the
way official Iranian pay-slips conventionally do (see the sample fiches).
"""
from __future__ import annotations

_ONES = ["", "یک", "دو", "سه", "چهار", "پنج", "شش", "هفت", "هشت", "نه"]
_TEENS = [
    "ده", "یازده", "دوازده", "سیزده", "چهارده", "پانزده",
    "شانزده", "هفده", "هجده", "نوزده",
]
_TENS = ["", "ده", "بیست", "سی", "چهل", "پنجاه", "شصت", "هفتاد", "هشتاد", "نود"]
_HUNDREDS = [
    "", "صد", "دویست", "سیصد", "چهارصد", "پانصد",
    "ششصد", "هفتصد", "هشتصد", "نهصد",
]
_SCALES = ["", "هزار", "میلیون", "میلیارد", "تریلیون", "کوادریلیون"]


def _three_digits_to_words(n: int) -> str:
    """n is 0-999."""
    if n == 0:
        return ""
    parts = []
    hundred, rem = divmod(n, 100)
    if hundred:
        parts.append(_HUNDREDS[hundred])
    if rem:
        if rem < 10:
            parts.append(_ONES[rem])
        elif rem < 20:
            parts.append(_TEENS[rem - 10])
        else:
            ten, one = divmod(rem, 10)
            parts.append(_TENS[ten])
            if one:
                parts.append(_ONES[one])
    return " و ".join(parts)


def number_to_persian_words(n: int) -> str:
    """Converts a non-negative integer to Persian words. Returns 'صفر' for 0."""
    n = int(n)
    if n == 0:
        return "صفر"
    if n < 0:
        return "منفی " + number_to_persian_words(-n)

    groups = []
    while n > 0:
        n, rem = divmod(n, 1000)
        groups.append(rem)

    parts = []
    for i in range(len(groups) - 1, -1, -1):
        g = groups[i]
        if g == 0:
            continue
        words = _three_digits_to_words(g)
        if i > 0:
            words += " " + _SCALES[i]
        parts.append(words)

    return " و ".join(parts)


def amount_in_words_rials(n: int) -> str:
    """e.g. 305841000 -> 'سیصد و پنج میلیون و هشتصد و چهل و یک هزار ریال'"""
    return f"{number_to_persian_words(n)} ریال"


if __name__ == "__main__":
    for test in [0, 1000, 305841000, 224352000, 1500000, 999, 1000000000]:
        print(test, "->", amount_in_words_rials(test))