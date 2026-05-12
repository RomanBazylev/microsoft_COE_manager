"""
tip_renderer.py — fills the HTML template with tip data and screenshots it via Playwright.

Produces: docs/tip_YYYYMMDD.png (1200x675px)
Returns: file path string, or None on failure.
"""
import html
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

CARD_WIDTH  = 1200
CARD_HEIGHT = 675
DOCS_DIR    = Path("docs")
ASSETS_DIR  = Path("assets")
TEMPLATE    = ASSETS_DIR / "tip_template.html"


def _esc(text: str) -> str:
    return html.escape(str(text or ""), quote=True)


def _format_code(code_str: str) -> str:
    """Light syntax highlighting via HTML spans — Apex / SOQL / JSON."""
    if not code_str:
        return ""
    code = html.escape(code_str)

    # Keywords
    keywords = (
        r'\b(String|Integer|Boolean|List|Map|Set|void|return|new|null|true|false|'
        r'public|private|global|static|final|class|interface|extends|implements|'
        r'if|else|for|while|try|catch|finally|throw|this|super|'
        r'SELECT|FROM|WHERE|AND|OR|NOT|IN|LIKE|LIMIT|ORDER|BY|GROUP|HAVING|'
        r'INSERT|UPDATE|DELETE|UPSERT|MERGE|CREATE|WITH|SHARING|SECURITY_ENFORCED)\b'
    )
    code = re.sub(keywords, r'<span class="kw">\1</span>', code)

    # Salesforce types
    code = re.sub(
        r'\b(Account|Contact|Lead|Opportunity|Case|User|SObject|Database|System|Schema|Trigger|ApexPages)\b',
        r'<span class="ty">\1</span>', code
    )

    # Strings (single-quoted, HTML-escaped)
    code = re.sub(r"(&#39;[^&#]*&#39;)", r'<span class="st">\1</span>', code)
    # Strings (double-quoted)
    code = re.sub(r'(&quot;[^&]*&quot;)', r'<span class="st">\1</span>', code)

    # Comments
    code = re.sub(r'(//[^\n]*)', r'<span class="cm">\1</span>', code)

    # Numbers
    code = re.sub(r'\b(\d+)\b', r'<span class="nu">\1</span>', code)

    return code


def _build_code_section(tip_data: dict) -> str:
    before = tip_data.get("before_code")
    after  = tip_data.get("after_code")

    if not before or not after:
        summary    = _esc(tip_data.get("benefit") or tip_data.get("subtitle") or "")
        source_url = _esc(tip_data.get("source_url", ""))
        link = f'<a class="read-more" href="{source_url}">Read the full article →</a>' if source_url else ""
        return f"""
  <div class="fallback-body">
    <div class="fallback-content">
      <p>{summary}</p>
      {link}
    </div>
  </div>"""

    before_label = _esc(tip_data.get("before_label") or "BEFORE — The Old Way")
    after_label  = _esc(tip_data.get("after_label")  or "AFTER — Better Way")

    return f"""
  <div class="code-section">
    <div class="code-block before">
      <div class="code-header"><span class="code-dot"></span>{before_label}</div>
      <pre>{_format_code(before)}</pre>
    </div>
    <div class="code-block after">
      <div class="code-header"><span class="code-dot"></span>{after_label}</div>
      <pre>{_format_code(after)}</pre>
    </div>
  </div>"""


def _build_use_cases_html(use_cases: list) -> str:
    if not use_cases:
        return ""
    items = "".join(f"<li>{_esc(uc)}</li>" for uc in use_cases[:4])
    return f"""
    <div class="use-cases">
      <div class="use-cases-title">Real Use Cases</div>
      <ul>{items}</ul>
    </div>"""


def render_tip(item: dict) -> str | None:
    """
    Renders the tip PNG from item["tip_data"].
    Saves to docs/tip_YYYYMMDD.png  (or item["png_filename"]).
    Returns the file path string, or None on failure.
    """
    tip_data = item.get("tip_data", {})
    if not tip_data:
        print("[Renderer] No tip_data in item — skipping render")
        return None

    if not TEMPLATE.exists():
        print(f"[Renderer] Template not found: {TEMPLATE}")
        return None

    template_html = TEMPLATE.read_text(encoding="utf-8")
    today_str = datetime.now(timezone.utc).strftime("%B %d, %Y")

    filled = (
        template_html
        .replace("{{TITLE}}",          _esc(tip_data.get("title", "Salesforce Tip")))
        .replace("{{SUBTITLE}}",       _esc(tip_data.get("subtitle", "")))
        .replace("{{LABEL}}",          _esc(tip_data.get("label", "Tip of the Day")))
        .replace("{{CODE_SECTION}}",   _build_code_section(tip_data))
        .replace("{{USE_CASES_HTML}}", _build_use_cases_html(tip_data.get("use_cases", [])))
        .replace("{{BENEFIT}}",        _esc(tip_data.get("benefit", "")))
        .replace("{{SOURCE_DOMAIN}}", _esc(tip_data.get("source_domain", "")))
        .replace("{{DATE}}",           today_str)
    )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(filled)
        tmp_path = Path(tmp.name)

    DOCS_DIR.mkdir(exist_ok=True)
    out_png = DOCS_DIR / item.get("png_filename", "tip_today.png")

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": CARD_WIDTH, "height": CARD_HEIGHT})
            page.goto(tmp_path.resolve().as_uri(), wait_until="networkidle", timeout=30000)
            page.screenshot(
                path=str(out_png),
                clip={"x": 0, "y": 0, "width": CARD_WIDTH, "height": CARD_HEIGHT},
            )
            browser.close()

        print(f"[Renderer] PNG saved → {out_png} ({out_png.stat().st_size // 1024}KB)")
        return str(out_png)

    except ImportError:
        print("[Renderer] playwright not installed (pip install playwright)")
        return None
    except Exception as e:
        print(f"[Renderer] Error: {e}")
        return None
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    test_item = {
        "png_filename": "tip_test.png",
        "tip_data": {
            "title": "Apex Multiline Strings",
            "subtitle": "Summer '26 introduces triple-quoted text blocks — no more \\n concatenation.",
            "label": "Apex",
            "before_label": "BEFORE — The Old Way 😩",
            "after_label":  "AFTER — Summer '26 ✅",
            "before_code": (
                "String body = 'Dear Customer,\\n' +\n"
                "    'Thank you for your order.\\n' +\n"
                "    'Regards, Team';"
            ),
            "after_code": (
                "String body = '''\n"
                "    Dear Customer,\n"
                "    Thank you for your order.\n"
                "    Regards, Team\n"
                "    ''';"
            ),
            "use_cases": [
                "SOQL queries with multiple fields",
                "JSON payloads for API callouts",
                "HTML email templates",
                "Debug log messages",
            ],
            "benefit": "Clean, readable code. No more \\n escaping or string concatenation issues.",
            "source_url": "https://salesforcemonday.com/",
            "source_domain": "salesforcemonday.com",
        },
    }
    path = render_tip(test_item)
    if path:
        print(f"\nOpen to preview: {Path(path).resolve()}")
    else:
        print("\nRender failed — check Playwright installation.")
