"""Sample problems with hand-written reference solutions used for scoring.

Every problem states the exact RESULT keys and units. `tolerance` maps each scored key to
(relative tolerance, absolute tolerance); (0, 0) means an exact match. The reference functions
are cross-checked by independent methods in tests/test_tasks.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from typing import Callable


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    problem: str
    tolerance: dict[str, tuple[float, float]]
    reference: Callable[[], dict]

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(self.tolerance)


# --------------------------------------------------------------------- references

def loan_prepay_reference() -> dict:
    principal, r, n, prepay = 5_000_000.0, 0.085 / 12, 240, 100_000.0
    emi = principal * r * (1 + r) ** n / ((1 + r) ** n - 1)
    interest_without = emi * n - principal
    balance, month, interest_with = principal, 0, 0.0
    while balance > 1e-6:
        month += 1
        interest = balance * r
        interest_with += interest
        balance -= min(emi, balance + interest) - interest
        if month % 12 == 0 and balance > 1e-6:
            balance -= min(prepay, balance)
    return {"emi": round(emi, 2), "months_with_prepayment": month,
            "months_saved": n - month, "interest_saved": round(interest_without - interest_with, 2)}


def sip_stepup_reference() -> dict:
    base, step, monthly_rate, months = 10_000.0, 0.10, 0.01, 180
    invested = fv = fv_flat = 0.0
    for m in range(months):                       # m = 0 is the first month
        amount = base * (1 + step) ** (m // 12)
        growth = (1 + monthly_rate) ** (months - m)
        invested += amount
        fv += amount * growth
        fv_flat += base * growth
    return {"total_invested": round(invested), "future_value": round(fv),
            "wealth_gained": round(fv - invested), "fv_without_stepup": round(fv_flat)}


TAX_SLABS = [(300_000, 0.0), (700_000, 0.05), (1_000_000, 0.10), (1_200_000, 0.15),
             (1_500_000, 0.20), (math.inf, 0.30)]


def new_regime_tax(gross: float) -> float:
    taxable = max(gross - 75_000, 0)
    tax, lower = 0.0, 0.0
    for upper, rate in TAX_SLABS:
        if taxable > lower:
            tax += (min(taxable, upper) - lower) * rate
        lower = upper
    if taxable <= 700_000:
        tax = 0.0                                  # rebate u/s 87A
    else:
        tax = min(tax, taxable - 700_000)          # marginal relief
    return tax * 1.04                              # 4% health and education cess


def income_tax_reference() -> dict:
    a, b, c = (new_regime_tax(g) for g in (720_000, 790_000, 1_850_000))
    return {"tax_a": round(a), "tax_b": round(b), "tax_c": round(c),
            "effective_rate_c_pct": round(c / 1_850_000 * 100, 2)}


def drag_range(angle_deg: float, v0: float = 50.0, k: float = 0.1, g: float = 9.81) -> float:
    """Exact range with linear drag: x(t), y(t) in closed form, landing time by bisection."""
    th = math.radians(angle_deg)
    vx, vy = v0 * math.cos(th), v0 * math.sin(th)

    def y(t: float) -> float:
        return (vy + g / k) / k * (1 - math.exp(-k * t)) - g / k * t

    lo, hi = 1e-9, 2 * vy / g + 1.0                # y(hi) < 0: drag shortens the flight
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if y(mid) > 0 else (lo, mid)
    return vx / k * (1 - math.exp(-k * lo))


def projectile_reference() -> dict:
    lo, hi = 1.0, 89.0                             # golden-section search on the angle
    inv_phi = (math.sqrt(5) - 1) / 2
    for _ in range(100):
        a, b = hi - inv_phi * (hi - lo), lo + inv_phi * (hi - lo)
        lo, hi = (lo, b) if drag_range(a) > drag_range(b) else (a, hi)
    best = (lo + hi) / 2
    return {"best_angle_deg": round(best, 1), "max_range_m": round(drag_range(best), 2),
            "range_at_45_m": round(drag_range(45.0), 2)}


@lru_cache(maxsize=None)
def p_no_triple(n: int, days: int = 365) -> Fraction:
    """P(no day has 3+ people): k days with 2 people, n-2k with 1, counted exactly."""
    total = 0
    for k in range(n // 2 + 1):
        singles = n - 2 * k
        if k + singles > days:
            continue
        day_choices = math.factorial(days) // (math.factorial(k) * math.factorial(singles)
                                               * math.factorial(days - k - singles))
        total += day_choices * math.factorial(n) // 2 ** k
    return Fraction(total, days ** n)


def p_no_pair(n: int, days: int = 365) -> Fraction:
    return Fraction(math.perm(days, n), days ** n) if n <= days else Fraction(0)


def birthday_reference() -> dict:
    n_pair = next(n for n in range(1, 366) if 1 - p_no_pair(n) > Fraction(1, 2))
    n_triple = next(n for n in range(1, 731) if 1 - p_no_triple(n) > Fraction(1, 2))
    return {"n_pair": n_pair, "p_pair": round(float(1 - p_no_pair(n_pair)), 6),
            "n_triple": n_triple, "p_triple": round(float(1 - p_no_triple(n_triple)), 6)}


EOQ_DEMAND, EOQ_ORDER_COST, EOQ_HOLD_RATE = 12_000, 1_500, 0.20


def eoq_price(q: int) -> float:
    return 100.0 if q < 1000 else 96.0 if q < 2500 else 94.0


def eoq_total_cost(q: int) -> float:
    p = eoq_price(q)
    return EOQ_DEMAND * p + EOQ_DEMAND / q * EOQ_ORDER_COST + q / 2 * EOQ_HOLD_RATE * p


def eoq_reference() -> dict:
    eoq_base = math.sqrt(2 * EOQ_DEMAND * EOQ_ORDER_COST / (EOQ_HOLD_RATE * 100))
    best = min(range(1, 30_001), key=eoq_total_cost)   # brute force over integer quantities
    return {"eoq_base": round(eoq_base, 2), "best_order_qty": best,
            "min_total_cost": round(eoq_total_cost(best), 2),
            "orders_per_year": round(EOQ_DEMAND / best, 2)}


YEAR_FACTORS = {
    2020: (1 + 0.06 / 4) ** 4,
    2021: (1 + 0.072 / 12) ** 12,
    2022: (1 + 0.055 / 365) ** 365,
    2023: 1.08,
    2024: math.exp(0.065),
}
DEPOSITS = {2020: 200_000.0, 2022: 50_000.0, 2024: 50_000.0}


def compound_reference() -> dict:
    value = 0.0
    for year in range(2020, 2025):
        value = (value + DEPOSITS.get(year, 0.0)) * YEAR_FACTORS[year]

    def fv_at(rate: float) -> float:
        return sum(d * (1 + rate) ** (2025 - y) for y, d in DEPOSITS.items())

    lo, hi = 0.0, 0.5                               # fv_at is increasing in rate: bisection
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if fv_at(mid) < value else (lo, mid)
    return {"final_value": round(value, 2),
            "total_interest": round(value - sum(DEPOSITS.values()), 2),
            "equivalent_rate_pct": round(lo * 100, 3)}


def strings_reference(length: int = 8, letters: int = 26, digits: int = 10) -> dict:
    # counts[d][t]: strings so far with d digits whose last character is of type t (0=letter)
    counts = [[0, 0] for _ in range(length + 1)]
    counts[0][0], counts[1][1] = letters, digits
    for _ in range(length - 1):
        nxt = [[0, 0] for _ in range(length + 1)]
        for d in range(length + 1):
            letter_end, digit_end = counts[d]
            if d <= length:  # append a letter: anything but the same letter
                nxt[d][0] += letter_end * (letters - 1) + digit_end * letters
            if d + 1 <= length:  # append a digit: anything but the same digit
                nxt[d + 1][1] += letter_end * digits + digit_end * (digits - 1)
        counts = nxt
    by_digits = [sum(c) for c in counts]
    mixed = sum(by_digits[1:length])
    three = by_digits[3]
    return {"count_mixed": mixed, "count_three_digits": three,
            "prob_three_digits": round(three / (letters + digits) ** length, 6)}


# --------------------------------------------------------------------- task list

TASKS: dict[str, Task] = {t.id: t for t in [
    Task("loan_prepay", "Home loan with yearly prepayments", (
        "A home loan of Rs 50,00,000 is taken at 8.5% annual interest, compounded monthly "
        "(monthly rate r = 8.5%/12), for 20 years (240 monthly EMIs). The EMI is fixed with the "
        "standard formula EMI = P*r*(1+r)^n / ((1+r)^n - 1) and is not rounded during the "
        "calculation. Each month, interest = outstanding balance * r and the rest of the EMI "
        "repays principal. At the end of every 12th month (right after that month's EMI) the "
        "borrower also prepays Rs 1,00,000 (or the remaining balance, if smaller), which reduces "
        "the outstanding principal; the EMI amount stays the same. When the balance plus that "
        "month's interest is less than one EMI, the final payment is just that amount and the "
        "loan closes. Compute: emi (Rs, 2 decimals); months_with_prepayment (number of monthly "
        "payments until the loan closes, counting the final partial payment); months_saved "
        "(240 minus that); interest_saved (total interest without prepayments minus total "
        "interest with prepayments, Rs, 2 decimals). RESULT keys: emi, months_with_prepayment, "
        "months_saved, interest_saved."),
        {"emi": (1e-4, 0.01), "months_with_prepayment": (0, 0), "months_saved": (0, 0),
         "interest_saved": (2e-3, 1.0)}, loan_prepay_reference),
    Task("sip_stepup", "Step-up SIP future value", (
        "An investor runs a monthly SIP for 15 years (180 instalments) with a 10% annual "
        "step-up: the instalment is Rs 10,000 per month in year 1, Rs 11,000 in year 2, "
        "Rs 12,100 in year 3, and so on (multiply by 1.10 each year, no rounding). Each "
        "instalment is invested at the START of its month. The fund earns 12% a year compounded "
        "monthly, i.e. 1% per month, so an instalment invested at the start of month m "
        "(m = 1..180) is multiplied by 1.01^(181 - m) by the end of month 180. Compute, rounded "
        "to the nearest rupee: total_invested; future_value (value at the end of month 180); "
        "wealth_gained (future_value - total_invested); fv_without_stepup (future value if "
        "Rs 10,000 were invested every month with no step-up, same rules). RESULT keys: "
        "total_invested, future_value, wealth_gained, fv_without_stepup."),
        {"total_invested": (1e-5, 2.0), "future_value": (1e-5, 2.0),
         "wealth_gained": (1e-5, 2.0), "fv_without_stepup": (1e-5, 2.0)}, sip_stepup_reference),
    Task("income_tax", "Indian income tax, new regime FY 2024-25", (
        "Compute Indian income tax under the new tax regime for FY 2024-25 for three salaried "
        "people with gross salaries A = Rs 7,20,000, B = Rs 7,90,000 and C = Rs 18,50,000. Use "
        "exactly these rules: (1) taxable income = gross salary - standard deduction of "
        "Rs 75,000. (2) Slab rates on taxable income: up to 3,00,000: 0%; 3,00,001-7,00,000: 5%; "
        "7,00,001-10,00,000: 10%; 10,00,001-12,00,000: 15%; 12,00,001-15,00,000: 20%; above "
        "15,00,000: 30%. (3) Rebate u/s 87A: if taxable income <= 7,00,000 the tax is zero. "
        "(4) Marginal relief: if taxable income exceeds 7,00,000, the tax before cess cannot "
        "exceed (taxable income - 7,00,000). (5) Add 4% health and education cess on the tax "
        "after rebate/relief. (6) No surcharge and no other deductions. Report each person's "
        "total tax including cess, rounded to the nearest rupee, and C's effective tax rate as "
        "a percentage of gross salary (2 decimals). RESULT keys: tax_a, tax_b, tax_c, "
        "effective_rate_c_pct."),
        {"tax_a": (0, 1.0), "tax_b": (0, 1.0), "tax_c": (0, 1.0),
         "effective_rate_c_pct": (0, 0.011)}, income_tax_reference),
    Task("projectile_drag", "Best launch angle with linear air drag", (
        "A projectile is launched from flat ground (y = 0) with speed 50 m/s. Gravity "
        "g = 9.81 m/s^2 acts downwards and air resistance is linear: the drag acceleration is "
        "-k*v (a vector opposite to the velocity) with k = 0.1 per second. Find the launch angle "
        "(degrees above the horizontal) that maximises the horizontal range (the x position when "
        "the projectile returns to y = 0) and that maximum range. Also report the range at 45 "
        "degrees for comparison. Use an accurate method (the analytic solution of the linear-drag "
        "equations, or a fine numerical integration with interpolation of the landing point). "
        "RESULT keys: best_angle_deg (1 decimal), max_range_m (2 decimals), range_at_45_m "
        "(2 decimals)."),
        # the range is flat near the optimum (R(40) and R(39.4) differ by about 0.01%), so the
        # angle gets a generous +/-1 degree while the ranges must be within 0.5%
        {"best_angle_deg": (0, 1.0), "max_range_m": (5e-3, 0.0), "range_at_45_m": (5e-3, 0.0)},
        projectile_reference),
    Task("birthday", "Birthday problem: pairs and triples (exact)", (
        "Assume 365 equally likely birthdays (ignore leap years) and independent people. "
        "(a) Find the smallest group size n_pair for which the probability that at least two "
        "people share a birthday exceeds 0.5, and that probability p_pair (6 decimals). (b) Find "
        "the smallest group size n_triple for which the probability that at least three people "
        "share the same birthday exceeds 0.5, and that probability p_triple (6 decimals). "
        "Compute the probabilities exactly (combinatorics or dynamic programming, not "
        "simulation). RESULT keys: n_pair, p_pair, n_triple, p_triple."),
        {"n_pair": (0, 0), "p_pair": (0, 2e-6), "n_triple": (0, 0), "p_triple": (0, 2e-6)},
        birthday_reference),
    Task("eoq_discount", "Order quantity with quantity discounts", (
        "A retailer sells 12,000 units per year at a constant rate. Placing an order costs "
        "Rs 1,500 and the annual holding cost per unit is 20% of the unit purchase price. The "
        "supplier gives all-units quantity discounts: order quantity below 1,000 units: Rs 100 "
        "per unit; 1,000 to 2,499 units: Rs 96 per unit; 2,500 units or more: Rs 94 per unit. "
        "Total annual cost = D*p + (D/Q)*S + (Q/2)*h*p, where D is annual demand, S the cost per "
        "order, h = 20% and p the unit price that applies to order quantity Q. Find: eoq_base, "
        "the classic EOQ at the undiscounted price of Rs 100 (2 decimals); best_order_qty, the "
        "integer order quantity Q that minimises total annual cost; min_total_cost, that minimum "
        "total annual cost (Rs, 2 decimals); orders_per_year at that Q (2 decimals). RESULT "
        "keys: eoq_base, best_order_qty, min_total_cost, orders_per_year."),
        {"eoq_base": (0, 0.011), "best_order_qty": (0, 0), "min_total_cost": (1e-6, 0.5),
         "orders_per_year": (0, 0.011)}, eoq_reference),
    Task("compound_varying", "Compound interest with changing rates and deposits", (
        "Rs 2,00,000 is invested on 1 Jan 2020. Further deposits of Rs 50,000 are made on "
        "1 Jan 2022 and on 1 Jan 2024. The nominal annual rate and compounding change every "
        "calendar year: 2020: 6% compounded quarterly; 2021: 7.2% compounded monthly; 2022: "
        "5.5% compounded daily (365 periods); 2023: 8% compounded annually; 2024: 6.5% "
        "compounded continuously. Each year's growth factor applies to the whole balance held "
        "during that year (treat every year as exactly one year; a deposit on 1 Jan earns that "
        "whole year's growth). Compute: final_value on 31 Dec 2024 (Rs, 2 decimals); "
        "total_interest = final_value minus total deposits (Rs, 2 decimals); "
        "equivalent_rate_pct, the single annual effective rate r (in %, 3 decimals) such that "
        "the same three deposits compounded annually at r would grow to the same final value "
        "(solve numerically). RESULT keys: final_value, total_interest, equivalent_rate_pct."),
        {"final_value": (1e-6, 0.05), "total_interest": (1e-5, 0.05),
         "equivalent_rate_pct": (0, 0.0021)}, compound_reference),
    Task("constrained_strings", "Counting strings with adjacency constraints", (
        "Consider 8-character strings over an alphabet of 26 uppercase letters and 10 digits "
        "(36 symbols) in which no two adjacent characters are identical. Find: (a) count_mixed, "
        "the number of such strings that contain at least one letter and at least one digit; "
        "(b) count_three_digits, the number of such strings that contain exactly 3 digits; "
        "(c) prob_three_digits, the probability that a uniformly random 8-character string over "
        "the 36 symbols (with no restriction) has exactly 3 digits AND no two adjacent identical "
        "characters (6 decimals). RESULT keys: count_mixed, count_three_digits, "
        "prob_three_digits."),
        {"count_mixed": (0, 0), "count_three_digits": (0, 0), "prob_three_digits": (0, 2e-6)},
        strings_reference),
]}


@lru_cache(maxsize=None)
def reference_answer(task_id: str) -> dict:
    return TASKS[task_id].reference()


def get_task(task_id: str) -> Task:
    if task_id not in TASKS:
        raise KeyError(f"unknown task {task_id!r}; choose from {', '.join(TASKS)}")
    return TASKS[task_id]


def score(task: Task, result: dict | None) -> dict:
    """Compare a RESULT dict with the reference answer key by key."""
    expected = reference_answer(task.id)
    checks = {}
    for key, (rel_tol, abs_tol) in task.tolerance.items():
        got = (result or {}).get(key)
        try:
            ok = math.isclose(float(got), float(expected[key]), rel_tol=rel_tol, abs_tol=abs_tol)
        except (TypeError, ValueError):
            ok = False
        checks[key] = {"expected": expected[key], "got": got, "ok": ok}
    return {"correct": all(c["ok"] for c in checks.values()), "checks": checks}
