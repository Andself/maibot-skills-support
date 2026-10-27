import asyncio
import importlib
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

pkg = types.ModuleType('skills_tests')
pkg.__path__ = [str(Path(__file__).parent)]
sys.modules['skills_tests'] = pkg
skills = importlib.import_module('skills_tests.skills')
store = importlib.import_module('skills_tests.store')
plugin = importlib.import_module('skills_tests.plugin')
DOCUMENT = Path(__file__).with_name('skills').joinpath('deep-research/SKILL.md').read_text('utf-8')


def package():
    return {**skills.parse_skill(DOCUMENT), 'files': {'SKILL.md': DOCUMENT, 'references/test.md': '参考'},
            'source': 'builtin', 'commit': '', 'digest': 'test', 'skipped_files': 0}


def evidence(name, cid='new', success=True, output='{"results":[{"url":"https://example.com"}]}'):
    return [{'item_type': 'FunctionCallItem', 'tool_call': {'call_id': cid, 'func_name': name}},
            {'item_type': 'FunctionCallOutputItem', 'call_id': cid, 'tool_name': name, 'success': success, 'output': output}]


class FormatTests(unittest.TestCase):
    def test_standard_frontmatter_and_required_tools(self):
        p = skills.parse_skill(DOCUMENT, 'deep-research')
        self.assertEqual(p['name'], 'deep-research')
        self.assertEqual(p['required'][1], ['fetch_page', 'web_fetch'])

    def test_bad_frontmatter_names_aliases_and_size(self):
        for text in ('plain', DOCUMENT.replace('name: deep-research', 'name: BAD'),
                     DOCUMENT.replace('description:', 'description: &x\na: *x\nb:'), 'x' * 70000):
            with self.subTest(text=text[:30]), self.assertRaises(ValueError):
                skills.parse_skill(text)
        with self.assertRaises(ValueError):
            skills.parse_skill(DOCUMENT, 'wrong-folder')

    def test_safe_paths(self):
        for path in ('../x', '/x', 'a/../x', 'C:/x', 'a\\x', 'a//x', 'a\nx'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                skills.safe_path(path)
        self.assertEqual(skills.safe_path('references/a.md'), 'references/a.md')

    def test_github_directory_file_and_explicit_ref(self):
        for url in ('https://github.com/a/repo/tree/main/skills/test',
                    'https://github.com/a/repo/blob/main/skills/test/SKILL.md'):
            self.assertEqual(skills.github_location(url), ('a', 'repo', 'main', 'skills/test'))
        self.assertEqual(skills.github_location('https://github.com/a/repo?ref=feature%2Ftest&path=skills%2Ftest'),
                         ('a', 'repo', 'feature/test', 'skills/test'))

    def test_no_arbitrary_urls_credentials_or_traversal(self):
        for url in ('http://github.com/a/b', 'https://evil.test/a/b', 'https://github.com.evil/a/b',
                    'https://secret@github.com/a/b', 'https://github.com:443/a/b',
                    'https://github.com/a/b/tree/main/../secret', 'https://github.com/a/b?token=secret'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                skills.github_location(url)

    def test_trigger_negation_quotes_and_commands(self):
        phrases = package()['triggers']
        self.assertTrue(plugin.triggered('帮我查一下这个词的起源', phrases))
        for text in ('不用查一下了', '不要搜索', '别帮我查一下', '他说“查一下”是什么意思', '/install-skill https://github.com/a/b', '取消调查'):
            self.assertFalse(plugin.triggered(text, phrases), text)

    def test_install_must_be_direct_request_not_negation_or_quote(self):
        url = 'https://github.com/a/repo'
        self.assertTrue(plugin.install_requested('/install-skill '+url, url))
        self.assertTrue(plugin.install_requested('帮我安装这个技能 '+url, url))
        for text in ('不要安装 '+url, '他说“安装这个技能 '+url+'”', '请问安装 '+url+' 是什么意思'):
            self.assertFalse(plugin.install_requested(text, url), text)

    def test_download_pins_commit_and_skips_scripts(self):
        requests = []
        doc = '---\nname: sample\ndescription: Example\n---\nDo something.'
        def opened(req, **kwargs):
            url = req.full_url
            requests.append(url)
            if '/commits/' in url:
                value = {'sha': 'a' * 40}
            elif '/git/trees/' in url:
                value = {'tree': [dict(path=p, type='blob', mode='100644', size=100)
                                  for p in ('skills/sample/SKILL.md', 'skills/sample/references/a.md', 'skills/sample/scripts/test.py')]}
            elif 'raw.githubusercontent.com' in url:
                return io.BytesIO((doc if url.endswith('SKILL.md') else 'reference').encode())
            else:
                value = {'default_branch': 'main'}
            return io.BytesIO(json.dumps(value).encode())
        with patch.object(skills.urllib.request, 'build_opener', return_value=types.SimpleNamespace(open=opened)):
            p = skills.fetch_github('https://github.com/owner/repo/tree/main/skills/sample')
        self.assertEqual(p['commit'], 'a' * 40)
        self.assertEqual(p['skipped_files'], 1)
        self.assertEqual(set(p['files']), {'SKILL.md', 'references/a.md'})
        self.assertTrue(all('/' + 'a'*40 + '/' in u for u in requests if 'raw.githubusercontent.com' in u))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = store.Store(self.tmp.name)
        self.s.install(package())

    def test_no_silent_overwrite(self):
        with self.assertRaises(ValueError):
            self.s.install(package())

    def test_same_message_dedup_and_new_topic_supersedes(self):
        run, fresh = self.s.start('deep-research', 's', 'm', 'query', [])
        self.assertTrue(fresh)
        self.assertFalse(self.s.start('deep-research', 's', 'm', 'query', [])[1])
        self.s.start('deep-research', 's', 'next', 'query', [])
        self.assertEqual(self.s.runs()[1]['status'], 'superseded')

    def test_old_failed_and_wrong_name_results_do_not_complete(self):
        run, _ = self.s.start('deep-research', 's', 'm', 'query', ['old'])
        self.s.observe(run, evidence('web_search', 'old'))
        self.s.observe(run, evidence('web_search', 'failed', False))
        self.s.observe(run, evidence('web_search', 'jsonerror', True, '{"error":"rate limited"}'))
        wrong = evidence('web_search', 'mismatch')
        wrong[1]['tool_name'] = 'fetch_page'
        self.s.observe(run, wrong)
        self.assertEqual(len(self.s.progress(run)['missing_tools']), 2)
        self.s.observe(run, evidence('search_and_summarize', 'search'))
        self.s.observe(run, evidence('fetch_page', 'body'))
        self.assertEqual(self.s.progress(run)['missing_tools'], [])

    def test_cancel_disable_and_remove(self):
        run, _ = self.s.start('deep-research', 's', 'm', 'query', [])
        self.s.toggle('deep-research', False)
        self.assertEqual(self.s.current('s')['status'], 'canceled')
        self.assertFalse(self.s.update(run['id'], 'completed'))
        self.s.remove('deep-research')
        self.assertEqual(self.s.catalog(), [])

    def test_expiry_and_disabled_global(self):
        run, _ = self.s.start('deep-research', 's', 'm', 'query', [])
        with patch.object(store.time, 'time', return_value=run['created']+400):
            self.assertEqual(self.s.current('s')['status'], 'timed_out')
        self.s.configure(False, None)
        with self.assertRaises(ValueError):
            self.s.start('deep-research', 's', 'next', 'query', [])

    def test_daily_limits_and_interrupt(self):
        self.s.configure(True, None, daily_limit=1)
        self.s.start('deep-research', 's', 'm', 'query', [])
        with self.assertRaises(ValueError):
            self.s.start('deep-research', 'other', 'm', 'query', [])
        self.s.interrupt()
        self.assertEqual(self.s.current('s')['status'], 'interrupted')


class PluginTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.obj = plugin.SkillsSupport()
        self.stream = {'session_id': 's', 'user_id': 'u', 'platform': 'test', 'account_id': 'bot'}
        self.row = {'message_id': 'm', 'processed_plain_text': '帮我仔细查一下这个问题',
                    'message_info': {'user_info': {'user_id': 'u'}}}
        self.obj._ctx = types.SimpleNamespace(paths=types.SimpleNamespace(data_dir=Path(self.tmp.name)),
            chat=types.SimpleNamespace(get_private_streams=AsyncMock(return_value=[self.stream])),
            call_capability=AsyncMock(return_value=[self.row]),
            send=types.SimpleNamespace(text=AsyncMock(return_value={'sent': True})),
            logger=types.SimpleNamespace(warning=lambda *a: None))
        await self.obj.on_load()

    async def test_autostart_before_model_once_and_progress_from_host_results(self):
        r = await self.obj.planner(items=[], session_id='s')
        self.assertIn('已激活 SKILL.md', json.dumps(r, ensure_ascii=False))
        self.assertEqual(len(self.obj.store.runs()), 1)
        await self.obj.planner(items=[], session_id='s')
        self.assertEqual(self.obj.ctx.send.text.await_count, 1)
        self.assertFalse((await self.obj.control(operation='finish', stream_id='s'))['success'])
        await self.obj.planner(items=evidence('web_search')+evidence('fetch_page', 'body'), session_id='s')
        self.assertTrue((await self.obj.control(operation='finish', stream_id='s'))['success'])
        reply = await self.obj.replyer(items=[], session_id='s')
        self.assertIn('现在可以正常回复', json.dumps(reply, ensure_ascii=False))

    async def test_no_eager_full_document_for_chitchat(self):
        self.row['processed_plain_text'] = '今天吃什么'
        r = await self.obj.planner(items=[], session_id='s')
        content = json.dumps(r, ensure_ascii=False)
        self.assertNotIn('已激活 SKILL.md', content)
        self.assertEqual(self.obj.store.runs(), [])
        self.obj.ctx.send.text.assert_not_called()

    async def test_references_scoped_and_paths_rejected(self):
        await self.obj.planner(items=[], session_id='s')
        self.assertFalse((await self.obj.read_reference(path='../secret', stream_id='s'))['success'])
        r = await self.obj.read_reference(path='SKILL.md', stream_id='s')
        self.assertIn('深入调查', r['text'])
        self.assertFalse((await self.obj.read_reference(path='SKILL.md', stream_id='other'))['success'])

    async def test_wrong_user_denied(self):
        self.row['message_info']['user_info']['user_id'] = 'other'
        self.assertFalse((await self.obj.control(operation='start', skill_name='deep-research', query='query', stream_id='s'))['success'])

    async def test_chat_install_is_hard_admin_check(self):
        url = 'https://github.com/a/repo/tree/main/skill'
        self.row['processed_plain_text'] = '/install-skill '+url
        with patch.object(plugin, 'fetch_github') as fetch:
            self.assertFalse((await self.obj.install_tool(url=url, stream_id='s', is_admin=True))['success'])
            fetch.assert_not_called()
        await self.obj.configure(True, admin_session_id='s')
        p = package();p['name'] = 'example';p['commit'] = 'a'*40
        with patch.object(plugin, 'fetch_github', return_value=p) as fetch:
            result = await self.obj.install_command(stream_id='s', matched_groups={'skill_url': url})
            self.assertTrue(result[0]);self.assertTrue(result[2]);fetch.assert_called_once()
        self.row['processed_plain_text'] = '普通聊天'
        self.assertFalse((await self.obj.install_tool(url=url, stream_id='s'))['success'])

    async def test_admin_account_isolation_and_unbind(self):
        await self.obj.configure(True, admin_session_id='s')
        self.stream['account_id'] = 'different-bot'
        self.row['processed_plain_text'] = '/install-skill https://github.com/a/repo'
        r = await self.obj.install_tool(url='https://github.com/a/repo', stream_id='s')
        self.assertFalse(r['success'])
        await self.obj.configure(True, admin_session_id='__clear__')
        self.assertIsNone(self.obj.store.settings()['administrator'])

    async def test_new_message_cancels_old_and_no_completion(self):
        await self.obj.planner(items=[], session_id='s')
        self.row['message_id'] = 'next'
        self.row['processed_plain_text'] = '取消调查'
        await self.obj.planner(items=[], session_id='s')
        self.assertEqual(self.obj.store.current('s')['status'], 'canceled')
        self.assertFalse((await self.obj.control(operation='finish', stream_id='s'))['success'])

    async def test_sending_failure_does_not_claim_sent(self):
        self.obj.ctx.send.text.side_effect = RuntimeError('offline')
        await self.obj.planner(items=[], session_id='s')
        self.assertEqual(self.obj.store.current('s')['notice'], 'failed')


if __name__ == '__main__':
    unittest.main()
