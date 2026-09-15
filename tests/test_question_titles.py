import sqlite3

from zhijing.domain.models import SourceDraft
from zhijing.infrastructure.sqlite_sources import SQLiteSourceRepository


def answer(name, n=1, title=None):
    return SourceDraft(title=title or name, author_id=f'author-{n}', author_name=name,
                       text=f'回答正文 {n}', origin='zhihu',
                       url=f'https://www.zhihu.com/question/123/answer/{n}')


def test_legacy_author_titles_are_never_question_names(tmp_path):
    repo = SQLiteSourceRepository(tmp_path / 'sources.sqlite3')
    repo.initialize()
    repo.save_many([answer('Jhon Smith'), answer('忧郁的Tom', 2)])
    group = repo.groups('question', '', 0, 20).items[0]
    assert group.name == '问题 123（标题待补全）'
    assert group.count == 2
    repo.save(answer('另一作者', 3, '正确的问题标题？'))
    assert repo.groups('question', '', 0, 20).items[0].name == '正确的问题标题？'


def test_title_override_preserves_sources_and_survives_restart(tmp_path):
    repo = SQLiteSourceRepository(tmp_path / 'sources.sqlite3')
    repo.initialize()
    before = repo.save_many([answer('Jhon Smith'), answer('忧郁的Tom', 2)])
    with sqlite3.connect(repo.path) as connection:
        payloads = connection.execute('SELECT id, payload FROM sources ORDER BY id').fetchall()
    group = repo.set_question_title('123', '正确的问题标题？')
    assert group.name == '正确的问题标题？' and group.count == 2
    repo.initialize()
    assert repo.groups('question', '正确的问题', 0, 20).items[0] == group
    with sqlite3.connect(repo.path) as connection:
        assert connection.execute('SELECT id, payload FROM sources ORDER BY id').fetchall() == payloads
    assert repo.save(answer('Jhon Smith')).id == before[0].id
    assert len(repo.list()) == 2
    repo.delete_many([row.id for row in before])
    assert repo.groups('question', '', 0, 20).total == 0


def test_title_endpoint_validates_and_keeps_source_and_author_identity(client):
    original = client.post('/api/v1/sources/import', json={'items':[answer('Jhon Smith').model_dump(mode='json')]}).json()[0]
    path = '/api/v1/sources/question-title'
    for body in [{'question_id':'', 'title':'标题'}, {'question_id':'123', 'title':' '}, {'question_id':'123', 'title':'x'*201}]:
        assert client.post(path,json=body).status_code == 422
    assert client.post(path,json={'question_id':'999', 'title':'不存在'}).status_code == 404
    assert client.post(path,json={'question_id':'123', 'title':'正确的问题标题？'}).status_code == 200
    assert client.get('/api/v1/sources/'+original['id']).json() == original
    assert client.get('/api/v1/sources/groups?by=author').json()['items'][0]['name'] == 'Jhon Smith'
    assert client.post(path,json={'question_id':'123','title':'恶意修改'}, headers={'X-Zhijing-Token':'invalid'}).status_code == 403
