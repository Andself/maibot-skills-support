"""Document-only Agent Skills packages and commit-pinned GitHub installation."""
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import PurePosixPath

import yaml

MAX_FILE = 65536
MAX_TOTAL = 524288
NAME = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*\Z')


def safe_path(value):
    if not isinstance(value, str) or not value or len(value) > 400 or '\\' in value or ':' in value or any(ord(c) < 32 for c in value):
        raise ValueError('无效的技能相对路径')
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ('', '.', '..') for p in value.split('/')):
        raise ValueError('技能路径必须在技能目录内')
    return value


def parse_skill(text, directory_name=None):
    if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_FILE:
        raise ValueError('SKILL.md 最大64KB')
    text = text.removeprefix('\ufeff').replace('\r\n', '\n')
    parts = text.split('\n---\n', 1)
    if not text.startswith('---\n') or len(parts) != 2:
        raise ValueError('SKILL.md 需要 YAML frontmatter')
    # Reject aliases: a document cannot expand an unbounded YAML object graph.
    try:
        tokens = list(yaml.scan(parts[0][4:]))
        if len(tokens) > 1000 or any(isinstance(t, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken)) for t in tokens):
            raise ValueError('frontmatter 过大或含不支持的 YAML 锚点/别名')
        meta = yaml.safe_load(parts[0][4:])
    except (yaml.YAMLError, RecursionError) as exc:
        raise ValueError('frontmatter YAML 格式无效') from None
    if not isinstance(meta, dict):
        raise ValueError('frontmatter 必须为对象')
    name, description = meta.get('name'), meta.get('description')
    if not isinstance(name, str) or len(name) > 64 or not NAME.fullmatch(name):
        raise ValueError('name 必须是64字内小写字母、数字和单横线')
    if directory_name and name != directory_name:
        raise ValueError('name 必须与技能目录名一致')
    if not isinstance(description, str) or not 1 <= len(description.strip()) <= 1024:
        raise ValueError('description 需为1至1024字')
    if not parts[1].strip():
        raise ValueError('技能正文不能为空')
    metadata = meta.get('metadata') or {}
    if not isinstance(metadata, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in metadata.items()):
        raise ValueError('metadata 仅支持字符串键和值')
    phrases = [s.strip() for s in metadata.get('maibot-trigger-phrases', '').split('|') if s.strip()]
    if len(phrases) > 20 or any(len(s) > 40 or len(s) < 2 for s in phrases):
        raise ValueError('触发短语最多20个，每项2至40字')
    required = []
    for group in metadata.get('maibot-required-tools', '').split(';'):
        names = [s.strip() for s in group.split('|') if s.strip()]
        if names:
            if len(required) >= 8 or len(names) > 8 or any(not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', n) for n in names):
                raise ValueError('必要工具分组无效')
            required.append(names)
    return {'name': name, 'description': description.strip(), 'body': parts[1].strip(),
            'compatibility': str(meta.get('compatibility', ''))[:500],
            'allowed_tools': str(meta.get('allowed-tools', ''))[:2000],
            'triggers': phrases, 'required': required, 'document': text,
            'require_citations': metadata.get('maibot-require-citations') == 'true'}


def github_location(url):
    if not isinstance(url, str) or len(url) > 1500:
        raise ValueError('GitHub 地址无效')
    p = urllib.parse.urlsplit(url)
    if p.scheme != 'https' or p.hostname != 'github.com' or p.username or p.password or p.port or p.fragment:
        raise ValueError('仅支持 https://github.com/owner/repo 地址')
    pieces = urllib.parse.unquote(p.path).strip('/').split('/')
    if len(pieces) < 2 or not all(re.fullmatch(r'[\w.-]+', s, re.ASCII) for s in pieces[:2]):
        raise ValueError('GitHub 仓库地址无效')
    owner, repo = pieces[:2]
    repo = repo.removesuffix('.git')
    query = urllib.parse.parse_qs(p.query)
    if set(query) - {'ref', 'path'} or any(len(v) != 1 for v in query.values()):
        raise ValueError('只支持 ref、path 查询参数')
    ref = query.get('ref', [''])[0]
    path = query.get('path', [''])[0].strip('/')
    if len(pieces) > 2:
        if len(pieces) < 4 or pieces[2] not in ('tree', 'blob') or ref or path:
            raise ValueError('请使用仓库地址或 tree/blob/<ref>/<技能路径>；带斜线分支使用 ?ref=...&path=...')
        ref, path = pieces[3], '/'.join(pieces[4:])
    if path.endswith('/SKILL.md'):
        path = path[:-9]
    elif path == 'SKILL.md':
        path = ''
    if path:
        safe_path(path)
    if len(ref) > 200 or any(ch in ref for ch in '\r\n\x00'):
        raise ValueError('Git ref 无效')
    return owner, repo, ref, path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('GitHub 请求发生重定向，请使用仓库当前地址')


def fetch_github(url):
    """Only fixed GitHub API/raw hosts. No clone, archives, code or credentials."""
    owner, repo, ref, directory = github_location(url)
    deadline = time.monotonic() + 25
    opener = urllib.request.build_opener(NoRedirect())

    def get(host, path, limit, as_json=True):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError('GitHub 安装超时')
        req = urllib.request.Request('https://' + host + path, headers={
            'User-Agent': 'maibot-skills-support', 'Accept': 'application/vnd.github+json'})
        try:
            with opener.open(req, timeout=min(8, remaining)) as response:
                raw = response.read(limit + 1)
        except urllib.error.HTTPError as exc:
            raise ValueError(f'GitHub HTTP {exc.code}；仅支持公开仓库，限流时请稍后重试') from None
        except (urllib.error.URLError, TimeoutError):
            raise ValueError('GitHub 网络请求失败或超时') from None
        if len(raw) > limit:
            raise ValueError('GitHub 文件或目录超过大小限制')
        return json.loads(raw) if as_json else raw.decode('utf-8')

    base = f'/repos/{owner}/{repo}'
    if not ref:
        ref = get('api.github.com', base, MAX_TOTAL)['default_branch']
    commit = get('api.github.com', base + '/commits/' + urllib.parse.quote(ref, safe=''), MAX_TOTAL)['sha']
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('无法固定 GitHub commit')
    tree = get('api.github.com', base + f'/git/trees/{commit}?recursive=1', 4 * MAX_TOTAL)
    if tree.get('truncated'):
        raise ValueError('仓库目录过大，无法可靠安装')
    blobs = [r for r in tree.get('tree', []) if r.get('type') == 'blob' and r.get('mode') == '100644']
    candidates = [r['path'] for r in blobs if r['path'] == 'SKILL.md' or r['path'].endswith('/SKILL.md')]
    target = (directory + '/' if directory else '') + 'SKILL.md'
    if target not in candidates:
        if not directory and len(candidates) == 1:
            target = candidates[0]
            directory = target.rsplit('/', 1)[0] if '/' in target else ''
        else:
            choices = ', '.join(candidates[:12]) or '无 SKILL.md'
            raise ValueError('请指定某个技能目录：' + choices)
    prefix = directory + '/' if directory else ''
    # Resolve the latest change to this skill at the immutable download snapshot,
    # rather than using a commit that only changed another skill in the repo.
    history_query = urllib.parse.urlencode({'sha': commit, 'path': directory, 'per_page': 1})
    changes = get('api.github.com', base + '/commits?' + history_query, MAX_TOTAL)
    version = changes[0].get('sha', '') if isinstance(changes, list) and changes else ''
    if not re.fullmatch(r'[0-9a-f]{40}', version):
        raise ValueError('无法确认该技能的最新变更 commit，未安装')
    documents, skipped, total = {}, 0, 0
    for item in blobs:
        full = item['path']
        if not full.startswith(prefix):
            continue
        relative = full[len(prefix):]
        safe_path(relative)
        if relative.startswith('.') or relative.startswith('scripts/') or not (
                PurePosixPath(relative).suffix.lower() in ('.md', '.txt', '.json', '.yaml', '.yml', '.csv', '.toml')
                or relative in ('LICENSE', 'NOTICE')):
            skipped += 1
            continue
        # A repo-root skill must not absorb other nested skills.
        if any(c != target and c.startswith(prefix) and full.startswith(c[:-8]) for c in candidates):
            continue
        if item.get('size', MAX_FILE + 1) > MAX_FILE or len(documents) >= 32:
            raise ValueError('技能最多32个文档，每个64KB')
        raw = get('raw.githubusercontent.com', '/' + '/'.join(urllib.parse.quote(v, safe='') for v in (owner, repo, commit))
                  + '/' + urllib.parse.quote(full, safe='/'), MAX_FILE, False)
        total += len(raw.encode('utf-8'))
        if total > MAX_TOTAL:
            raise ValueError('技能文档总量超过512KB')
        documents[relative] = raw
    skill = parse_skill(documents['SKILL.md'], directory.split('/')[-1] if directory else repo)
    digest = hashlib.sha256(json.dumps(documents, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {**skill, 'files': documents, 'source': f'https://github.com/{owner}/{repo}', 'install_url': url,
            'commit': version, 'snapshot_commit': commit, 'directory': directory, 'digest': digest, 'skipped_files': skipped}
