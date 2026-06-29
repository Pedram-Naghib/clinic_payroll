"""
Minimal Jalali (Persian) <-> Gregorian date conversion.
No external dependencies — pure Python implementation (based on the
well-known jdatetime/khayyam algorithm), so the system stays 100% offline
without needing pip packages at runtime.
"""

from __future__ import annotations
from datetime import date


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> date:
    jy += 1595
    days = -355668 + (365 * jy) + ((jy // 33) * 8) + (((jy % 33) + 3) // 4) + jd
    if jm < 7:
        days += (jm - 1) * 31
    else:
        days += ((jm - 7) * 30) + 186
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    g_days_in_month = [31, 29 if (gy % 4 == 0 and (gy % 100 != 0 or gy % 400 == 0)) else 28,
                       31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    while gm < 12 and gd > g_days_in_month[gm]:
        gd -= g_days_in_month[gm]
        gm += 1
    return date(gy, gm + 1, gd)


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    g_days_in_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    if (gy % 4 == 0 and (gy % 100 != 0 or gy % 400 == 0)):
        g_days_in_month[1] = 29
    gy2 = gy - 1600
    gm2 = gm - 1
    gd2 = gd - 1
    g_day_no = 365 * gy2 + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400)
    for i in range(gm2):
        g_day_no += g_days_in_month[i]
    g_day_no += gd2

    j_day_no = g_day_no - 79
    j_np = j_day_no // 12053
    j_day_no %= 12053
    jy = 979 + 33 * j_np + 4 * (j_day_no // 1461)
    j_day_no %= 1461
    if j_day_no >= 366:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365

    j_days_in_month = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29]
    jm = 0
    while jm < 11 and j_day_no >= j_days_in_month[jm]:
        j_day_no -= j_days_in_month[jm]
        jm += 1
    jd = j_day_no + 1
    return jy, jm + 1, jd


def parse_jalali_str(s: str) -> date:
    """Accepts '1405/03/01' or '1405-03-01' -> returns Gregorian date."""
    s = s.strip().replace("-", "/")
    jy, jm, jd = (int(x) for x in s.split("/"))
    return jalali_to_gregorian(jy, jm, jd)


def to_jalali_str(g_date: date) -> str:
    jy, jm, jd = gregorian_to_jalali(g_date.year, g_date.month, g_date.day)
    return f"{jy:04d}/{jm:02d}/{jd:02d}"


if __name__ == "__main__":
    # Sanity check against known date: 1405/03/01 (Khordad 1, 1405) ~ 2026/05/22
    g = jalali_to_gregorian(1405, 3, 1)
    print("1405/03/01 ->", g)
    back = to_jalali_str(g)
    print(g, "-> ", back)
