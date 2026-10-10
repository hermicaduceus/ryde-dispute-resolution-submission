"""Static accessibility audit of the HTML under ui/ (stdlib only, non-app tool).

Checks what a parser can see without a browser: document language, title, viewport meta,
a main landmark, a single h1, heading order, form controls with an accessible name,
images with alt, buttons/links with a name, duplicate ids, positive tabindex.
Pages that build their DOM in JavaScript are only audited as served; the real-browser
contrast and keyboard checks live in tests/browser/.

    python tools/a11y_static_audit.py [--ui ui] [--json out.json]

Exit 0 when no error-level finding, 1 otherwise. Warnings never fail the run.
"""
import argparse
import json
import sys
from html.parser import HTMLParser
from pathlib import Path

VOID = {"meta", "link", "input", "img", "br", "hr", "source", "area", "base", "col", "wbr"}
NAMED_INPUT_SKIP = {"hidden", "submit", "button", "reset", "image"}


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lang = None
        self.title = ""
        self.viewport = False
        self.main = False
        self.headings = []
        self.ids = []
        self.label_for = set()
        self.controls = []   # (tag, attrs, labelled_by_wrapping)
        self.imgs = []
        self.named = []      # (tag, attrs, text)
        self.positive_tabindex = 0
        self._stack = []
        self._in_title = False
        self._label_depth = 0
        self._text = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.lang = a.get("lang")
        if tag == "title":
            self._in_title = True
        if tag == "meta" and a.get("name") == "viewport":
            self.viewport = True
        if tag == "main" or a.get("role") == "main":
            self.main = True
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.headings.append(int(tag[1]))
        if "id" in a:
            self.ids.append(a["id"])
        if a.get("tabindex", "").lstrip("-").isdigit() and int(a["tabindex"]) > 0:
            self.positive_tabindex += 1
        if tag == "label":
            self._label_depth += 1
            if "for" in a:
                self.label_for.add(a["for"])
        if tag in {"input", "select", "textarea"}:
            if not (tag == "input" and a.get("type", "text") in NAMED_INPUT_SKIP):
                self.controls.append((tag, a, self._label_depth > 0))
        if tag == "img":
            self.imgs.append(a)
        if tag in {"button", "a"}:
            self._text = [tag, a, ""]
        if tag not in VOID:
            self._stack.append(tag)

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag == "label" and self._label_depth:
            self._label_depth -= 1
        if self._text and self._text[0] == tag:
            self.named.append(tuple(self._text))
            self._text = None

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._text:
            self._text[2] += data


def audit(path):
    p = Page()
    p.feed(path.read_text(encoding="utf-8"))
    out = []

    def add(level, msg):
        out.append({"level": level, "message": msg})

    if not p.lang:
        add("error", "html element has no lang")
    if not p.title.strip():
        add("error", "page has no title")
    if not p.viewport:
        add("error", "no viewport meta (breaks reflow on phones)")
    if not p.main:
        add("warn", "no main landmark")
    h1 = p.headings.count(1)
    if h1 != 1:
        add("warn", f"{h1} h1 elements (expected 1)")
    for prev, cur in zip(p.headings, p.headings[1:]):
        if cur > prev + 1:
            add("warn", f"heading level jumps h{prev} to h{cur}")
    dupes = sorted({i for i in p.ids if p.ids.count(i) > 1})
    if dupes:
        add("error", f"duplicate ids: {', '.join(dupes)}")
    if p.positive_tabindex:
        add("warn", f"{p.positive_tabindex} element(s) with positive tabindex")
    for tag, a, wrapped in p.controls:
        named = (wrapped or a.get("id") in p.label_for or a.get("aria-label")
                 or a.get("aria-labelledby") or a.get("title"))
        if not named:
            add("error", f"{tag} id={a.get('id')!r} name={a.get('name')!r} has no accessible name")
    for a in p.imgs:
        if "alt" not in a and a.get("role") != "presentation":
            add("error", f"img src={a.get('src')!r} has no alt")
    for tag, a, text in p.named:
        if not (text.strip() or a.get("aria-label") or a.get("aria-labelledby") or a.get("title")):
            add("warn", f"{tag} id={a.get('id')!r} has no static text (may be filled by script)")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ui", default="ui")
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    root = Path(args.ui)
    pages = sorted(root.rglob("*.html"))
    if not pages:
        print(f"a11y_static_audit: no HTML under {root}", file=sys.stderr)
        return 2
    report, errors = {}, 0
    for page in pages:
        findings = audit(page)
        report[page.as_posix()] = findings
        for f in findings:
            errors += f["level"] == "error"
            print(f"{f['level'].upper():5} {page.as_posix()}: {f['message']}")
    print(f"\n{len(pages)} pages, {errors} error(s), "
          f"{sum(len(v) for v in report.values()) - errors} warning(s)")
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
