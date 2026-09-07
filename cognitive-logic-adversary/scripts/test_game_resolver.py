"""LA-01/02/03: input, CLI exit, and unchanged scoring regressions."""
import contextlib
import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import game_resolver as resolver

SCRIPT = Path(__file__).with_name('game_resolver.py')


def valid_option():
    return {'name': 'A', 'agent_scores': [0.8, 0.6], 'friction': 0.2, 'risk_level': 'medium'}


class GameResolverTests(unittest.TestCase):
    def cli(self, *args):
        return subprocess.run([sys.executable, '-B', str(SCRIPT), *map(str, args)],
                              capture_output=True, text=True, encoding='utf-8', timeout=30)

    def assert_error(self, result):
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'Error')
        self.assertEqual(result.stderr, '')

    def test_cli_input_errors_are_one_json_and_nonzero(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bad_json = root / 'bad.json'
            bad_json.write_text('{', encoding='utf-8')
            bad_utf8 = root / 'encoding.json'
            bad_utf8.write_bytes(b'\xff')
            schema = root / 'schema.json'
            schema.write_text('{}', encoding='utf-8')
            for path in (root/'missing.json', root, bad_json, bad_utf8, schema):
                with self.subTest(path=path.name):
                    self.assert_error(self.cli(path))

    def test_cli_usage_errors_are_json(self):
        self.assert_error(self.cli())
        self.assert_error(self.cli('input.json', '--unknown'))

    def test_permission_error_is_predictable(self):
        with patch.object(sys, 'argv', ['resolver', 'input.json']), \
             patch('builtins.open', side_effect=PermissionError('synthetic denied')), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(resolver.main(), 2)
        self.assertEqual(json.loads(output.getvalue())['status'], 'Error')

    def test_unexpected_exception_is_not_masked(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'input.json'
            path.write_text(json.dumps({'options': [valid_option()]}), encoding='utf-8')
            with patch.object(sys, 'argv', ['resolver', str(path)]), \
                 patch.object(resolver.GameTheoryResolver, 'resolve_consensus',
                              side_effect=RuntimeError('synthetic defect')), \
                 self.assertRaisesRegex(RuntimeError, 'synthetic defect'):
                resolver.main()

    def test_top_level_and_option_shapes(self):
        invalid = [None, [], {}, {'options': None}, {'options': []},
                   {'options': {}}, {'options': [None]}, {'options': [{}]}]
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(ValueError):
                resolver.GameTheoryResolver(data)

    def test_names_and_duplicate_names_rejected(self):
        for name in (None, '', '  ', 1, [], {}):
            option = valid_option()
            option['name'] = name
            with self.subTest(name=name), self.assertRaises(ValueError):
                resolver.GameTheoryResolver({'options': [option]})
        with self.assertRaises(ValueError):
            resolver.GameTheoryResolver({'options': [valid_option(), valid_option()]})

    def test_scores_confidences_friction_and_risk_contract(self):
        invalid_numbers = [True, False, None, '0.5', [], {}, -0.1, 1.1,
                           float('nan'), float('inf'), -float('inf'), 10**400]
        for field in ('score', 'confidence', 'friction'):
            for value in invalid_numbers:
                option = valid_option()
                if field == 'friction':
                    option[field] = value
                else:
                    option['agent_scores'] = [{'score': 0.5, field: value}]
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    resolver.GameTheoryResolver({'options': [option]})
        for scores in ([], None, {}, [0.5, {}], [{}, 0.5], [{}], [True],
                       [{'score': 0.5, 'agent': []}]):
            option = valid_option()
            option['agent_scores'] = scores
            with self.subTest(scores=scores), self.assertRaises(ValueError):
                resolver.GameTheoryResolver({'options': [option]})
        for risk in ('typo', None, 1, [], {}):
            option = valid_option()
            option['risk_level'] = risk
            with self.subTest(risk=risk), self.assertRaises(ValueError):
                resolver.GameTheoryResolver({'options': [option]})

    def test_flat_structured_and_defaults_keep_formula(self):
        option = valid_option()
        flat = resolver.GameTheoryResolver({'options': [option]}).resolve_consensus()[0]
        self.assertEqual(flat, {'option': 'A', 'stability': 0.4284,
            'weighted_consensus': 0.7, 'consensus_distance': 0.1,
            'friction': 0.2, 'risk_level': 'medium', 'agent_count': 2,
            'score_range': [0.6, 0.8]})
        structured = copy.deepcopy(option)
        structured['agent_scores'] = [{'score': 0.8}, {'score': 0.6}]
        self.assertEqual(resolver.GameTheoryResolver({'options': [structured]}).resolve_consensus()[0], flat)
        structured['agent_scores'] = [{'agent': 'x', 'score': 0.8, 'confidence': 0.9},
                                     {'score': 0.6, 'confidence': 0.7}]
        model = resolver.GameTheoryResolver({'options': [structured]})
        self.assertAlmostEqual(model.weighted_consensus(structured), 0.7125)
        self.assertEqual(model.stability_score(structured), 0.4361)
        for risk in resolver.GameTheoryResolver.RISK_PENALTY:
            resolver.GameTheoryResolver({'options': [dict(option, risk_level=risk)]})
        default = {'name': 'default', 'agent_scores': [{'score': 1, 'confidence': 0}]}
        row = resolver.GameTheoryResolver({'options': [default]}).resolve_consensus()[0]
        self.assertEqual((row['stability'], row['friction'], row['risk_level']), (0, 0.5, 'medium'))

    def test_pareto_dominance_and_ties(self):
        options = [{'name': name, 'agent_scores': [score]} for name, score in [('A', .9), ('B', .1), ('C', .9)]]
        model = resolver.GameTheoryResolver({'options': options})
        self.assertEqual([x['option'] for x in model.pareto_frontier()], ['A', 'C'])

    def test_success_preserves_output_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'input.json'
            path.write_text(json.dumps({'options': [valid_option()]}), encoding='utf-8')
            result = self.cli(path, '--pareto', '--chart')
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(set(output), {'status', 'version', 'optimal_consensus_point',
                                      'full_analysis', 'pareto_frontier', 'stability_chart'})
        self.assertEqual(output['status'], 'Success')
        self.assertEqual(output['optimal_consensus_point'], output['full_analysis'][0])


if __name__ == '__main__':
    unittest.main()
