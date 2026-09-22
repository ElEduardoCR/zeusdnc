"""OTA with loopback HTTP/files/locks; never restarts real services."""
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from unittest.mock import Mock, patch
import sys
sys.modules.setdefault('serial_transfer', Mock())
from zeuz_core import updater as u, deployment as d, operation_guard as guard, remote_updates as remote, update_auth
from zeuz_core.headless_api import Server, HeadlessController

class UpdateFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        for module, key, path in [
            (u, 'STATE_PATH', 'data/update.json'), (u, 'ARCHIVE_PATH', 'data/update.tar.gz'),
            (u, 'VERSION_PATH', 'etc/version'), (u, 'REVISION_PATH', 'etc/revision'),
            (u, 'INSTALL_DIR', 'opt/code'), (u, 'SYSTEMD_DIR', 'etc/units'),
            (d, 'ROLLBACK_DIR', 'root-backup'), (guard, 'LOCK_PATH', 'data/operation.lock'),
            (remote, 'JOB_LOCK', 'data/job.lock'), (remote, 'POLICY_PATH', 'data/policy.json'),
            (update_auth, 'DEFAULT_SETTINGS_PATH', 'data/runtime.json')]:
            item = patch.object(module, key, self.root / path)
            item.start(); self.addCleanup(item.stop)
        for folder in ('data', 'etc/units', 'opt/code'): (self.root / folder).mkdir(parents=True, exist_ok=True)
        u.VERSION_PATH.write_text('0.6.0'); u.REVISION_PATH.write_text('a'*40)
        (u.INSTALL_DIR / 'old.py').write_text('old code')
        for unit in u.SYSTEMD_UNITS: (u.SYSTEMD_DIR / unit).write_text('old unit')
        (self.root / 'data/program.nc').write_bytes(b'O100\r\nM30\r\n')
        update_auth.DEFAULT_SETTINGS_PATH.write_text(json.dumps({'paired_agent': {'token': 'owner'}, 'program_source': {'type': 'local'}}))
        self.value = dict(available=True, downloaded=True, phase='available', current_version='0.6.0', latest_version='0.7.0', latest_revision='b'*40)
        with tarfile.open(u.ARCHIVE_PATH, 'w:gz') as archive:
            contents = {'VERSION': b'0.7.0', 'machines.py': b'# new', 'qt_app/__init__.py': b'', 'zeuz_core/__init__.py': b''}
            contents.update({'systemd/' + unit: b'new unit' for unit in u.SYSTEMD_UNITS})
            for name, content in contents.items():
                info = tarfile.TarInfo('repo/' + name); info.size = len(content)
                archive.addfile(info, io.BytesIO(content))
        self.value['archive_sha256'] = hashlib.sha256(u.ARCHIVE_PATH.read_bytes()).hexdigest()
        u._write_state(u.STATE_PATH, self.value); self.calls = []
    def service(self, *args):
        self.calls.append(args)
        if args[0] == 'is-active': raise subprocess.CalledProcessError(3, args)
    def verify(self, value, target): shutil.copy2(u.ARCHIVE_PATH, target)

class DeploymentTests(UpdateFixture):
    def test_install_verifies_health_without_touch_preserves_data(self):
        result = d.apply_managed_update(verify=self.verify, systemctl=self.service, healthy=lambda _: True)
        self.assertEqual(result['phase'], 'succeeded')
        self.assertEqual(u.VERSION_PATH.read_text().strip(), '0.7.0')
        self.assertTrue((u.INSTALL_DIR / 'machines.py').exists())
        self.assertFalse((d.ROLLBACK_DIR / 'ready').exists())
        self.assertNotIn(('stop', 'zeuz-dnc-qt.service'), self.calls)
        self.assertEqual((self.root / 'data/program.nc').read_bytes(), b'O100\r\nM30\r\n')
        self.assertEqual(update_auth.paired_token(), 'owner')
    def test_unhealthy_version_restores_code_units_metadata(self):
        result = d.apply_managed_update(verify=self.verify, systemctl=self.service, healthy=lambda _: False)
        self.assertEqual(result['phase'], 'rolled_back')
        self.assertEqual((u.INSTALL_DIR / 'old.py').read_text(), 'old code')
        self.assertEqual(u.VERSION_PATH.read_text(), '0.6.0')
        self.assertEqual(u.REVISION_PATH.read_text(), 'a'*40)
        self.assertEqual((u.SYSTEMD_DIR / u.SYSTEMD_UNITS[0]).read_text(), 'old unit')
        self.assertEqual(update_auth.paired_token(), 'owner')
    def test_active_transfer_prevents_install_or_restart(self):
        with guard.OperationLease():
            result = d.apply_managed_update(verify=Mock(side_effect=AssertionError()), systemctl=self.service)
        self.assertEqual(result['phase'], 'waiting_idle'); self.assertEqual(self.calls, [])
        self.assertTrue((u.INSTALL_DIR / 'old.py').exists())
    def test_update_excludes_transfer_across_processes(self):
        script = "from pathlib import Path; from zeuz_core.operation_guard import OperationLease,Busy; import sys\ntry: OperationLease(path=Path(sys.argv[1]))\nexcept Busy: sys.exit(17)\n"
        with guard.OperationLease(update=True):
            result = subprocess.run([sys.executable, '-c', script, str(guard.LOCK_PATH)], capture_output=True)
        self.assertEqual(result.returncode, 17, result.stderr)
    def test_changed_official_channel_rejects_revision(self):
        with patch.object(u, '_fetch_json', return_value={'sha': 'c'*40}):
            with self.assertRaisesRegex(RuntimeError, 'canal oficial cambió'):
                d.verify_source(self.value, self.root / 'verified.tar.gz')
    def test_hash_mismatch_does_not_stop_api(self):
        response = io.BytesIO(b'official archive')
        response.geturl = lambda: f'https://codeload.github.com/{u.REPOSITORY}/archive'
        with patch.object(u, '_fetch_json', return_value={'sha': 'b'*40}), patch.object(u, '_fetch_text', return_value='0.7.0'), patch('urllib.request.urlopen', return_value=response):
            result = d.apply_managed_update(systemctl=self.service)
        self.assertEqual(result['phase'], 'failed'); self.assertIn('artefacto', result['error'])
        self.assertEqual(self.calls, []); self.assertEqual(u.VERSION_PATH.read_text(), '0.6.0')
    def test_interrupted_install_restores_complete_snapshot(self):
        d.snapshot(); shutil.rmtree(u.INSTALL_DIR); u.VERSION_PATH.write_text('0.7.0')
        self.assertTrue(d.restore_snapshot()); self.assertTrue((u.INSTALL_DIR / 'old.py').exists())
        self.assertEqual(u.VERSION_PATH.read_text(), '0.6.0')

    def test_bootstrap_restores_without_importing_broken_application(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("zeuz_update_runner", Path(__file__).parents[1] / "packaging/update_runner.py")
        runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)
        d.snapshot(); shutil.rmtree(u.INSTALL_DIR); u.VERSION_PATH.write_text('0.7.0')
        report, run = Mock(), Mock()
        self.assertTrue(runner.recover(install=u.INSTALL_DIR, backup=d.ROLLBACK_DIR, metadata=u.VERSION_PATH.parent, systemd=u.SYSTEMD_DIR, report=report, run=run))
        self.assertEqual((u.INSTALL_DIR / 'old.py').read_text(), 'old code')
        self.assertEqual(u.VERSION_PATH.read_text(), '0.6.0')
        self.assertFalse((d.ROLLBACK_DIR / 'ready').exists())
        report.assert_called_once_with(True)


class RemoteAPITests(UpdateFixture):
    def setUp(self):
        super().setUp()
        self.server = Server(('127.0.0.1', 0), HeadlessController())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'; self.addCleanup(self.close)
    def close(self):
        self.server.updates.stop(); self.server.shutdown(); self.server.server_close(); self.thread.join()
    def request(self, method, path, body=None, token='owner'):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
            method=method, headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req) as response: return response.status, json.load(response)
        except urllib.error.HTTPError as exc: return exc.code, json.load(exc)
    def test_management_requires_owner_token_blocks_repair(self):
        for path in ('/api/update/status', '/api/update/check', '/api/update/install', '/api/update/policy'):
            status, _ = self.request('GET' if path.endswith('status') else 'POST', path, {} if not path.endswith('status') else None, token='attacker')
            self.assertEqual(status, 401)
        self.assertEqual(self.request('POST', '/api/agent/pair', {'url': 'http://attacker', 'code': '123456'}, token='attacker')[0], 403)
        status, value = self.request('GET', '/api/update/status')
        self.assertEqual(status, 200); self.assertFalse(value['auto_install'])
    def test_rejects_url_wrong_revision_invalid_policy(self):
        self.assertEqual(self.request('POST', '/api/update/install', {'url': 'https://attacker/x'})[0], 400)
        self.assertEqual(self.request('POST', '/api/update/install', {'revision': 'c'*40, 'request_id': str(uuid.uuid4())})[0], 409)
        self.assertEqual(self.request('POST', '/api/update/policy', {'auto_install': 'yes'})[0], 400)
        self.assertEqual(self.request('POST', '/api/update/policy', {'auto_install': True})[0], 200)
        self.assertTrue(remote.read_policy()['auto_install'])
    def test_install_idempotent_waits_for_transfer(self):
        request_id = str(uuid.uuid4()); payload = {'revision': 'b'*40, 'request_id': request_id}
        with guard.OperationLease(), patch.object(u, 'download_update') as download:
            first = self.request('POST', '/api/update/install', payload)
            second = self.request('POST', '/api/update/install', payload)
            self.assertEqual(first[0], 200); self.assertEqual(second[0], 200)
            self.assertEqual(second[1]['request_id'], request_id); self.assertEqual(second[1]['phase'], 'waiting_idle')
            download.assert_not_called(); self.server.updates.stop(); self.server.updates.worker.join(timeout=2)
    def test_mobile_management_rejects_replaceable_mobile_token(self):
        from zeuz_core import mobile_api
        with patch.object(mobile_api, 'credentials', return_value={'mobile_token': 'attacker', 'pairing_code': '123456'}):
            self.assertEqual(self.request('GET', '/v1/dnc/update/status?machine_id=one', token='attacker')[0], 401)

    def test_agent_proxy_and_offline_pi_fallback_use_management_token(self):
        from zeuzagent.config import AgentConfig
        from zeuzagent.library import ProgramLibrary
        from zeuzagent.machines import MachineRegistry
        from zeuzagent.server import create_server
        registry = MachineRegistry(self.root / 'agent-machines.json')
        machine = registry.save(dict(name='Torno', dnc_host='127.0.0.1', dnc_port=self.server.server_port,
            baudrate=9600, bytesize=8, parity='N', stopbits=1, flow_control='none', line_terminator='CRLF'))
        config = AgentConfig(name='Test', programs_dir=str(self.root / 'data'), host='127.0.0.1', port=0, api_token='owner', pairing_code='123456', discovery=False)
        agent = create_server(config, ProgramLibrary(self.root / 'data'), registry)
        thread = threading.Thread(target=agent.serve_forever, daemon=True); thread.start()
        try:
            req = urllib.request.Request(f'http://127.0.0.1:{agent.server_port}/v1/dnc/update/status?machine_id={machine["id"]}', headers={'Authorization':'Bearer owner'})
            with urllib.request.urlopen(req) as response: value = json.load(response)
            self.assertTrue(value['supported']); self.assertEqual(value['latest_revision'], 'b'*40)
        finally:
            agent.shutdown(); agent.server_close(); thread.join()
        from zeuz_core import mobile_api, workshop_routes
        with patch.object(mobile_api, 'credentials', return_value={'mobile_token':'owner', 'pairing_code':'123456'}), patch.object(workshop_routes, 'route_for', return_value={'local':True}):
            status, value = self.request('GET', '/v1/dnc/update/status?machine_id=one')
        self.assertEqual(status, 200); self.assertTrue(value['supported'])

    def test_public_configuration_cannot_redirect_management_or_expose_pairing(self):
        self.assertEqual(self.request('POST', '/api/workshop/configure', {'machine_routes': []}, token='attacker')[0], 403)
        from zeuz_core import mobile_api, workshop
        with patch.object(mobile_api, 'credentials', return_value={'mobile_token':'owner', 'pairing_code':'123456', 'name':'Test'}):
            value = workshop.dispatch('GET', '/api/workshop/info')
        self.assertNotIn('mobile_token', value)
        self.assertNotIn('pairing_code', value)

    def test_requested_install_continues_after_client_disconnects(self):
        def downloaded(value, **kwargs):
            value['downloaded'] = True
            return u._write_state(u.STATE_PATH, value)
        def start(*args, **kwargs):
            self.server.updates._write('installing')
        with patch.object(u, 'download_update', side_effect=downloaded) as download, patch.object(remote.subprocess, 'run', side_effect=start) as service:
            with guard.OperationLease():
                status, value = self.request('POST', '/api/update/install', {'revision':'b'*40, 'request_id':str(uuid.uuid4())})
                self.assertEqual(status, 200); self.assertEqual(value['phase'], 'waiting_idle')
                download.assert_not_called()
            # No subsequent phone/Agent request: the Pi worker finishes preparation.
            self.server.updates.worker.join(timeout=4)
            self.assertFalse(self.server.updates.worker.is_alive())
            download.assert_called_once(); service.assert_called_once()
            self.assertEqual(u.read_update_state()['phase'], 'installing')

    def test_management_pairing_preserves_program_source(self):
        from zeuz_core import headless_api
        before = json.loads(update_auth.DEFAULT_SETTINGS_PATH.read_text())['program_source']
        with patch.object(headless_api, 'DEFAULT_SETTINGS_PATH', update_auth.DEFAULT_SETTINGS_PATH), patch.object(headless_api, 'pair', return_value={'token':'owner'}):
            value = HeadlessController.pair_agent('http://127.0.0.1:9999', '123456', management_only=True)
        self.assertTrue(value['ok'])
        self.assertEqual(json.loads(update_auth.DEFAULT_SETTINGS_PATH.read_text())['program_source'], before)


if __name__ == '__main__': unittest.main()
