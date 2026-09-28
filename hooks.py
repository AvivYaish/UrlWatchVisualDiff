"""Add `- browserdiff` as the first filter of a job JOBNAME to save .html page diffs in $XDG_CONFIG_HOME/urlwatch/BrowserDiff/JobName"""
from datetime import datetime
from pathlib import Path
import re
import sys

from lxml import etree, html
from lxml.html.diff import htmldiff
from urlwatch.filters import FilterBase
from urlwatch.reporters import StdoutReporter

MAX_REPORTS = 5  # .html files to keep per job


def page_diff(old, new, url):
    previous, current = (html.document_fromstring(text, parser=html.HTMLParser(remove_comments=True)) for text in (old, new))
    for document in (previous, current):
        document.make_links_absolute(url)
        etree.strip_elements(document, "script", "iframe", "object", "embed", "base", "meta", with_tail=False)
        for attribute in document.xpath("//@*[starts-with(name(), 'on')]"):
            del attribute.getparent().attrib[attribute.attrname]
        etree.strip_tags(document, "ins", "del")
    body = html.fragment_fromstring(htmldiff(previous.body, current.body), create_parent="body")
    if not body.xpath(".//ins | .//del"):
        return ""
    body.attrib.update(current.body.attrib)
    current.replace(current.body, body)
    if current.head is None:
        current.insert(0, html.Element("head"))
    charset, policy, style = html.fragments_fromstring("""
        <meta charset="utf-8">
        <meta http-equiv="Content-Security-Policy" content="script-src 'none'; object-src 'none'; frame-src 'none'; form-action 'none'">
        <style>ins{background:#fff09a!important;text-decoration:none!important}
        del{background:#ffd9dc!important;text-decoration:line-through!important}</style>
    """)
    current.head[:0] = [charset, policy]
    current.head.append(style)
    return html.tostring(current, encoding="unicode", doctype="<!DOCTYPE html>")


class BrowserDiffFilter(FilterBase):
    """Pass original content to the next filter"""
    __kind__, __no_subfilter__ = "browserdiff", True

    def filter(self, data, subfilter):
        if not isinstance(data, str) or not re.search(r"<(?:html|body)\b", data, re.I):
            raise ValueError("browserdiff needs an HTML page, place it before html2text.")
        self.state.browserdiff = data
        return data


class BrowserDiffStdout(StdoutReporter):
    """Add browser links at the top of the stdout output"""

    def submit(self):
        for state in self.job_states:
            if not hasattr(state, "browserdiff") or state.exception is not None:
                continue
            new = state.browserdiff
            name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", state.job.pretty_name()).rstrip(". ") or "job"
            directory = Path(__file__).resolve().parent / "BrowserDiff" / name
            directory.mkdir(parents=True, exist_ok=True)
            baseline = directory / "last.html"
            old = baseline.read_text(encoding="utf-8") if baseline.exists() else new
            state.browserdiff_link = ""
            if state.verb == "changed" and old != new and state.get_diff():
                result = page_diff(old, new, state.job.get_location())
                if result:
                    output = directory / f"{datetime.now():%Y-%m-%d_%H-%M-%S-%f}.diff.html"
                    output.write_text(result, encoding="utf-8")
                    state.browserdiff_link = output.as_uri()
            baseline.write_text(new, encoding="utf-8")
            for expired in sorted(directory.glob("*.diff.html"), reverse=True)[MAX_REPORTS:]:
                expired.unlink()
        super().submit()

    def _format_content(self, state):
        content = super()._format_content(state)
        link = getattr(state, "browserdiff_link", "")
        if content and link:
            if sys.stdout.isatty():
                link = f"\033]8;;{link}\033\\open\033]8;;\033\\"
            content = f"Browser diff: {link}\n\n{content}"
        return content
