"""Plugin-owned skill catalog and verifiable execution ledger."""
import json
import sqlite3
import time
import uuid
import re
from urllib.parse import urlsplit
from contextlib import contextmanager
from pathlib import Path

DEFAULTS = {'enabled': True, 'administrator': None, 'timeout': 300, 'daily_limit': 30}


class Store:
    def __init__(self, directory):
        self.root = Path(directory)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'skills.sqlite3'
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS skills(name TEXT PRIMARY KEY,package TEXT NOT NULL,enabled INTEGER NOT NULL,installed REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,skill TEXT NOT NULL,session TEXT NOT NULL,
                  message TEXT NOT NULL,query TEXT NOT NULL,status TEXT NOT NULL,package TEXT NOT NULL,
                  baseline TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,notice TEXT NOT NULL DEFAULT '',
                  UNIQUE(session,message));
                CREATE TABLE IF NOT EXISTS evidence(run_id TEXT NOT NULL,call_id TEXT NOT NULL,tool TEXT NOT NULL,
                  success INTEGER NOT NULL,observed REAL NOT NULL,PRIMARY KEY(run_id,call_id));
                CREATE TABLE IF NOT EXISTS seed_state(name TEXT PRIMARY KEY,removed INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS revisions(name TEXT NOT NULL,package TEXT NOT NULL,changed REAL NOT NULL);
            ''')
            if 'urls' not in {r[1] for r in db.execute('PRAGMA table_info(evidence)')}:
                db.execute("ALTER TABLE evidence ADD COLUMN urls TEXT NOT NULL DEFAULT '[]'")
            db.execute('INSERT OR IGNORE INTO settings VALUES(1,?)', (json.dumps(DEFAULTS),))

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def settings(self):
        with self.db() as db:
            return {**DEFAULTS, **json.loads(db.execute('SELECT value FROM settings WHERE id=1').fetchone()[0])}

    def configure(self, enabled, administrator, timeout=300, daily_limit=30):
        if type(enabled) is not bool or type(timeout) is not int or type(daily_limit) is not int or not 30 <= timeout <= 1800 or not 1 <= daily_limit <= 100:
            raise ValueError('有效期30至1800秒，每24小时最多1至100次')
        if administrator is not None and (not isinstance(administrator, dict) or not administrator.get('user_id') or not administrator.get('platform')):
            raise ValueError('管理员身份无效')
        state = dict(enabled=enabled, administrator=administrator, timeout=timeout, daily_limit=daily_limit)
        with self.db() as db:
            db.execute('UPDATE settings SET value=? WHERE id=1', (json.dumps(state),))
            if not enabled:
                db.execute("UPDATE runs SET status='canceled',updated=? WHERE status='running'", (time.time(),))
        return state

    def install(self, package, builtin=False):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if builtin:
                seed = db.execute('SELECT removed FROM seed_state WHERE name=?', (package['name'],)).fetchone()
                if seed and seed['removed']:
                    return False
                db.execute('INSERT OR IGNORE INTO seed_state(name) VALUES(?)', (package['name'],))
            old = db.execute('SELECT 1 FROM skills WHERE name=?', (package['name'],)).fetchone()
            if old:
                if builtin:
                    return False
                raise ValueError('同名技能已存在；先在后台移除旧技能，避免静默覆盖')
            if db.execute('SELECT count(*) FROM skills').fetchone()[0] >= 40:
                raise ValueError('最多安装40个技能')
            db.execute('INSERT INTO skills VALUES(?,?,?,?)', (package['name'], json.dumps(package), 1, time.time()))
        return True

    def replace(self, name, package, expected_digest):
        if package['name'] != name:
            raise ValueError('上游技能名称已变化，未覆盖原技能')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT package FROM skills WHERE name=?', (name,)).fetchone()
            if not old or json.loads(old['package']).get('digest') != expected_digest:
                raise ValueError('技能已被移除或更新，请刷新重试')
            if old['package'] == json.dumps(package):
                return False
            db.execute('INSERT INTO revisions VALUES(?,?,?)', (name, old['package'], time.time()))
            db.execute('UPDATE skills SET package=? WHERE name=?', (json.dumps(package), name))
        return True

    def catalog(self):
        with self.db() as db:
            return [{**json.loads(r['package']), 'enabled': bool(r['enabled']), 'installed': r['installed']}
                    for r in db.execute('SELECT * FROM skills ORDER BY name')]

    def skill(self, name, enabled=True):
        with self.db() as db:
            r = db.execute('SELECT * FROM skills WHERE name=?', (name,)).fetchone()
            if not r or enabled and not r['enabled']:
                raise ValueError('技能不存在或未开启')
            return json.loads(r['package'])

    def toggle(self, name, enabled):
        if type(enabled) is not bool:
            raise ValueError('开关必须是布尔值')
        with self.db() as db:
            if not db.execute('UPDATE skills SET enabled=? WHERE name=?', (int(enabled), name)).rowcount:
                raise ValueError('技能不存在')
            if not enabled:
                db.execute("UPDATE runs SET status='canceled',updated=? WHERE skill=? AND status='running'", (time.time(), name))

    def remove(self, name):
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO seed_state VALUES(?,1)', (name,))
            db.execute('DELETE FROM skills WHERE name=?', (name,))
            db.execute("UPDATE runs SET status='canceled',updated=? WHERE skill=? AND status='running'", (time.time(), name))

    def expire(self):
        timeout = self.settings()['timeout']
        with self.db() as db:
            db.execute("UPDATE runs SET status='timed_out',updated=? WHERE status='running' AND created<?", (time.time(), time.time()-timeout))

    def start(self, skill, session, message, query, baseline):
        self.expire()
        package = self.skill(skill)
        config = self.settings()
        if not config['enabled']:
            raise ValueError('Skills 功能未开启')
        now = time.time()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT * FROM runs WHERE session=? AND message=?', (session, message)).fetchone()
            if old:
                if old['skill'] != skill:
                    raise ValueError('本条消息已有其他技能任务，请先完成或取消')
                return dict(old), False
            if db.execute('SELECT count(*) FROM runs WHERE created>?', (now-86400,)).fetchone()[0] >= config['daily_limit']:
                raise ValueError('已达到24小时技能任务上限')
            db.execute("UPDATE runs SET status='superseded',updated=? WHERE session=? AND status='running'", (now, session))
            run_id = uuid.uuid4().hex
            db.execute('INSERT INTO runs(id,skill,session,message,query,status,package,baseline,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (run_id, skill, session, message, query, 'running', json.dumps(package), json.dumps(baseline), now, now))
            return dict(db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()), True

    def current(self, session):
        self.expire()
        with self.db() as db:
            row = db.execute('SELECT * FROM runs WHERE session=? ORDER BY created DESC LIMIT 1', (session,)).fetchone()
            return dict(row) if row else None

    def update(self, run_id, status):
        with self.db() as db:
            return bool(db.execute("UPDATE runs SET status=?,updated=? WHERE id=? AND status='running'", (status, time.time(), run_id)).rowcount)

    def notice(self, run_id, sent):
        with self.db() as db:
            db.execute('UPDATE runs SET notice=? WHERE id=?', ('sent' if sent else 'failed', run_id))

    def observe(self, run, items):
        if run['status'] != 'running':
            return
        baseline = set(json.loads(run['baseline']))
        calls = {i['tool_call']['call_id']: i['tool_call']['func_name'] for i in items
                 if i.get('item_type') == 'FunctionCallItem' and isinstance(i.get('tool_call'), dict)
                 and i['tool_call'].get('call_id') and i['tool_call'].get('func_name')}
        with self.db() as db:
            for item in items:
                call_id = item.get('call_id')
                if item.get('item_type') != 'FunctionCallOutputItem' or not call_id or call_id in baseline:
                    continue
                name = calls.get(call_id)
                if not name or item.get('tool_name') not in (None, name):
                    continue
                success = item.get('success') is True
                output = item.get('output')
                try:
                    result = json.loads(output) if isinstance(output, str) else output
                except (ValueError, TypeError):
                    result = None
                if isinstance(result, dict) and (result.get('success') is False or result.get('error')
                        or result.get('status') in ('error', 'failed', 'unavailable')):
                    success = False
                urls = []
                if success and name in ('fetch_page', 'web_fetch'):
                    call = next((i.get('tool_call', {}) for i in items if i.get('tool_call', {}).get('call_id') == call_id), {})
                    args = call.get('args') or {}
                    requested = args.get('url', '') if isinstance(args, dict) else ''
                    # Embedded hyperlinks were not themselves fetched. Only the
                    # requested page (or a tool's leading canonical URL) counts.
                    candidates = [requested] if requested else [line.strip() for line in str(output).splitlines()[:4]
                        if re.fullmatch(r'https?://[^\s<>"\u3000]+', line.strip())][:1]
                    for url in candidates:
                        url = url.rstrip('。，；、)）]')
                        try:
                            parsed = urlsplit(url)
                            if parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username and not parsed.password and url not in urls:
                                urls.append(url)
                        except ValueError:
                            continue
                db.execute('INSERT OR IGNORE INTO evidence(run_id,call_id,tool,success,observed,urls) VALUES(?,?,?,?,?,?)',
                           (run['id'], call_id, name, int(success), time.time(), json.dumps(urls[:6])))

    def progress(self, run):
        package = json.loads(run['package'])
        with self.db() as db:
            evidence = [dict(r) for r in db.execute('SELECT call_id,tool,success,observed,urls FROM evidence WHERE run_id=? ORDER BY observed', (run['id'],))]
        for r in evidence:
            r['urls'] = json.loads(r['urls'])
        used = {r['tool'] for r in evidence if r['success']}
        missing = [group for group in package.get('required', []) if not used.intersection(group)]
        return {'id': run['id'], 'skill': run['skill'], 'status': run['status'], 'query': run['query'],
                'created': run['created'], 'notice': run['notice'], 'evidence': evidence, 'missing_tools': missing,
                'sources': list(dict.fromkeys(u for r in evidence for u in r['urls'])),
                'verification': '仅验证真实工具执行记录，不保证来源内容或最终答案正确'}

    def runs(self):
        self.expire()
        with self.db() as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM runs ORDER BY created DESC LIMIT 60')]
        return [self.progress(r) for r in rows]

    def interrupt(self):
        with self.db() as db:
            db.execute("UPDATE runs SET status='interrupted',updated=? WHERE status='running'", (time.time(),))
