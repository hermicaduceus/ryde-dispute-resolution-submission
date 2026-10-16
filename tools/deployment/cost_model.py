"""Reproduce the presentation's assumptions, not a forecast of measured Ryde savings.

Run: python3 tools/deployment/cost_model.py
Current routing: two DeepSeek V4 Flash advocates and a V4 Pro Judge.
No role-level token usage, retry frequency or invoice has been measured here.

Reference rates checked 16 October 2026, USD per million uncached tokens:
https://www.tencentcloud.com/document/product/1300/78937
Flash 0731 GA peak: 0.44 input / 1.32 output.
Unversioned V4 Pro: 1.74 input / 3.48 output; Pro 0813 GA peak: 1.32 / 3.96.
These are alternative public rate rows, NOT proof of the apps' billed SKU.
The S$175/month provision covers the reference maximum at the ASSUMED aggregate
50,000 input and 3,500 output tokens/case, 1,333.33 cases/month, USD/SGD 1.30.
It is not a spend limit. More calls/tokens, fees or different SKUs can exceed it.
No caching benefit is assumed. ADP plan fees are excluded.
"""
import json

TOKEN_BUDGET_SGD = 175.0
BASE_CASES_MONTH = 4_000_000 / 12 * 0.01 * 0.40


def token_references():
    def cost(input_price, output_price):
        return (50_000 * input_price + 3_500 * output_price) / 1_000_000 * BASE_CASES_MONTH * 1.30
    return {
        "all_flash_ga_peak_sgd": cost(0.44, 1.32),
        "all_pro_unversioned_sgd": cost(1.74, 3.48),
        "all_pro_ga_peak_sgd": cost(1.32, 3.96),
        # Independent highest input/output prices, not a claim of an offered SKU.
        "max_reference_rates_sgd": cost(1.74, 3.96),
    }


def forecast(dispute_rate=0.01, growth=0.10, hosted=False, token_budget=TOKEN_BUDGET_SGD):
    """Same rollout as the earlier deck; only the token provision has changed.

    Embedded: build months 1-4, shadow 5-6, assist 7-9, limited autonomy 10+.
    Hosted: build 1-3, shadow 4-5, assist 6-8, limited autonomy 9+.
    All case volume, staff costs, productivity and growth are planning assumptions.
    """
    build_months = 3 if hosted else 4
    setup_total = 90_000 if hosted else 120_000
    manual_total = system_total = 0.0
    rows = []
    for month in range(1, 37):
        cases = 4_000_000 / 12 * dispute_rate * 0.40 * (1 + growth) ** ((month - 1) // 12)
        manual = cases * 7.50  # 12 min at S$37.50/hour
        if month <= build_months + 2:
            remainder = manual
        elif month <= build_months + 5:
            remainder = cases * 3.125  # assisted handling, 5 min each
        else:
            remainder = cases * 0.40 * 3.125  # 60% autonomous is assumed, not measured
        setup = setup_total / build_months if month <= build_months else 0.0
        running = 0.0
        if month > build_months:
            running = token_budget * cases / BASE_CASES_MONTH
            if hosted:
                running += 1_700  # S$500 cloud + 0.1 engineer at S$1,200
        manual_total += manual
        system_total += setup + remainder + running
        rows.append({"month": month, "manual_sgd": round(manual_total, 6),
                     "system_sgd": round(system_total, 6)})
    saving = manual_total - system_total
    return {"manual_total_sgd": manual_total, "system_total_sgd": system_total,
            "saving_sgd": saving, "roi_percent": saving / setup_total * 100,
            "payback_month": next((r["month"] for r in rows if r["system_sgd"] <= r["manual_sgd"]), None),
            "rows": rows}


def break_even_rate(growth=0.10):
    low, high = 0.0, 0.1
    for _ in range(60):
        mid = (low + high) / 2
        if forecast(dispute_rate=mid, growth=growth)["saving_sgd"] < 0:
            low = mid
        else:
            high = mid
    return high


def presentation():
    return {
        "type": "planning assumptions, not measured bills or savings",
        "routing": "Advocates: V4 Flash; Judge: V4 Pro",
        "token_budget_sgd_per_base_month": TOKEN_BUDGET_SGD,
        "token_references": token_references(),
        "embedded": forecast(), "hosted": forecast(hosted=True),
        "sensitivity": [
            {"dispute_rate": rate, "growth": growth, **forecast(dispute_rate=rate, growth=growth)}
            for rate in (0.0025, 0.005, 0.01, 0.015, 0.02) for growth in (0.0, 0.10, 0.17)
        ],
        "break_even_percent": {str(g): break_even_rate(g) * 100 for g in (0.0, 0.10)},
    }


if __name__ == "__main__":
    print(json.dumps(presentation(), indent=2))
