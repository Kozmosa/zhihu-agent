import json, sqlite3
from datetime import UTC, datetime
from pathlib import Path

class SQLiteTranscript:
 def __init__(self,path:Path): self.path=path
 def initialize(self):
  self.path.parent.mkdir(parents=True,exist_ok=True)
  with sqlite3.connect(self.path) as c:
   c.execute('CREATE TABLE IF NOT EXISTS transcript_events (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, run_id TEXT, step_id TEXT, attempt INTEGER, event TEXT NOT NULL, provider TEXT, model TEXT, payload TEXT NOT NULL, created_at TEXT NOT NULL)')
   c.execute('CREATE INDEX IF NOT EXISTS idx_transcript_run ON transcript_events(run_id,id)')
 def append(self, *, session_id='', run_id='', step_id='', attempt=0, event='model_call', provider='', model='', payload=None):
  with sqlite3.connect(self.path) as c:
   c.execute('INSERT INTO transcript_events(session_id,run_id,step_id,attempt,event,provider,model,payload,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(session_id,run_id,step_id,attempt,event,provider,model,json.dumps(payload or {},ensure_ascii=False),datetime.now(UTC).isoformat()))
 def list(self, run_id):
  with sqlite3.connect(self.path) as c:
   rows=c.execute('SELECT id,session_id,run_id,step_id,attempt,event,provider,model,payload,created_at FROM transcript_events WHERE run_id=? ORDER BY id',(run_id,)).fetchall()
  keys=['id','session_id','run_id','step_id','attempt','event','provider','model','payload','created_at']
  return [dict(zip(keys,r)) | {'payload':json.loads(r[8])} for r in rows]
