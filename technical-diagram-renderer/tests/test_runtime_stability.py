"""Runtime failures must terminate predictably before publication."""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
SPEC = importlib.util.spec_from_file_location('runtime_renderer', SCRIPTS / 'render-diagram.py')
renderer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(renderer)


class RuntimeStabilityTests(unittest.TestCase):
    def test_hung_child_is_bounded_and_classified(self):
        with patch.object(renderer, 'PROCESS_TIMEOUT_SECONDS', 0.02, create=True):
            with self.assertRaisesRegex(renderer.RenderError, 'timed out'):
                renderer._run([sys.executable, '-c', 'import time; time.sleep(0.25)'], purpose='synthetic child')

    def test_invalid_utf8_and_deep_json_are_classified(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'input.json'
            for raw in (b'\xff', b'{"nested":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}'):
                path.write_bytes(raw)
                with self.subTest(raw_size=len(raw)), self.assertRaises(renderer.RenderError):
                    renderer._load_json(path)

    def test_oversized_input_is_rejected_before_decoding(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'input.json'
            path.write_bytes(b'{}' + b' ' * 100)
            with patch.object(renderer, 'MAX_INPUT_BYTES', 16, create=True):
                with self.assertRaisesRegex(renderer.RenderError, 'limit'):
                    renderer._load_json(path)

    def test_layout_budget_is_enforced_before_layout(self):
        with patch.object(renderer, 'MAX_NODES', 2, create=True):
            with self.assertRaisesRegex(renderer.RenderError, 'nodes.*limit'):
                renderer.normalize_diagram('architecture', {'nodes': [{'id': str(i)} for i in range(3)], 'arrows': []})

    def test_interrupt_rolls_back_already_published_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage = root / 'stage'
            stage.mkdir()
            destinations = {'svg': root / 'result.svg', 'json': root / 'result.json'}
            staged = {'svg': stage / 'new.svg', 'json': stage / 'new.json'}
            for key, path in destinations.items():
                path.write_text('old-' + key, encoding='utf-8')
                staged[key].write_text('new-' + key, encoding='utf-8')
            original = renderer.os.replace
            def interrupt_second(source, destination):
                if Path(source) == staged['json']:
                    raise KeyboardInterrupt('synthetic interrupt')
                return original(source, destination)
            with patch.object(renderer.os, 'replace', side_effect=interrupt_second):
                with self.assertRaises(KeyboardInterrupt):
                    renderer._atomic_publish(staged, destinations, stage)
            self.assertEqual(destinations['svg'].read_text(encoding='utf-8'), 'old-svg')
            self.assertEqual(destinations['json'].read_text(encoding='utf-8'), 'old-json')

    def test_timeout_preserves_existing_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            input_path = Path(temporary) / 'input.json'
            input_path.write_text('{"nodes": [], "arrows": []}', encoding='utf-8')
            output = Path(temporary) / 'result.svg'
            output.write_bytes(b'previous')
            with patch.object(renderer, '_run', side_effect=renderer.RenderError('synthetic timed out')):
                self.assertEqual(renderer.main(['--type', 'architecture', '--input', str(input_path),
                                                '--output', str(output.with_suffix(''))]), 1)
            self.assertEqual(output.read_bytes(), b'previous')
            self.assertFalse(output.with_suffix('.json').exists())


if __name__ == '__main__':
    unittest.main()
