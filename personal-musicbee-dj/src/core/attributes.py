"""Metadata vocabulary and evidence scoring; no file, player or network access."""
import unicodedata

UNKNOWN = {'', 'unknown', '未知', '[未知]'}
LANGUAGE_ALIASES = {
    'en': 'eng', 'eng': 'eng', 'english': 'eng', '英语': 'eng', '英文': 'eng',
    'zh': 'zho', 'zho': 'zho', 'chi': 'zho', 'chs': 'zho', 'chinese': 'zho', '中文': 'zho', '汉语': 'zho',
    'ja': 'jpn', 'jpn': 'jpn', 'jap': 'jpn', 'japanese': 'jpn', '日语': 'jpn',
    'ko': 'kor', 'kor': 'kor', 'korean': 'kor', '韩语': 'kor',
    'fr': 'fra', 'fra': 'fra', 'fre': 'fra', 'french': 'fra', '法语': 'fra',
    'de': 'deu', 'deu': 'deu', 'ger': 'deu', 'german': 'deu', '德语': 'deu',
    'it': 'ita', 'ita': 'ita', 'italian': 'ita', '意大利语': 'ita',
    'es': 'spa', 'spa': 'spa', 'spanish': 'spa', '西班牙语': 'spa',
    'ru': 'rus', 'rus': 'rus', 'russian': 'rus', '俄语': 'rus',
}
MOOD_ALIASES = {
    'neutral': 'neutral', '中性': 'neutral',
    'warm': 'warm', '温暖': 'warm',
    'joyful': 'joyful', 'happy': 'joyful', '愉快': 'joyful', '欢快': 'joyful',
    'melancholic': 'melancholic', 'sad': 'melancholic', '忧伤': 'melancholic',
    'tense': 'tense', '紧张': 'tense',
    'introspective': 'introspective', '沉思': 'introspective',
    'calm': 'calm', '平静': 'calm',
    'energetic': 'energetic', '活跃': 'energetic',
}
# Preserve the richer MusicBee labels as distinct identifiers, not guessed coarse moods.
for _mood in ('Angry', 'Bewildered', 'Bouncy', 'Calm', 'Cheerful', 'Chill', 'Cold',
              'Comatose', 'Complacent', 'Crazy', 'Crushed', 'Cynical', 'Depressed',
              'Dreamy', 'Drunk', 'Eclectic', 'Envious', 'Groovy', 'Happy', 'Mellow',
              'Morose', 'Quirky', 'Rockin', 'Sad', 'Soothing', 'Spooky',
              'Sunday Brunch', 'Tranquil', 'Trippy', 'Upbeat', 'Wild', 'Work'):
    MOOD_ALIASES.setdefault(_mood.casefold(), _mood.casefold())
AROUSAL_MOODS = {'calm', 'energetic'}
SCORE_WEIGHTS = {'scene': .35, 'mood': .25, 'energy': .20, 'genre': .10, 'tempo': .10}


def token(value):
    return unicodedata.normalize('NFKC', value).casefold().strip()


def values(raw, aliases=None):
    """Only semicolons separate values; unknown or unrecognised enums stay unavailable."""
    result = set()
    for part in raw.split(';'):
        value = token(part)
        if value in UNKNOWN:
            continue
        if aliases is not None:
            value = aliases.get(value)
            if value is None:
                continue
        result.add(value)
    return result


def requested_values(items, aliases, field):
    result = set()
    if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
        raise ValueError(f'{field} must be a string list')
    for item in items:
        parts = item.split(';')
        if not parts or any(token(part) not in aliases for part in parts):
            raise ValueError(f'Unknown {field} identifier; use the documented vocabulary')
        result.update(aliases[token(part)] for part in parts)
    return result


def evidence_score(components):
    """Keep missing requested evidence in the denominator; coverage is not probability.

    Components map feature -> (match in [0,1], evidence availability in [0,1], source).
    Source tiers are explicit design weights, not calibrated accuracy estimates.
    """
    weight = sum(SCORE_WEIGHTS[name] for name in components)
    if not weight:
        return {'match_score': 0.0, 'evidence_coverage': 0.0, 'components': {}}
    match = sum(SCORE_WEIGHTS[name]*value[0]*value[1] for name,value in components.items())
    coverage = sum(SCORE_WEIGHTS[name]*value[1] for name,value in components.items())
    return {'match_score': round(match/weight, 6), 'evidence_coverage': round(coverage/weight, 6),
            'components': {name: {'match': value[0], 'availability': value[1], 'source': value[2]}
                           for name,value in components.items()}}
