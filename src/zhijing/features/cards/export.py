"""纯导出函数，不连接用户的 Anki，也不写入用户卡库。"""

import csv
import hashlib
import html
import io
import itertools
import sqlite3
import time
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

import genanki

from zhijing.features.cards.schemas import ExportRequest


def _html(text: str) -> str:
    return html.escape(text).replace("\n", "<br>").replace("\r", "")


def _fields(card) -> list[str]:
    source = card.source_id
    if card.evidence_excerpt is not None:
        source += f"\n原文摘录：{card.evidence_excerpt}"
    return [_html(card.front), _html(card.back), _html(source)]


def export_tsv(request: ExportRequest) -> str:
    output = io.StringIO(newline="")
    output.write("#separator:Tab\n#html:true\n#columns:Front\tBack\tSource\n")
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")
    for card in request.cards:
        writer.writerow(_fields(card))
    return output.getvalue()


def export_apkg(request: ExportRequest, temp_root: Path) -> bytes:
    model = genanki.Model(
        1888741041,
        "ZhiJing Basic v1",
        fields=[{"name": name} for name in ["Front", "Back", "Source"]],
        templates=[
            {
                "name": "阅读卡片",
                "qfmt": "{{Front}}",
                "afmt": '{{FrontSide}}<hr id="answer">{{Back}}<hr>来源：{{Source}}',
            }
        ],
    )
    deck_id = int.from_bytes(hashlib.sha256(request.deck_name.encode()).digest()[:4], "big")
    deck = genanki.Deck(deck_id, request.deck_name)
    seen = set()
    for card in request.cards:
        guid = genanki.guid_for(card.source_id, card.front)
        if guid not in seen:
            deck.add_note(genanki.Note(model=model, fields=_fields(card), guid=guid))
            seen.add(guid)
    temp_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=temp_root) as directory:
        # genanki.write_to_file 会遗留系统临时数据库；显式管理其生命周期。
        database = Path(directory) / "collection.anki2"
        timestamp = time.time()
        connection = sqlite3.connect(database)
        try:
            genanki.Package(deck).write_to_db(
                connection.cursor(), timestamp, itertools.count(int(timestamp * 1000))
            )
            connection.commit()
        finally:
            connection.close()
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(database, "collection.anki2")
            archive.writestr("media", "{}")
        return output.getvalue()
