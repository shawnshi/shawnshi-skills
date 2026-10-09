from pathlib import Path
import math
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.core.audio_analysis import full_vocal_plan, AudioAnalysisError
from src.core.audio_classifier import OfflineClassifier
from src.core.local_paths import local_regular_file, local_path


class CoverageTests(unittest.TestCase):
    def test_full_plan_has_no_gaps_including_short_tail(self):
        for duration in (8, 10, 10.01, 16, 27, 180, 1199.9, 1200, 1200.01, 3600.7):
            windows = list(full_vocal_plan(duration))
            reached = 0
            for window in windows:
                self.assertLessEqual(window['start_seconds'], reached)
                self.assertGreaterEqual(window['duration_seconds'], 8)
                self.assertLessEqual(window['duration_seconds'], 10)
                reached = max(reached, window['start_seconds'] + window['duration_seconds'])
            self.assertAlmostEqual(reached, duration)
            self.assertLessEqual(len(windows), math.ceil(duration / 10))
        self.assertTrue(any(w['start_seconds'] <= 60 and w['start_seconds']+w['duration_seconds'] >= 65
                            for w in full_vocal_plan(180)))

    def test_short_and_invalid_recordings_rejected(self):
        for duration in (0, 7.99, float('inf'), float('nan')):
            with self.assertRaises(AudioAnalysisError):
                full_vocal_plan(duration)

    def fake_engine(self):
        engine = object.__new__(OfflineClassifier)
        def score(window):
            vocal = window['start_seconds'] == 60
            return {('DJ_VOCALS','vocal'): .4 if vocal else .1,
                    ('DJ_VOCALS','instrumental'): .1 if vocal else .4}, 'pcm'
        engine._audio_scores = score
        return engine

    def test_sparse_vocals_defeat_whole_track_instrumental_candidate(self):
        with patch('src.core.audio_analysis.decode_clip', side_effect=lambda path, window, ffmpeg, timeout: window):
            result = self.fake_engine().scan_full_vocals('fixture',180,'fixture')
        self.assertTrue(result['coverage_complete'])
        self.assertEqual(result['suggested_value'], 'vocal')
        self.assertEqual(len(result['windows']), 18)
        self.assertFalse(result['whole_track_absence_verified'])
        self.assertFalse(result['automatic_tag_write_eligible'])

    def test_complete_negative_is_still_unreviewed_not_verified(self):
        engine = self.fake_engine()
        engine._audio_scores = lambda pcm: ({('DJ_VOCALS','vocal'):.1,('DJ_VOCALS','instrumental'):.4},'pcm')
        with patch('src.core.audio_analysis.decode_clip', return_value='pcm'):
            result = engine.scan_full_vocals('fixture',27,'fixture')
        self.assertTrue(result['coverage_complete'])
        self.assertEqual(result['suggested_value'],'instrumental')
        self.assertFalse(result['whole_track_absence_verified'])

    def test_time_budget_and_decode_error_never_yield_instrumental(self):
        engine = self.fake_engine()
        with patch('src.core.audio_classifier.time.monotonic', side_effect=[0, 121]):
            result = engine.scan_full_vocals('fixture',180,'fixture')
        self.assertFalse(result['coverage_complete'])
        self.assertIsNone(result['suggested_value'])
        with patch('src.core.audio_analysis.decode_clip', side_effect=AudioAnalysisError('fixture')):
            result = engine.scan_full_vocals('fixture',180,'fixture')
        self.assertEqual(result['status'],'voice_scan_error')
        self.assertIsNone(result['suggested_value'])

    def test_silence_is_not_an_instrumental_proof(self):
        engine = self.fake_engine();engine._audio_scores=lambda pcm:(None,'pcm')
        with patch('src.core.audio_analysis.decode_clip', return_value='pcm'):
            result = engine.scan_full_vocals('fixture',27,'fixture')
        self.assertEqual(result['status'],'insufficient_non_silent_segments')
        self.assertIsNone(result['suggested_value'])

    def test_sampled_instrumental_is_suppressed(self):
        engine = object.__new__(OfflineClassifier)
        groups = {'DJ_VOCALS':['instrumental','vocal'],'DJ_ENERGY':['low','high'],'mood':['calm','warm']}
        engine.groups = {(f, v):[] for f, values in groups.items() for v in values}
        scores = {(f, v): .4 if i==0 else .1 for f, values in groups.items() for i,v in enumerate(values)}
        scores.update({('DJ_SCENE','focus','positive'):.4,('DJ_SCENE','focus','contrast'):.1})
        engine._audio_scores=lambda pcm:(scores,'pcm')
        result=engine.classify(['pcm']*3,{'focus'})
        self.assertIsNone(result['fields']['DJ_VOCALS']['suggested_value'])
        self.assertEqual(result['fields']['DJ_VOCALS']['status'],'insufficient_coverage_for_instrumental')


@unittest.skipUnless(os.name=='nt','Windows-specific filesystem controls')
class WindowsPathTests(unittest.TestCase):
    def test_remote_and_indeterminate_drives_denied_before_stat(self):
        import ctypes
        for kind in (0,1,4):
            library=MagicMock();library.GetDriveTypeW.return_value=kind
            with patch.object(ctypes,'WinDLL',return_value=library), patch.object(Path,'is_file') as stat_file, \
                 patch.object(Path,'is_symlink') as link_check:
                with self.assertRaisesRegex(ValueError,'drive'):
                    local_regular_file('Z:/owned-fixture.mp3')
                stat_file.assert_not_called();link_check.assert_not_called()

    def test_junction_denied_before_leaf_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'file.mp3';path.write_bytes(b'fixture')
            with patch.object(Path,'is_junction',return_value=True), patch.object(Path,'is_file') as stat_file:
                with self.assertRaisesRegex(ValueError,'junction'):
                    local_regular_file(path)
                stat_file.assert_not_called()

    def test_real_owned_junction_rejected(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target=root/'target';target.mkdir();(target/'fixture.mp3').write_bytes(b'fixture')
            link=root/'junction'
            result=subprocess.run(['cmd','/c','mklink','/J',str(link),str(target)],capture_output=True,timeout=10)
            if result.returncode:self.skipTest('OS denied owned junction fixture')
            try:
                with self.assertRaises(ValueError):local_regular_file(link/'fixture.mp3')
                self.assertEqual((target/'fixture.mp3').read_bytes(),b'fixture')
            finally:os.rmdir(link)

    def test_local_file_and_directory_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'fixture.mp3';path.write_bytes(b'fixture')
            self.assertEqual(local_regular_file(path),path)
            self.assertEqual(local_path(Path(tmp)),Path(tmp))


if __name__=='__main__':unittest.main()
