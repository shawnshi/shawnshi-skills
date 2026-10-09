from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.core import runtime_support as runtime


class RuntimeTests(unittest.TestCase):
    def tearDown(self):
        runtime.verify_runtime.cache_clear()

    def test_actual_isolated_runtime_accepted(self):
        runtime.verify_runtime.cache_clear()
        result=runtime.verify_runtime()
        self.assertTrue(result['isolated_site_packages'])
        self.assertEqual(result['verified_production_packages'],59)

    def test_global_interpreter_rejected(self):
        runtime.verify_runtime.cache_clear()
        with patch.object(runtime.sys,'prefix',sys.base_prefix):
            with self.assertRaisesRegex(RuntimeError,'isolated virtual'):
                runtime.verify_runtime()

    def test_python_version_drift_rejected(self):
        runtime.verify_runtime.cache_clear()
        with patch.object(runtime.sys,'version_info',(3,13,0)):
            with self.assertRaisesRegex(RuntimeError,'Python'):
                runtime.verify_runtime()

    def test_package_version_drift_rejected(self):
        runtime.verify_runtime.cache_clear()
        original=runtime.metadata.distribution
        def changed(name):
            result=original(name)
            if name=='numpy':
                from types import SimpleNamespace
                return SimpleNamespace(version='0.0.0',locate_file=result.locate_file)
            return result
        with patch.object(runtime.metadata,'distribution',side_effect=changed):
            with self.assertRaisesRegex(RuntimeError,'version/origin'):
                runtime.verify_runtime()

    def test_global_package_origin_rejected(self):
        runtime.verify_runtime.cache_clear()
        original=runtime.metadata.distribution
        def changed(name):
            result=original(name)
            if name=='numpy':
                from types import SimpleNamespace
                return SimpleNamespace(version=result.version,locate_file=lambda item:Path(sys.base_prefix)/'Lib/site-packages')
            return result
        with patch.object(runtime.metadata,'distribution',side_effect=changed):
            with self.assertRaisesRegex(RuntimeError,'version/origin'):
                runtime.verify_runtime()

    def test_durable_default_not_under_temp(self):
        root=runtime.default_runtime_root()
        self.assertNotIn('temp',[p.lower() for p in root.parts])
        self.assertTrue((root/'venv/Scripts/python.exe').is_file())
        self.assertTrue((root/'models/clap/model.safetensors').is_file())


if __name__=='__main__':unittest.main()
