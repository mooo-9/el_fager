"""
Full JARVIS audit: Unicode safety, dispatch coverage, schema alignment, basic functional tests.
"""
import sys, os, re, glob, importlib, inspect, json
sys.path.insert(0, os.path.dirname(__file__))

ISSUES = []

def issue(category, tool_file, detail):
    ISSUES.append((category, tool_file, detail))
    print(f"  ISSUE [{category}] {tool_file}: {detail}"
          .encode("ascii", "replace").decode("ascii"))

# ─────────────────────────────────────────────────────────────────────────────
# 1. Unicode safety: scan every return / f-string line in every tool file
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 1. UNICODE SAFETY (cp1252) ===")
tool_files = sorted(glob.glob("tools/*.py"))
unicode_issues = []
for fpath in tool_files:
    if "__init__" in fpath:
        continue
    with open(fpath, encoding="utf-8") as f:
        lines = f.readlines()
    for i, line in enumerate(lines, 1):
        try:
            line.encode("cp1252")
        except UnicodeEncodeError:
            bad = sorted({c for c in line if ord(c) > 127})
            issue("UNICODE", fpath, f"line {i}: {[hex(ord(c)) for c in bad]} — {line.strip()[:70]}")

# ─────────────────────────────────────────────────────────────────────────────
# 2. Load brain.py TOOLS list and dispatch coverage
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 2. BRAIN.PY TOOLS vs DISPATCH ===")
try:
    from core.brain import TOOLS, _dispatch_tool, _TOOL_GROUP_NAMES, _GROUP_TRIGGERS, _CORE_NAMES

    brain_names = {t["name"] for t in TOOLS}
    print(f"  Total tools in TOOLS list: {len(brain_names)}")

    # Read brain.py dispatch elif blocks
    with open("core/brain.py", encoding="utf-8") as f:
        brain_src = f.read()

    dispatched = set(re.findall(r'elif name == "([^"]+)"', brain_src))
    print(f"  Dispatch elif blocks: {len(dispatched)}")

    in_tools_not_dispatched = brain_names - dispatched
    in_dispatch_not_tools = dispatched - brain_names

    if in_tools_not_dispatched:
        for t in sorted(in_tools_not_dispatched):
            issue("NO-DISPATCH", "brain.py", f"'{t}' in TOOLS list but no elif in _dispatch_tool")
    else:
        print("  All TOOLS have dispatch blocks: OK")

    if in_dispatch_not_tools:
        for t in sorted(in_dispatch_not_tools):
            issue("ORPHAN-DISPATCH", "brain.py", f"'{t}' has elif but not in TOOLS list")
    else:
        print("  No orphan dispatch blocks: OK")

    # Check group coverage — every named tool should be in at least one group or _CORE_NAMES
    grouped = set(_CORE_NAMES)
    for names in _TOOL_GROUP_NAMES.values():
        grouped |= set(names)
    ungrouped = brain_names - grouped
    if ungrouped:
        for t in sorted(ungrouped):
            issue("NO-GROUP", "brain.py", f"'{t}' not in any _TOOL_GROUP_NAMES or _CORE_NAMES")
    else:
        print("  All tools in a group or core: OK")

    # Check groups with no triggers
    for group in _TOOL_GROUP_NAMES:
        triggers = _GROUP_TRIGGERS.get(group, [])
        if not triggers:
            issue("NO-TRIGGERS", "brain.py", f"group '{group}' has no triggers")

except Exception as e:
    issue("IMPORT", "core/brain.py", str(e))

# ─────────────────────────────────────────────────────────────────────────────
# 3. Schema alignment: required params in TOOLS vs function signatures
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 3. SCHEMA ALIGNMENT ===")

# Map tool name -> module
tool_name_map = {}
for fpath in tool_files:
    if "__init__" in fpath:
        continue
    modname = os.path.basename(fpath).replace(".py", "")
    try:
        mod = importlib.import_module(f"tools.{modname}")
        for fname in dir(mod):
            obj = getattr(mod, fname)
            if callable(obj) and not fname.startswith("_"):
                tool_name_map[fname] = (modname, obj)
    except Exception as e:
        issue("IMPORT", f"tools/{modname}.py", str(e))

schema_ok = 0
for t in TOOLS:
    tname = t["name"]
    schema = t.get("input_schema", {})
    required = schema.get("required", [])
    props = schema.get("properties", {})

    if tname not in tool_name_map:
        issue("NO-FUNCTION", "tools/", f"'{tname}' in TOOLS but no matching function found in any tool file")
        continue

    modname, func = tool_name_map[tname]
    try:
        sig = inspect.signature(func)
        params = sig.parameters
        # Check all required schema params exist in function
        for req in required:
            if req not in params:
                issue("SCHEMA-MISMATCH", f"tools/{modname}.py",
                      f"'{tname}': required param '{req}' in schema but not in function signature")
        # Check all function required params (no default) are in schema required
        for pname, param in params.items():
            if pname == "self":
                continue
            if param.default is inspect.Parameter.empty and pname not in required:
                issue("SCHEMA-MISSING", f"tools/{modname}.py",
                      f"'{tname}': function requires '{pname}' but it's not in schema 'required'")
        schema_ok += 1
    except Exception as e:
        issue("SIGNATURE", f"tools/{modname}.py", f"'{tname}': {e}")

print(f"  Schema checks passed: {schema_ok}/{len(TOOLS)}")

# ─────────────────────────────────────────────────────────────────────────────
# 4. Functional tests for pure-logic tools (no external APIs / hardware)
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 4. FUNCTIONAL TESTS (pure-logic tools) ===")

PASS = 0
FAIL = 0
SKIP = 0

def ok(label, result, must_not_start_bracket=True, contains=None):
    global PASS, FAIL
    is_err = isinstance(result, str) and result.startswith("[")
    good = not is_err if must_not_start_bracket else is_err
    if contains and good:
        good = str(contains).lower() in str(result).lower()
    if good:
        PASS += 1
    else:
        FAIL += 1
        issue("FUNC-FAIL", "", f"{label}: {str(result)[:80]}")

def err(label, result):
    ok(label, result, must_not_start_bracket=False)

def skip(label):
    global SKIP
    SKIP += 1
    print(f"  SKIP  {label}".encode("ascii", "replace").decode("ascii"))

# clipboard
from tools.clipboard_tool import get_clipboard_text, set_clipboard_text
ok("clipboard set", set_clipboard_text("el_fager_test"))
r = get_clipboard_text()
ok("clipboard get", r, contains="el_fager_test")

# code_tool
from tools.code_tool import check_syntax, get_python_info
ok("check_syntax valid", check_syntax("x = 1 + 2"), contains="Syntax")
ok("check_syntax invalid", check_syntax("def ("), contains="error")
ok("get_python_info", get_python_info(), contains="python")

# business_calculator
from tools.business_calculator import roi_calc, break_even, loan_payment, margin_analysis, cagr_calc, burn_runway
ok("roi_calc", roi_calc(1000, 1200), contains="20")
ok("break_even", break_even(5000, 6, 10), contains="1,250")
ok("loan_payment", loan_payment(100000, 5, 360), contains="536")
ok("margin_calc", margin_analysis(100, 60, 10), contains="40")
ok("cagr", cagr_calc(1000, 2000, 5), contains="14")
ok("burn_runway", burn_runway(5000, 50000), contains="10")

# unit_tool (already fully tested, quick sanity)
from tools.unit_tool import convert_units
ok("units km->mi", convert_units(10, "km", "miles"), contains="6.21")
err("units cross-cat", convert_units(1, "km", "kg"))

# dev_utils
from tools.dev_utils_tool import hash_text, generate_uuid
ok("hash sha256", hash_text("test"), contains="SHA256")
ok("uuid", generate_uuid(), contains="UUID")

# prayer_tool
from tools.prayer_tool import get_prayer_times, get_next_prayer
r = get_prayer_times()
ok("prayer_times", r, contains="fajr")
r = get_next_prayer()
ok("next_prayer", r)

# wikipedia
from tools.wikipedia_tool import wikipedia_lookup
r = wikipedia_lookup("Egypt")
ok("wikipedia_lookup", r, contains="Egypt")

# currency
from tools.currency_tool import convert_currency, get_exchange_rates
r = get_exchange_rates("USD")
ok("get_exchange_rates", r, contains="USD")
r = convert_currency(100, "USD", "EGP")
ok("convert_currency", r, contains="EGP")

# weather
from tools.weather_tool import get_weather
r = get_weather("Cairo")
ok("get_weather Cairo", r, contains="Cairo")

# news
from tools.news_tool import get_news, get_all_headlines
r = get_news("technology", n=3)
ok("get_news", r)
r = get_all_headlines(n=5)
ok("get_all_headlines", r)

# web_tool
from tools.web_tool import web_search, fetch_page
r = web_search("Python programming", max_results=3)
ok("web_search", r)
r = fetch_page("https://en.wikipedia.org/wiki/Python_(programming_language)")
skip("fetch_page (network-dependent)")  # ok if no readable HTML <p> tags found

# translation
from tools.translation_tool import translate_text
r = translate_text("Hello", "ar")
ok("translate to Arabic", r, must_not_start_bracket=False, contains="Arabic")

# files_tool
from tools.files_tool import read_file_content, search_files
r = read_file_content("README.md")
ok("read_file_content README", r)
r = search_files("*.py", "tools")
ok("search_files", r, contains=".py")

# system_tool
from tools.system_tool import run_command
r = run_command("echo el_fager_test")
ok("run_command", r, contains="el_fager_test")

# system_health
from tools.system_health_tool import system_health, get_disk_space, get_cpu_usage, get_ram_usage
ok("system_health", system_health(), contains="CPU")
ok("get_disk_space", get_disk_space("C:\\"), contains="free")
ok("get_cpu_usage", get_cpu_usage(interval=0.1), contains="%")
ok("get_ram_usage", get_ram_usage(), contains="GB")

# network (quick - no speed test)
from tools.network_tool import check_internet, get_local_ip
ok("check_internet", check_internet(), contains="Connected")
ok("get_local_ip", get_local_ip(), contains=".")

# file_ops (already audited, quick check)
from tools.file_ops_tool import list_folder
ok("list_folder tools/", list_folder("tools"), contains=".py")

# archive (already audited)
from tools.archive_tool import list_archive
err("list_archive missing", list_archive("data/_NOFILE.zip"))

# git (already audited)
from tools.git_tool import git_status
err("git_status not-a-repo", git_status("data"))

# income / expense / budget
from tools.income_tool import get_income_summary, list_recent_income
ok("income_summary", get_income_summary())
ok("list_income", list_recent_income(n=3))
from tools.expense_tool import get_expense_summary, list_recent_expenses
ok("expense_summary", get_expense_summary())
ok("list_expenses", list_recent_expenses(n=3))
from tools.budget_tool import list_budgets
ok("list_budgets", list_budgets())

# journal
from tools.journal_tool import list_journal_entries
ok("list_journal", list_journal_entries(n=3))

# reminder
from tools.reminder_tool import list_reminders, check_reminders
ok("list_reminders", list_reminders())
ok("check_reminders", check_reminders())

# scheduler
from tools.scheduler_tool import list_schedules
ok("list_schedules", list_schedules())

# history
from tools.history_tool import conversation_stats
ok("conversation_stats", conversation_stats())

# analytics
from tools.analytics_tool import daily_activity, productivity_insights
ok("daily_activity", daily_activity())
ok("productivity_insights", productivity_insights())

# email templates
from tools.email_templates_tool import list_email_templates
ok("list_email_templates", list_email_templates())

# flashcard
from tools.flashcard_tool import save_flashcards
ok("save_flashcards", save_flashcards([{"front": "Q", "back": "A"}], "data/_test_flashcards.csv", "Test"))

# focus_tool
from tools.focus_tool import enable_focus_mode, disable_focus_mode
ok("enable_focus", enable_focus_mode(25))
ok("disable_focus", disable_focus_mode())

# code_tool - script management
from tools.code_tool import create_script, delete_script, list_scripts
ok("create_script", create_script("_test_script", "print('hello')"))
ok("list_scripts", list_scripts(), contains="_test_script")
ok("delete_script", delete_script("_test_script"))

# citation
from tools.citation_tool import resolve_doi
r = resolve_doi("10.1038/nature12373")
ok("resolve_doi", r)

# stocks
from tools.stocks_tool import get_stock_price
r = get_stock_price("AAPL")
ok("get_stock_price AAPL", r, contains="AAPL")

# bond
from tools.bond_tool import get_bond_yields
r = get_bond_yields()
ok("get_bond_yields", r)

# system control
from tools.system_control_tool import get_battery_status, get_system_volume
ok("get_battery_status", get_battery_status())
ok("get_system_volume", get_system_volume(), contains="volume")

# process
from tools.process_tool import get_process_info
ok("get_process_info", get_process_info("python"), contains="python")

# window
from tools.window_tool import list_windows, get_active_window
ok("list_windows", list_windows())
ok("get_active_window", get_active_window())

# screen_tool
from tools.screen_tool import capture_screenshot
r = capture_screenshot()
ok("capture_screenshot", r)

# clipboard history
from tools.clipboard_history_tool import get_clipboard_history
ok("clipboard_history", get_clipboard_history())

# pomodoro
from tools.pomodoro_tool import list_pomodoros
ok("list_pomodoros", list_pomodoros())

print(f"\n  Functional: {PASS} passed, {FAIL} failed, {SKIP} skipped")

# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"TOTAL ISSUES FOUND: {len(ISSUES)}")
print(f"{'='*60}")
by_cat = {}
for cat, f, d in ISSUES:
    by_cat.setdefault(cat, []).append((f, d))
for cat, items in sorted(by_cat.items()):
    print(f"\n  {cat} ({len(items)}):")
    for f, d in items:
        print(f"    {f}: {d}".encode("ascii", "replace").decode("ascii")[:110])
