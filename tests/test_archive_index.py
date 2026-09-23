"""Tests for SEC archive index parsing and Certificate-of-Designation exhibit
resolution (the live-leg of the contract-clause pipeline)."""

import pytest

from src.crispdm.sec_client import (
    _parse_archive_directory_html,
    _parse_archive_index_html,
)

from scripts.populate_contract_terms import find_certificate_exhibit


INDEX_HTML = """<!DOCTYPE html><html><head><title>Filing Detail</title></head>
<body>
<h1>Form 8-K - Current report</h1>
<table class="tableFile">
<tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>
<tr><td>1</td><td>8-K</td><td>acr-20260831.htm</td><td>iXBRL 8-K</td><td>73988</td></tr>
<tr><td>2</td><td>EX-3.1</td><td>ex31_seriesd.htm</td><td>EX-3.1</td><td>412345</td></tr>
<tr><td>3</td><td>EX-3.2</td><td>ex32_amendment.htm</td><td>EX-3.2</td><td>270023</td></tr>
<tr><td>4</td><td>EX-5.1</td><td>ex51.htm</td><td>EX-5.1</td><td>34013</td></tr>
<tr><td>5</td><td>GRAPHIC</td><td>img00001.jpg</td><td>GRAPHIC</td><td>9927</td></tr>
<tr><td colspan="5">19 Complete submission text file 0001193125-26-382349.txt</td></tr>
</table>
</body></html>"""

DIRECTORY_HTML = """<!DOCTYPE html><html><body>
<h1>Index of /edgar/data/1332551/000119312526382349</h1>
<p><a href="/edgar/data/1332551/000119312526382349/..">..</a></p>
<p><a href="/edgar/data/1332551/000119312526382349/acr-20260831.htm">acr-20260831.htm</a></p>
<p><a href="/edgar/data/1332551/000119312526382349/ex31_seriesd.htm">ex31_seriesd.htm</a></p>
<p><a href="/edgar/data/1332551/000119312526382349/ex32_amendment.htm">ex32_amendment.htm</a></p>
<p>Javascript-toggled content hidden.</p>
</body></html>"""


def test_parse_archive_index_html_rows():
    items = _parse_archive_index_html(INDEX_HTML)
    assert ("8-K", "acr-20260831.htm", "iXBRL 8-K") in items
    assert ("EX-3.1", "ex31_seriesd.htm", "EX-3.1") in items
    assert ("EX-3.2", "ex32_amendment.htm", "EX-3.2") in items
    assert ("EX-5.1", "ex51.htm", "EX-5.1") in items


def test_parse_archive_index_html_skips_header_and_spans():
    items = _parse_archive_index_html(INDEX_HTML)
    names = [name for _desc, name, _type in items]
    assert "Document" not in names
    assert all(name.count(".") >= 1 for name in names)


def test_parse_archive_directory_html():
    items = _parse_archive_directory_html(DIRECTORY_HTML)
    names = [name for _desc, name, _type in items]
    assert "acr-20260831.htm" in names
    assert "ex31_seriesd.htm" in names
    assert ".." not in names


def test_find_certificate_exhibit_prefers_ex3_1(monkeypatch):
    archive = [("8-K", "acr-20260831.htm", "iXBRL 8-K"),
               ("EX-3.1", "ex31_seriesd.htm", "EX-3.1"),
               ("EX-3.2", "ex32_amendment.htm", "EX-3.2"),
               ("EX-5.1", "ex51.htm", "EX-5.1"),
               ("GRAPHIC", "img00001.jpg", "GRAPHIC")]
    monkeypatch.setattr("scripts.populate_contract_terms.fetch_archive_index",
                        lambda cik, acc: archive)
    result = find_certificate_exhibit("0001332551", "0001193125-26-382349")
    assert result["name"] == "ex31_seriesd.htm"
    assert result["exhibit_type"] == "EX-3.1"


def test_find_certificate_exhibit_description_certificate_name(monkeypatch):
    archive = [("8-K", "primary.htm", "iXBRL 8-K"),
               ("Certificate of Designation of Series D Preferred Stock",
                "exhibits232.htm", "EXHIBIT 3.2"),
               ("EX-1.1", "underwriting.htm", "EX-1.1")]
    monkeypatch.setattr("scripts.populate_contract_terms.fetch_archive_index",
                        lambda cik, acc: archive)
    result = find_certificate_exhibit("0001332551", "0001193125-26-382349")
    assert result["name"] == "exhibits232.htm"


def test_find_certificate_exhibit_none(monkeypatch):
    monkeypatch.setattr("scripts.populate_contract_terms.fetch_archive_index",
                        lambda cik, acc: [
                            ("8-K", "primary.htm", "iXBRL 8-K"),
                            ("EX-1.1", "a.htm", "EX-1.1"),
                            ("GRAPHIC", "img.jpg", "GRAPHIC"),
                        ])
    assert find_certificate_exhibit("0001332551", "0001193125-26-382349") is None


def test_find_certificate_exhibit_fetch_error(monkeypatch):
    def boom(_cik, _acc):
        raise RuntimeError("network down")
    monkeypatch.setattr("scripts.populate_contract_terms.fetch_archive_index", boom)
    assert find_certificate_exhibit("0001332551", "0001193125-26-382349") is None