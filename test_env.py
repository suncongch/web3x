import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class EnvironmentConfigTest(unittest.TestCase):
    def test_dotenv_public_url_overrides_environment_but_other_values_do_not(self):
        project = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            for name in ('app.py', 'three_xui.py', 'subscription.py', 'clash_config.py'):
                shutil.copy(project / name, directory / name)
            (directory / '.env').write_text(
                'XUI_BASE_URL=http://127.0.0.1:1234/panel\n'
                'XUI_USERNAME=from-file\n'
                'XUI_PASSWORD=example-password\n'
                'PUBLIC_BASE_URL=http://192.168.2.17:8000\n',
                encoding='utf-8',
            )
            env = os.environ.copy()
            for key in ('XUI_BASE_URL', 'XUI_USERNAME', 'XUI_PASSWORD', 'PUBLIC_BASE_URL'):
                env.pop(key, None)
            env['XUI_USERNAME'] = 'from-environment'
            env['PUBLIC_BASE_URL'] = 'http://127.0.0.1:8000'
            subprocess.run(
                [sys.executable, '-c',
                 'import app; from subscription import public_url; '
                 'from three_xui import ThreeXUI; panel = ThreeXUI(); '
                 'assert panel.base_url == "http://127.0.0.1:1234/panel"; '
                 'assert panel.username == "from-environment"; '
                 'assert panel.password == "example-password"; '
                 'assert public_url() == "http://192.168.2.17:8000"'],
                cwd=directory.parent, env={**env, 'PYTHONPATH': str(directory)},
                check=True,
            )
            (directory / '.env').write_text('XUI_USERNAME=from-file\n', encoding='utf-8')
            subprocess.run(
                [sys.executable, '-c',
                 'import app; from subscription import public_url; '
                 'assert public_url() == "http://127.0.0.1:8000"'],
                cwd=directory.parent, env={**env, 'PYTHONPATH': str(directory)},
                check=True,
            )


if __name__ == '__main__':
    unittest.main()
