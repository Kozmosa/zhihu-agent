import csv
import io
import sqlite3
import zipfile


def cards(client, imported):
    response = client.post(
        "/api/v1/cards/generate", json={"source_id": imported[0]["id"], "count": 3}
    )
    assert response.status_code == 200
    return response.json()["cards"]


def test_card_export_tsv(client, imported):
    generated = cards(client, imported)
    assert len(generated) == 3
    generated[0]["back"] = '<script>alert("x")</script>\n多行\t文本'
    result = client.post("/api/v1/cards/export/tsv", json={"cards": generated})
    assert result.status_code == 200
    assert "<script>" not in result.text
    assert "&lt;script&gt;" in result.text
    rows = list(
        csv.reader(
            io.StringIO(result.text.split("#columns:Front\tBack\tSource\n")[1]), delimiter="\t"
        )
    )
    assert len(rows) == 3
    assert len(rows[0]) == 3


def test_apkg_contains_valid_notes_and_stable_guids(client, imported, tmp_path):
    generated = cards(client, imported)
    guids = []
    for i in range(2):
        response = client.post("/api/v1/cards/export/apkg", json={"cards": generated + generated})
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            assert archive.testzip() is None
            assert set(archive.namelist()) == {"collection.anki2", "media"}
            database = tmp_path / f"check-{i}.sqlite3"
            database.write_bytes(archive.read("collection.anki2"))
        connection = sqlite3.connect(database)
        try:
            assert connection.execute("SELECT count(*) FROM notes").fetchone()[0] == 3
            assert connection.execute("SELECT count(*) FROM cards").fetchone()[0] == 3
            guids.append(connection.execute("SELECT guid FROM notes ORDER BY guid").fetchall())
        finally:
            connection.close()
    assert guids[0] == guids[1]
    assert list((tmp_path / "exports-tmp").iterdir()) == []
