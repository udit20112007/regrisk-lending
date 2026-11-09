"""
BUILD THE WEB PAGE FOR GITHUB PAGES
===================================

GitHub Pages can only serve plain files. It cannot run a Python server, so a
normal Streamlit app cannot live there.

The fix is "stlite": a version of Streamlit that runs Python inside the
visitor's own browser. This script packs the app, the code and the data into
one file, site/index.html, which GitHub Pages can serve.

Run with:   python scripts/build_site.py
The GitHub workflow (.github/workflows/deploy.yml) runs it automatically.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"

STLITE_VERSION = "1.12.1"                      # pinned so the page cannot break by surprise
CDN = f"https://cdn.jsdelivr.net/npm/@stlite/browser@{STLITE_VERSION}/build"

# Python packages the browser must install. pandas and numpy come with Streamlit.
REQUIREMENTS = ["plotly", "scipy"]

# Code and data the app needs, by their path inside the project.
CODE_FILES = [
    "app.py",
    "src/__init__.py",
    "src/event_study.py",
    "src/lending_model.py",
    "src/integration.py",
    "data/events.csv",
    "data/tickers.csv",
]

PAGE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Regulatory risk and fintech lending partnerships</title>
    <link rel="stylesheet" href="__CDN__/stlite.css" />
  </head>
  <body>
    <div id="root"></div>
    <noscript>This page needs JavaScript. It runs the model in your browser.</noscript>
    <script type="module">
      import { mount } from "__CDN__/stlite.js";
      mount(
        {
          entrypoint: "app.py",
          requirements: __REQUIREMENTS__,
          files: __FILES__,
        },
        document.getElementById("root"),
      );
    </script>
  </body>
</html>
"""


def main() -> None:
    files = {}
    for name in CODE_FILES:
        text = (ROOT / name).read_text(encoding="utf-8")
        files[name] = text if text.strip() else "# marks this folder as a Python package\n"

    # Real prices if we have them, otherwise the made-up sample (the app then
    # shows its yellow warning).
    real = ROOT / "data" / "prices.csv"
    if real.exists():
        files["data/prices.csv"] = real.read_text(encoding="utf-8")
        data_used = "REAL prices (data/prices.csv)"
    else:
        files["data/sample_prices.csv"] = (ROOT / "data" / "sample_prices.csv").read_text(encoding="utf-8")
        data_used = "SAMPLE prices (made up) - the page will show a warning"

    # Turn the files into JavaScript text. "</" is escaped so that nothing in
    # the data can accidentally close the <script> tag.
    files_js = json.dumps(files).replace("</", "<\\/")

    page = (PAGE.replace("__CDN__", CDN)
                .replace("__REQUIREMENTS__", json.dumps(REQUIREMENTS))
                .replace("__FILES__", files_js))

    SITE.mkdir(exist_ok=True)
    (SITE / "index.html").write_text(page, encoding="utf-8")

    size_kb = len(page.encode("utf-8")) / 1024
    print(f"Built site/index.html ({size_kb:.0f} KB) with {len(files)} files.")
    print(f"Data in the page: {data_used}")


if __name__ == "__main__":
    main()
