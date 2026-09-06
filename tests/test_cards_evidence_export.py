import csv
import io
import json
import sqlite3
import zipfile

import pytest

EVIDENCE = '<script>alert("x")</script> & 原文\n第二行'
ESCAPED_EVIDENCE = "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; 原文<br>第二行"


def card_request(with_evidence):
    card = {"front": "概念是什么？", "back": "概念说明。", "source_id": "source-1"}
    if with_evidence:
        card["evidence_excerpt"] = EVIDENCE
    return {"cards": [card]}


def expected_source(with_evidence):
    return "source-1" + (f"<br>原文摘录：{ESCAPED_EVIDENCE}" if with_evidence else "")


@pytest.mark.parametrize("with_evidence", [False, True])
def test_tsv_preserves_optional_evidence_with_html_escaping(client, with_evidence):
    response = client.post("/api/v1/cards/export/tsv", json=card_request(with_evidence))
    assert response.status_code == 200
    data = response.text.split("#columns:Front\tBack\tSource\n")[1]
    rows = list(csv.reader(io.StringIO(data), delimiter="\t"))
    assert rows == [["概念是什么？", "概念说明。", expected_source(with_evidence)]]
    assert "<script>" not in response.text


@pytest.mark.parametrize("with_evidence", [False, True])
def test_apkg_preserves_optional_evidence_in_compatible_source_field(
    client, tmp_path, with_evidence
):
    response = client.post("/api/v1/cards/export/apkg", json=card_request(with_evidence))
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.testzip() is None
        database = tmp_path / "evidence-export.sqlite3"
        database.write_bytes(archive.read("collection.anki2"))
    connection = sqlite3.connect(database)
    try:
        notes = connection.execute("SELECT flds FROM notes").fetchall()
        assert notes == [
            ("\x1f".join(["概念是什么？", "概念说明。", expected_source(with_evidence)]),)
        ]
        model = json.loads(connection.execute("SELECT models FROM col").fetchone()[0])
        assert [field["name"] for field in model["1888741041"]["flds"]] == [
            "Front",
            "Back",
            "Source",
        ]
    finally:
        connection.close()
    assert list((tmp_path / "exports-tmp").iterdir()) == []
