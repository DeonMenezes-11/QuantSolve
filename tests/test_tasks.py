"""Reference answers are cross-checked with independent methods."""

import itertools
import math

import pytest

from quantsolve import tasks


@pytest.mark.parametrize("task", tasks.TASKS.values(), ids=tasks.TASKS.keys())
def test_reference_has_declared_keys_and_scores_itself_correct(task):
    ref = tasks.reference_answer(task.id)
    assert set(ref) == set(task.keys)
    assert all(key in task.problem for key in task.keys)  # the problem names every key
    assert tasks.score(task, ref)["correct"]


def test_score_detects_wrong_and_missing_values():
    task = tasks.get_task("income_tax")
    wrong = dict(tasks.reference_answer("income_tax"), tax_b=21_500 * 1.04)  # no marginal relief
    assert not tasks.score(task, wrong)["correct"]
    assert not tasks.score(task, {})["correct"]
    as_strings = {k: str(v) for k, v in tasks.reference_answer("income_tax").items()}
    assert tasks.score(task, as_strings)["correct"]


def test_loan_matches_year_by_year_closed_form():
    P, r, n, prepay = 5e6, 0.085 / 12, 240, 1e5
    emi = P * r * (1 + r) ** n / ((1 + r) ** n - 1)
    balance, months, paid = P, 0, 0.0
    while True:  # jump a whole year at a time using the annuity balance formula
        after = [balance * (1 + r) ** j - emi * ((1 + r) ** j - 1) / r for j in range(13)]
        closing = next((j for j in range(1, 13) if after[j] <= 1e-6), None)
        if closing:
            paid += emi * (closing - 1) + after[closing - 1] * (1 + r)
            months += closing
            break
        balance, months, paid = after[12], months + 12, paid + 12 * emi
        extra = min(prepay, balance)
        balance, paid = balance - extra, paid + extra
    ref = tasks.reference_answer("loan_prepay")
    assert ref["months_with_prepayment"] == months
    assert math.isclose(ref["interest_saved"], (emi * n - P) - (paid - P), abs_tol=0.01)


def test_sip_matches_geometric_series():
    yearly = sum(1.01 ** -j for j in range(12))
    fv = sum(10_000 * 1.1 ** y * 1.01 ** (180 - 12 * y) * yearly for y in range(15))
    flat = 10_000 * sum(1.01 ** k for k in range(1, 181))
    ref = tasks.reference_answer("sip_stepup")
    assert ref["future_value"] == round(fv) and ref["fv_without_stepup"] == round(flat)
    assert ref["total_invested"] == round(10_000 * 12 * (1.1 ** 15 - 1) / 0.1)


def test_income_tax_hand_computed():
    ref = tasks.reference_answer("income_tax")
    assert ref["tax_a"] == 0                                   # 6.45 L taxable -> rebate
    assert ref["tax_b"] == 15_600                              # relief caps tax at 15,000
    assert ref["tax_c"] == round((20_000 + 30_000 + 30_000 + 60_000 + 82_500) * 1.04)


def test_projectile_matches_rk4_simulation():
    def rk4_range(deg, dt=2e-3, v0=50.0, k=0.1, g=9.81):
        th = math.radians(deg)
        s = (0.0, 0.0, v0 * math.cos(th), v0 * math.sin(th))
        f = lambda s: (s[2], s[3], -k * s[2], -g - k * s[3])  # noqa: E731
        while True:
            k1 = f(s)
            k2 = f(tuple(a + dt / 2 * b for a, b in zip(s, k1)))
            k3 = f(tuple(a + dt / 2 * b for a, b in zip(s, k2)))
            k4 = f(tuple(a + dt * b for a, b in zip(s, k3)))
            new = tuple(a + dt / 6 * (b + 2 * c + 2 * d + e) for a, b, c, d, e in zip(s, k1, k2, k3, k4))
            if new[1] < 0 < new[0]:
                return s[0] + s[1] / (s[1] - new[1]) * (new[0] - s[0])
            s = new
    ref = tasks.reference_answer("projectile_drag")
    best_range, best_angle = max((rk4_range(a / 2), a / 2) for a in range(74, 84))
    assert abs(best_angle - ref["best_angle_deg"]) <= 0.5
    assert math.isclose(best_range, ref["max_range_m"], rel_tol=1e-3)
    assert math.isclose(rk4_range(45), ref["range_at_45_m"], rel_tol=1e-3)


def test_birthday_triple_matches_generating_function():
    from fractions import Fraction

    def p_no_triple(n, days=365):  # coefficient of x^n in (1 + x + x^2/2)^days, times n!/days^n
        poly = [Fraction(1)]
        for _ in range(days):
            new = [Fraction(0)] * min(len(poly) + 2, n + 1)
            for i, a in enumerate(poly):
                for j, b in enumerate((1, 1, Fraction(1, 2))):
                    if i + j <= n:
                        new[i + j] += a * b
            poly = new
        return poly[n] * math.factorial(n) / Fraction(days) ** n

    ref = tasks.reference_answer("birthday")
    assert (ref["n_pair"], ref["n_triple"]) == (23, 88)
    assert 1 - p_no_triple(87) < Fraction(1, 2) < 1 - p_no_triple(88)
    assert math.isclose(float(1 - p_no_triple(88)), ref["p_triple"], abs_tol=1e-6)


def test_eoq_matches_classic_discount_algorithm():
    D, S, h = 12_000, 1_500, 0.2
    candidates = []
    for low, high, price in [(1, 999, 100), (1000, 2499, 96), (2500, 10 ** 9, 94)]:
        q = min(max(round(math.sqrt(2 * D * S / (h * price))), low), high)
        candidates.append((D * price + D / q * S + q / 2 * h * price, q))
    cost, q = min(candidates)
    ref = tasks.reference_answer("eoq_discount")
    assert (ref["best_order_qty"], ref["min_total_cost"]) == (q, round(cost, 2))


def test_compound_matches_log_form():
    growth = (4 * math.log1p(0.015), 12 * math.log1p(0.006),
              365 * math.log1p(0.055 / 365), math.log(1.08), 0.065)
    value = 200_000 * math.exp(growth[0] + growth[1])
    value = (value + 50_000) * math.exp(growth[2] + growth[3])
    value = (value + 50_000) * math.exp(growth[4])
    ref = tasks.reference_answer("compound_varying")
    assert math.isclose(ref["final_value"], value, abs_tol=0.01)
    r = ref["equivalent_rate_pct"] / 100
    implied = 200_000 * (1 + r) ** 5 + 50_000 * (1 + r) ** 3 + 50_000 * (1 + r)
    assert math.isclose(implied, value, rel_tol=1e-4)


def test_strings_match_closed_form_and_type_patterns():
    ref = tasks.reference_answer("constrained_strings")
    assert ref["count_mixed"] == 36 * 35 ** 7 - 26 * 25 ** 7 - 10 * 9 ** 7
    three = 0
    for pattern in itertools.product((0, 1), repeat=8):  # 0 = letter, 1 = digit
        if sum(pattern) != 3:
            continue
        count = 10 if pattern[0] else 26
        for a, b in zip(pattern, pattern[1:]):
            size = 10 if b else 26
            count *= size - 1 if a == b else size
        three += count
    assert ref["count_three_digits"] == three
