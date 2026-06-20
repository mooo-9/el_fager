"""
Business calculator — pure Python, no external deps.
Covers startup metrics, valuation, loan/investment math, and profitability.
"""

import math


# ── Startup / SaaS Metrics ────────────────────────────────────────────────────

def startup_metrics(mrr: float, churn_rate: float, cac: float,
                    avg_revenue_per_user: float = 0) -> str:
    """
    MRR/ARR, LTV, CAC ratio, and payback period.

    mrr           Monthly Recurring Revenue (USD/EGP)
    churn_rate    Monthly churn % (e.g. 5 for 5%)
    cac           Cost to Acquire a Customer (same currency as mrr)
    avg_revenue_per_user  If provided, used to compute LTV; else derived from mrr/churn
    """
    arr = mrr * 12
    monthly_churn = churn_rate / 100

    if monthly_churn <= 0:
        ltv_str = "infinite (0% churn)"
        ltv_cac_str = "N/A"
        payback_str = "N/A"
    else:
        arpu = avg_revenue_per_user if avg_revenue_per_user > 0 else (mrr / max(1, mrr / max(cac, 1)))
        ltv = arpu / monthly_churn
        ltv_cac = ltv / cac if cac > 0 else float("inf")
        payback = cac / (arpu * (1 - monthly_churn)) if arpu > 0 else float("inf")
        ltv_str = f"{ltv:,.0f}"
        ltv_cac_str = f"{ltv_cac:.1f}x  {'GOOD (>3x)' if ltv_cac >= 3 else 'LOW (<3x)'}"
        payback_str = f"{payback:.1f} months  {'GOOD (<12mo)' if payback < 12 else 'LONG (>12mo)'}"

    return (
        f"Startup metrics:\n"
        f"  MRR:           {mrr:,.0f}\n"
        f"  ARR:           {arr:,.0f}\n"
        f"  Monthly churn: {churn_rate:.1f}%\n"
        f"  CAC:           {cac:,.0f}\n"
        f"  LTV:           {ltv_str}\n"
        f"  LTV/CAC:       {ltv_cac_str}\n"
        f"  Payback:       {payback_str}\n"
        f"  Benchmark: LTV/CAC > 3x, payback < 12 months = healthy SaaS"
    )


def burn_runway(monthly_burn: float, cash: float) -> str:
    """Runway in months and date."""
    if monthly_burn <= 0:
        return "Burn rate is 0 or negative — not burning cash."
    runway_months = cash / monthly_burn
    from datetime import date, timedelta
    runway_date = date.today() + timedelta(days=int(runway_months * 30.44))
    status = "CRITICAL (<6mo)" if runway_months < 6 else ("RAISE NOW (<12mo)" if runway_months < 12 else "HEALTHY (>12mo)")
    return (
        f"Burn & runway:\n"
        f"  Monthly burn:  {monthly_burn:,.0f}\n"
        f"  Cash on hand:  {cash:,.0f}\n"
        f"  Runway:        {runway_months:.1f} months  ({status})\n"
        f"  Zero date:     {runway_date.strftime('%B %Y')}\n"
        f"  Raise target:  aim for 18-24 months runway post-raise"
    )


# ── Profitability ─────────────────────────────────────────────────────────────

def break_even(fixed_costs: float, variable_cost_per_unit: float,
               price_per_unit: float) -> str:
    """Break-even units and revenue."""
    contribution_margin = price_per_unit - variable_cost_per_unit
    if contribution_margin <= 0:
        return "Error: price must be higher than variable cost per unit."
    be_units = fixed_costs / contribution_margin
    be_revenue = be_units * price_per_unit
    cm_ratio = (contribution_margin / price_per_unit) * 100
    return (
        f"Break-even analysis:\n"
        f"  Fixed costs:         {fixed_costs:,.0f}\n"
        f"  Variable cost/unit:  {variable_cost_per_unit:,.2f}\n"
        f"  Price/unit:          {price_per_unit:,.2f}\n"
        f"  Contribution margin: {contribution_margin:,.2f} ({cm_ratio:.1f}% of price)\n"
        f"  Break-even units:    {be_units:,.0f}\n"
        f"  Break-even revenue:  {be_revenue:,.0f}"
    )


def margin_analysis(revenue: float, cogs: float, operating_expenses: float,
                    tax_rate: float = 22.5) -> str:
    """Full P&L margin waterfall."""
    gross_profit = revenue - cogs
    ebit = gross_profit - operating_expenses
    tax = max(0, ebit * (tax_rate / 100))
    net_income = ebit - tax

    def pct(v): return f"{(v/revenue*100):+.1f}%" if revenue else "N/A"

    return (
        f"Margin analysis:\n"
        f"  Revenue:             {revenue:,.0f}  (100%)\n"
        f"  COGS:               -{cogs:,.0f}  ({cogs/revenue*100:.1f}% of rev)\n"
        f"  Gross profit:        {gross_profit:,.0f}  ({gross_profit/revenue*100:.1f}%)\n"
        f"  OpEx:               -{operating_expenses:,.0f}\n"
        f"  EBIT (op. income):   {ebit:,.0f}  ({pct(ebit)})\n"
        f"  Tax ({tax_rate}%):          -{tax:,.0f}\n"
        f"  Net income:          {net_income:,.0f}  ({pct(net_income)})\n"
        f"  Benchmarks: gross >40%, EBIT >15%, net >10% = healthy"
    )


def roi_calc(investment: float, gross_return: float, years: float = 1) -> str:
    """ROI, annualised ROI, and payback period."""
    profit = gross_return - investment
    roi = (profit / investment) * 100 if investment else 0
    ann_roi = ((gross_return / investment) ** (1 / years) - 1) * 100 if investment and years > 0 else 0
    payback = investment / (profit / years) if profit > 0 else float("inf")
    return (
        f"ROI analysis:\n"
        f"  Investment:      {investment:,.0f}\n"
        f"  Gross return:    {gross_return:,.0f}\n"
        f"  Net profit:      {profit:,.0f}\n"
        f"  ROI:             {roi:.1f}%\n"
        f"  Annualised ROI:  {ann_roi:.1f}% (over {years:.1f} year(s))\n"
        f"  Payback period:  {payback:.1f} year(s)"
    )


# ── Valuation ─────────────────────────────────────────────────────────────────

def dcf_value(cash_flows: list, discount_rate: float,
              terminal_growth: float = 2.0) -> str:
    """
    DCF intrinsic value.

    cash_flows      List of projected annual cash flows
    discount_rate   WACC or required return % (e.g. 10)
    terminal_growth Perpetual growth rate % for terminal value (default 2%)
    """
    r = discount_rate / 100
    g = terminal_growth / 100

    pv_flows = []
    for i, cf in enumerate(cash_flows, 1):
        pv = cf / ((1 + r) ** i)
        pv_flows.append(pv)

    pv_sum = sum(pv_flows)
    terminal_cf = cash_flows[-1] * (1 + g)
    terminal_value = terminal_cf / (r - g) if r > g else 0
    pv_terminal = terminal_value / ((1 + r) ** len(cash_flows))
    total_value = pv_sum + pv_terminal

    lines = ["DCF valuation:"]
    lines.append(f"  Discount rate (WACC): {discount_rate}%")
    lines.append(f"  Terminal growth:      {terminal_growth}%")
    lines.append(f"  Year-by-year PV:")
    for i, (cf, pv) in enumerate(zip(cash_flows, pv_flows), 1):
        lines.append(f"    Year {i}: CF={cf:,.0f}  PV={pv:,.0f}")
    lines.append(f"  PV of cash flows:     {pv_sum:,.0f}")
    lines.append(f"  Terminal value (PV):  {pv_terminal:,.0f}")
    lines.append(f"  Intrinsic value:      {total_value:,.0f}")
    return "\n".join(lines)


def valuation_multiples(revenue: float = 0, ebitda: float = 0,
                        net_income: float = 0,
                        rev_multiple: float = 0, ebitda_multiple: float = 0,
                        pe_multiple: float = 0) -> str:
    """
    Business valuation from revenue/EBITDA/P-E multiples.
    Pass the metrics you have; zero values are skipped.
    """
    lines = ["Valuation by multiples:"]
    if revenue > 0 and rev_multiple > 0:
        lines.append(f"  Revenue multiple:  {revenue:,.0f} x {rev_multiple}x = {revenue*rev_multiple:,.0f}")
    if ebitda > 0 and ebitda_multiple > 0:
        lines.append(f"  EBITDA multiple:   {ebitda:,.0f} x {ebitda_multiple}x = {ebitda*ebitda_multiple:,.0f}")
    if net_income > 0 and pe_multiple > 0:
        lines.append(f"  P/E multiple:      {net_income:,.0f} x {pe_multiple}x = {net_income*pe_multiple:,.0f}")
    if len(lines) == 1:
        return "Provide at least one metric + multiple (e.g. revenue=5000000, rev_multiple=3)."
    lines.append("  Benchmarks (Egypt): SaaS 3-8x rev | Retail 0.5-1.5x rev | Services 2-5x EBITDA")
    lines.append("  Benchmarks (US):    SaaS 5-15x rev | Tech 20-40x P/E | Industrials 8-12x EBITDA")
    return "\n".join(lines)


# ── Loan & Time-Value Math ────────────────────────────────────────────────────

def loan_payment(principal: float, annual_rate: float, months: int) -> str:
    """Monthly EMI, total paid, and total interest."""
    r = annual_rate / 100 / 12
    if r == 0:
        emi = principal / months
    else:
        emi = principal * r * (1 + r) ** months / ((1 + r) ** months - 1)
    total_paid = emi * months
    total_interest = total_paid - principal
    return (
        f"Loan amortisation:\n"
        f"  Principal:       {principal:,.0f}\n"
        f"  Annual rate:     {annual_rate:.2f}%\n"
        f"  Term:            {months} months ({months/12:.1f} years)\n"
        f"  Monthly payment: {emi:,.2f}\n"
        f"  Total paid:      {total_paid:,.0f}\n"
        f"  Total interest:  {total_interest:,.0f} ({total_interest/principal*100:.1f}% of principal)"
    )


def compound_growth(initial: float, annual_rate: float, years: float,
                    monthly_addition: float = 0) -> str:
    """Future value with optional monthly contributions (compound interest)."""
    r_monthly = annual_rate / 100 / 12
    months = int(years * 12)

    # Lump sum component
    fv_lump = initial * (1 + r_monthly) ** months

    # Monthly contribution component
    if r_monthly > 0 and monthly_addition > 0:
        fv_contrib = monthly_addition * ((1 + r_monthly) ** months - 1) / r_monthly
    else:
        fv_contrib = monthly_addition * months

    fv_total = fv_lump + fv_contrib
    total_invested = initial + monthly_addition * months
    total_gain = fv_total - total_invested

    return (
        f"Compound growth:\n"
        f"  Initial:            {initial:,.0f}\n"
        f"  Annual rate:        {annual_rate:.1f}%\n"
        f"  Period:             {years:.1f} years\n"
        f"  Monthly addition:   {monthly_addition:,.0f}\n"
        f"  Total invested:     {total_invested:,.0f}\n"
        f"  Future value:       {fv_total:,.0f}\n"
        f"  Total gain:         {total_gain:,.0f} ({total_gain/total_invested*100:.1f}% on invested)\n"
        f"  Rule of 72: doubles every {72/annual_rate:.1f} years at {annual_rate:.1f}%"
    )


def cagr_calc(start_value: float, end_value: float, years: float) -> str:
    """Compound Annual Growth Rate between two values."""
    if start_value <= 0 or years <= 0:
        return "Error: start value and years must be positive."
    cagr = ((end_value / start_value) ** (1 / years) - 1) * 100
    total_return = (end_value / start_value - 1) * 100
    return (
        f"CAGR:\n"
        f"  Start:        {start_value:,.0f}\n"
        f"  End:          {end_value:,.0f}\n"
        f"  Period:       {years:.1f} years\n"
        f"  Total return: {total_return:.1f}%\n"
        f"  CAGR:         {cagr:.2f}%"
    )
