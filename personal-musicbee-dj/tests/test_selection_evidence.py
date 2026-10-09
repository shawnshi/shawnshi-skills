"""Bounded synthetic acceptance tests for metadata gates, scoring, reports and preview."""
from pathlib import Path
from unittest.mock import Mock
import pytest
import yaml
import src.cli as cli
from src.core.attributes import LANGUAGE_ALIASES, MOOD_ALIASES, values, requested_values, evidence_score
from src.core.curator import DJCurator
from test_runtime import config, track, song, write_library
from test_export_contract import load_record


def records():
    result = [track(i, bpm=80) for i in range(1, 5)]
    for t in result:
        t.dj_scene = 'focus'
        t.dj_energy = 'low'
        t.dj_vocals = 'vocal'
    result[0].language = 'eng'
    result[1].language = '中文; English'
    result[2].language = ''
    result[3].dj_vocals = 'instrumental'
    return result


def test_language_normalisation_never_uses_genre_or_country():
    assert values('英语; EN; eng', LANGUAGE_ALIASES) == {'eng'}
    assert values('France; Jap; 日本', LANGUAGE_ALIASES) == {'jpn'}
    assert values('unknown; France', LANGUAGE_ALIASES) == set()


@pytest.mark.parametrize('spec,expected', [
    ({'languages':['eng']}, [1,2,4]),
    ({'languages':['中文']}, [2,4]),
    ({'exclude_languages':['zho']}, [1,4]),
])
def test_language_hard_gate_retains_known_instrumental_but_not_unknown_language(config, spec, expected):
    config['request'] = spec
    assert [t.id for t in DJCurator(config)._filter_by_intensity(records(),'normal')] == expected


def test_language_unknown_vocals_are_not_instrumental(config):
    config['request'] = {'languages':['eng']}
    t = track(1);t.dj_vocals='unknown';t.language='';t.genre='Instrumental'
    assert DJCurator(config)._filter_by_intensity([t],'normal') == []


@pytest.mark.parametrize('spec', [
    {'languages':['France']}, {'moods':['not calm']}, {'languages':['eng'],'exclude_languages':['en']},
    {'bpm_min':100,'bpm_max':90}, {'bpm_min':True}, {'bpm_max':float('inf')}
])
def test_invalid_or_conflicting_metadata_requests_rejected(config, spec):
    config['request'] = spec
    with pytest.raises(ValueError):DJCurator(config)


def test_mood_exact_gate_does_not_infer_from_genre(config):
    config['request'] = {'moods':['warm']}
    items = records()
    items[0].mood = '温暖'
    items[1].mood = 'not warm'
    items[2].mood = 'unknown';items[2].genre='Jazz'
    assert [t.id for t in DJCurator(config)._filter_by_intensity(items,'normal')] == [1]


def test_bpm_bound_cannot_be_bypassed_by_energy_tag(config):
    config['request'] = {'bpm_min':120,'bpm_max':150}
    items = records()
    for t,bpm in zip(items,[0,119,140,160]):t.bpm=bpm;t.dj_energy='high'
    assert [t.id for t in DJCurator(config)._filter_by_intensity(items,'high')] == [3]


def test_no_missing_feature_renormalisation():
    a=evidence_score({'scene':(1,1,'DJ_SCENE'),'mood':(0,0,'missing'),'energy':(0,0,'missing')})
    assert a['match_score'] == a['evidence_coverage'] < .5
    assert evidence_score({})['match_score'] == 0


def test_arousal_moods_not_double_scored_as_emotional_colour(config):
    config['request']={'prefer_moods':['calm']}
    dj=DJCurator(config);dj.score_scene='focus';dj.score_intensity='low'
    item=records()[0];item.mood='calm'
    assert 'mood' not in dj._track_evidence(item)['components']
    assert 'energy' in dj._track_evidence(item)['components']


def test_arousal_mood_soft_preference_works_when_energy_not_scored(config):
    config['request']={'prefer_moods':['calm']}
    dj=DJCurator(config)
    value=track(1);value.mood='calm'
    assert dj._track_evidence(value)['components']['mood']['match']==1


def test_quota_selection_ranks_evidence_before_artist_preference(config):
    config['request']={'prefer_artists':['weak'],'seed':5}
    dj=DJCurator(config);dj.score_scene='focus';dj.score_intensity='low'
    weak,strong=track(1),track(2)
    weak.artist='weak';weak.genre='Jazz'
    strong.artist='strong';strong.dj_scene='focus';strong.dj_energy='low';strong.mood='neutral'
    assert dj._track_evidence(strong)['match_score'] > dj._track_evidence(weak)['match_score']
    assert dj._select_ratio_tracks([weak,strong],1)==[strong]


def test_metadata_export_mood_tempo_language_multi_values(tmp_path):
    item=load_record(tmp_path,{'语言':'中文;English','Language1':'eng','情绪':'温暖','Mood1':'joyful','速度':'fast'})
    assert item.language=='中文; English; eng'
    assert item.mood=='温暖; joyful'
    assert item.tempo=='fast'
    assert item.bpm==0


def test_dry_selection_never_exports_and_reports_missing_evidence_and_quota_shortfall(config,tmp_path,monkeypatch):
    item=track(1,tmp_path/'one.flac');Path(item.local_path).touch()
    item.dj_scene='focus';item.dj_energy='low';item.genre='Unknown'
    dj=DJCurator(config)
    monkeypatch.setattr(dj.parser,'load_library',lambda:[item])
    monkeypatch.setattr(dj,'_export_to_m3u',Mock(side_effect=AssertionError('no export')))
    result=dj.generate_m3u('scene','focus','low',export=False,explain=True)
    assert result and result.exported_tracks==1 and not result.is_playable
    assert result.selection_diagnostics['candidate_shortfall']>0
    assert result.selection_diagnostics['mean_evidence_coverage']<1
    assert 'mood' in result.selection_diagnostics['tracks'][0]['unknown_fields']
    assert sum(result.selection_diagnostics['quota_actual'].values())==1
    assert result.selection_diagnostics['weak_genre_scene_fallback_tracks']==0


def test_strict_evidence_rejects_legacy_scene_energy_and_vocals(config):
    config['request']={'strict_evidence':True,'no_vocals':True}
    dj=DJCurator(config);dj.score_scene='focus';dj.score_intensity='low'
    t=track(1,bpm=70);t.genre='Instrumental'
    assert dj._metadata_rejection(t)=='missing_required_explicit_scene'
    t.dj_scene='focus'
    assert dj._metadata_rejection(t)=='missing_required_explicit_energy'
    t.dj_energy='low'
    assert dj._metadata_rejection(t)=='missing_required_explicit_instrumental'
    t.dj_vocals='instrumental'
    assert dj._filter_by_intensity([t],'low')==[t]


def test_missing_dates_never_count_as_novelty(config):
    items=[track(i,date='') for i in range(1,5)]
    dj=DJCurator(config);chosen=dj._select_ratio_tracks(items,4)
    assert len(chosen)==4
    assert 'novelty' not in dj.selection_buckets.values()


def test_current_presets_no_longer_use_language_or_region_as_genre():
    cfg=yaml.safe_load((Path(__file__).parents[1]/'config.yaml').read_text(encoding='utf-8'))
    for scene in cfg['scenes'].values():
        assert not {g.casefold() for g in scene['genres']} & {'eng','chs','jap','korean','france'}


def test_cli_read_only_preview_bypasses_platform_player_process_and_tempfiles(config,tmp_path,monkeypatch,capsys):
    cfg=config.copy();cfg['musicbee']=dict(config['musicbee'],exe_path=str(tmp_path/'not-installed.exe'))
    original_output=Path(cfg['playlist']['output_m3u'])
    monkeypatch.setattr(cli,'load_config',lambda _:cfg)
    monkeypatch.setattr(cli.sys,'platform','linux')
    monkeypatch.setattr(cli,'musicbee_running',Mock(side_effect=AssertionError('no process probe')))
    monkeypatch.setattr(cli.tempfile,'mkdtemp',Mock(side_effect=AssertionError('no temporary task')))
    monkeypatch.setattr(cli.subprocess,'Popen',Mock(side_effect=AssertionError('no player')))
    monkeypatch.setattr(cli.sys,'argv',['cli.py','--type','scene','--value','focus','--dry-run','--explain','--seed','1'])
    cli.main()
    out=capsys.readouterr().out
    assert '"mode": "read_only"' in out and 'weak_Genre_fallback' in out
    assert not original_output.exists()
    assert not (tmp_path/'cache.json').exists()


@pytest.mark.parametrize('args', [
    ['--type','playlist','--value','x','--language','eng'],
    ['--type','playlist','--value','x','--dry-run'],
    ['--type','scene','--value','focus','--dry-run','--queue','last'],
    ['--type','scene','--value','focus','--language','France'],
    ['--type','scene','--value','focus','--bpm-min','130','--bpm-max','100'],
    ['--check','--mood','warm'],
    ['--cleanup-task','x','--prefer-mood','warm'],
])
def test_cli_invalid_combination_never_loads_data_or_launches(monkeypatch,args):
    monkeypatch.setattr(cli,'load_config',Mock(side_effect=AssertionError('no config read')))
    monkeypatch.setattr(cli.subprocess,'Popen',Mock(side_effect=AssertionError('no player')))
    monkeypatch.setattr(cli.sys,'argv',['cli.py',*args])
    with pytest.raises(SystemExit) as exc:cli.main()
    assert exc.value.code==2
