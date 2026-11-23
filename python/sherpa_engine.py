"""Unified offline sherpa-onnx ASR worker (CPU only; never touches CUDA).

Supports modern 2025/2026 ONNX model families in a single low-memory process:
- x-asr / Zipformer Transducer (bilingual zh-en, built-in punctuation, BPE hotwords)
- FunASR-Nano (0.8B Encoder + Qwen LLM, built-in ITN/punctuation, dynamic hotwords & context)
- Qwen3-ASR (0.6B LLM-ASR, 52 languages/dialects, dynamic hotwords)
- SenseVoice (5-language fast NAR, built-in ITN/punctuation)
- FireRedASR2 (CTC and AED bilingual zh-en)
- Paraformer (legacy offline Mandarin)
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from audio_io import load_audio

_CJK_RE = re.compile(r'[\u4e00-\u9fff]')


def _pick(path: Path, *patterns: str):
    """Pick the first matching file in path (preferring int8 over fp32)."""
    for pattern in patterns:
        matches = sorted(path.glob(pattern))
        if matches:
            return matches[0]
    return None


def _read_engine_hint(path: Path) -> str:
    marker = path / 'engine.json'
    if marker.is_file():
        try:
            return str(json.loads(marker.read_text()).get('engine', '')).strip().lower()
        except (OSError, ValueError):
            pass
    return ''


def _tokens_info(tokens_path: Path):
    """Return (token_set, is_sentencepiece, has_cjk_punct, is_sense_voice)."""
    tokens = set()
    has_sp = False
    has_punct = False
    is_sv = False
    try:
        with tokens_path.open('r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                parts = line.split()
                if not parts:
                    continue
                tok = parts[0]
                tokens.add(tok)
                if tok.startswith('▁'):
                    has_sp = True
                if tok in ('▁，', '▁。', '▁？', '，', '。', '？'):
                    has_punct = True
                if tok in ('<|zh|>', '<|withitn|>', '<|SPECIAL_TOKEN_11|>'):
                    is_sv = True
    except OSError:
        pass
    return tokens, has_sp, has_punct, is_sv


def detect_model(path) -> dict | None:
    """Detect a sherpa-onnx offline model directory; return descriptor dict or None."""
    path = Path(path)
    if not path.is_dir():
        return None
    hint = _read_engine_hint(path)

    # 1. Qwen3-ASR: conv_frontend + encoder + decoder + tokenizer dir
    conv = _pick(path, 'conv_frontend*.onnx')
    enc = _pick(path, 'encoder*.int8.onnx', 'encoder*.onnx')
    dec = _pick(path, 'decoder*.int8.onnx', 'decoder*.onnx')
    tok_dir = path / 'tokenizer'
    if conv and enc and dec and tok_dir.is_dir():
        return {
            'kind': 'qwen3-asr',
            'conv_frontend': conv,
            'encoder': enc,
            'decoder': dec,
            'tokenizer': tok_dir,
            'native_punctuation': True,
            'supports_hotwords': True,
            'supports_context': False,
        }

    # 2. FunASR-Nano: encoder_adaptor + llm + embedding + tokenizer subdir
    enc_adp = _pick(path, 'encoder_adaptor*.int8.onnx', 'encoder_adaptor*.onnx')
    llm = _pick(path, 'llm*.int8.onnx', 'llm*.onnx')
    emb = _pick(path, 'embedding*.int8.onnx', 'embedding*.onnx')
    if enc_adp and llm and emb:
        tok_sub = next(
            (p for p in (path / 'Qwen3-0.6B', path / 'tokenizer') if p.is_dir()),
            next((p for p in sorted(path.iterdir()) if p.is_dir() and (p / 'tokenizer.json').is_file()), None),
        )
        if tok_sub is not None:
            return {
                'kind': 'funasr-nano',
                'encoder_adaptor': enc_adp,
                'llm': llm,
                'embedding': emb,
                'tokenizer': tok_sub,
                'native_punctuation': True,
                'supports_hotwords': True,
                'supports_context': True,
            }

    tokens_file = path / 'tokens.txt'
    if not tokens_file.is_file():
        return None

    # 3. Transducer (X-ASR / Zipformer): encoder + decoder + joiner + tokens.txt
    joiner = _pick(path, 'joiner*.int8.onnx', 'joiner*.onnx')
    if enc and dec and joiner:
        tokens, has_sp, has_punct, _ = _tokens_info(tokens_file)
        return {
            'kind': 'transducer',
            'encoder': enc,
            'decoder': dec,
            'joiner': joiner,
            'tokens': tokens_file,
            'token_set': tokens,
            'is_sentencepiece': has_sp,
            'native_punctuation': has_punct,
            'supports_hotwords': True,
            'supports_context': False,
        }

    # 4. FireRedASR2-AED: encoder + decoder + tokens.txt (no joiner)
    if enc and dec:
        return {
            'kind': 'fire-red-asr',
            'encoder': enc,
            'decoder': dec,
            'tokens': tokens_file,
            'native_punctuation': False,
            'supports_hotwords': False,
            'supports_context': False,
        }

    # 5. Single-file models: SenseVoice / FireRedASR2-CTC / Paraformer
    model = _pick(path, 'model.int8.onnx', 'model*.int8.onnx', 'model.onnx', 'model*.onnx')
    if not model:
        return None
    _, _, _, is_sv = _tokens_info(tokens_file)
    name_low = path.name.lower()
    if hint == 'sense-voice' or (not hint and (is_sv or 'sense-voice' in name_low or 'sensevoice' in name_low)):
        return {
            'kind': 'sense-voice',
            'model': model,
            'tokens': tokens_file,
            'native_punctuation': True,
            'supports_hotwords': False,
            'supports_context': False,
        }
    if hint in ('fire-red-asr-ctc', 'fire-red-asr2-ctc') or (not hint and ('fire-red' in name_low or 'firered' in name_low)):
        return {
            'kind': 'fire-red-asr-ctc',
            'model': model,
            'tokens': tokens_file,
            'native_punctuation': False,
            'supports_hotwords': False,
            'supports_context': False,
        }
    return {
        'kind': 'paraformer',
        'model': model,
        'tokens': tokens_file,
        'native_punctuation': False,
        'supports_hotwords': False,
        'supports_context': False,
    }


def is_model(path) -> bool:
    return detect_model(path) is not None


def _ensure_bpe_vocab(model_dir: Path, tokens_path: Path) -> str:
    """Create or reuse a 2-column BPE vocab file derived from tokens.txt."""
    target = model_dir / 'bpe.vocab'
    if target.is_file() and target.stat().st_size > 0:
        return str(target)
    lines = []
    for line in tokens_path.read_text(encoding='utf-8', errors='ignore').splitlines():
        parts = line.split()
        if len(parts) == 2 and not parts[0].startswith('<'):
            try:
                lines.append(f'{parts[0]}\t{-int(parts[1])}')
            except ValueError:
                pass
    content = '\n'.join(lines) + '\n'
    try:
        tmp = target.with_suffix('.vocab.tmp')
        tmp.write_text(content, encoding='utf-8')
        os.replace(tmp, target)
        return str(target)
    except OSError:
        fd, tmp_path = tempfile.mkstemp(prefix='qingyin-bpe-', suffix='.vocab')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(content)
        return tmp_path


def _split_phrases(*sources: str) -> list[str]:
    phrases = []
    seen = set()
    for src in sources:
        if not src:
            continue
        for item in re.split(r'[,，;\n]+', src):
            word = item.strip()
            if not word:
                continue
            key = word.casefold()
            if key not in seen:
                seen.add(key)
                phrases.append(word)
    return phrases


def _can_encode_sp(spaced: str, token_set: set[str]) -> bool:
    """Check whether every word in a spaced hotword can be covered by token_set."""
    if not spaced:
        return False
    for part in spaced.split():
        rem = '▁' + part
        pos = 0
        while pos < len(rem):
            matched = 0
            for end in range(len(rem), pos, -1):
                if rem[pos:end] in token_set:
                    matched = end - pos
                    break
            if not matched:
                return False
            pos += matched
    return True


def format_transducer_hotwords(phrases: list[str], token_set: set[str], is_sentencepiece: bool,
                               limit: int = 48, score: float = 2.0) -> str:
    """Format hotwords for sherpa-onnx Transducer modified_beam_search, skipping OOV entries."""
    lines = []
    for phrase in phrases:
        if is_sentencepiece:
            # Separate every CJK character so SentencePiece attaches ▁ to each character.
            spaced = ' '.join(re.sub(r'([\u4e00-\u9fff])', r' \1 ', phrase).split())
            if not _can_encode_sp(spaced, token_set):
                continue
            lines.append(f'{spaced} :{score:g}')
        else:
            if not all((ch in token_set) for ch in phrase if not ch.isspace()):
                continue
            lines.append(f'{phrase} :{score:g}')
        if len(lines) >= limit:
            break
    return '\n'.join(lines)


def _cpu_threads(kind: str) -> int:
    cores = os.cpu_count() or 4
    if kind in ('funasr-nano', 'qwen3-asr'):
        return min(6, max(2, cores // 2))
    # Hybrid Intel CPUs perform fastest with 3 threads on lightweight Zipformer/NAR graphs.
    return min(3, max(1, cores))


def build_recognizer(spec: dict, model_dir: Path):
    import sherpa_onnx

    kind = spec['kind']
    threads = _cpu_threads(kind)
    if kind == 'transducer':
        kwargs = dict(
            encoder=str(spec['encoder']),
            decoder=str(spec['decoder']),
            joiner=str(spec['joiner']),
            tokens=str(spec['tokens']),
            num_threads=threads,
            provider='cpu',
            decoding_method='modified_beam_search',
            max_active_paths=4,
            hotwords_score=1.5,
        )
        if spec['is_sentencepiece']:
            kwargs['modeling_unit'] = 'bpe'
            kwargs['bpe_vocab'] = _ensure_bpe_vocab(model_dir, spec['tokens'])
        else:
            kwargs['modeling_unit'] = 'cjkchar'
        return sherpa_onnx.OfflineRecognizer.from_transducer(**kwargs)
    if kind == 'funasr-nano':
        return sherpa_onnx.OfflineRecognizer.from_funasr_nano(
            encoder_adaptor=str(spec['encoder_adaptor']),
            llm=str(spec['llm']),
            embedding=str(spec['embedding']),
            tokenizer=str(spec['tokenizer']),
            num_threads=threads,
            provider='cpu',
            itn=True,
        )
    if kind == 'qwen3-asr':
        return sherpa_onnx.OfflineRecognizer.from_qwen3_asr(
            conv_frontend=str(spec['conv_frontend']),
            encoder=str(spec['encoder']),
            decoder=str(spec['decoder']),
            tokenizer=str(spec['tokenizer']),
            num_threads=threads,
            provider='cpu',
        )
    if kind == 'sense-voice':
        return sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(spec['model']),
            tokens=str(spec['tokens']),
            num_threads=threads,
            provider='cpu',
            use_itn=True,
            language='auto',
        )
    if kind == 'fire-red-asr-ctc':
        return sherpa_onnx.OfflineRecognizer.from_fire_red_asr_ctc(
            model=str(spec['model']),
            tokens=str(spec['tokens']),
            num_threads=threads,
            provider='cpu',
        )
    if kind == 'fire-red-asr':
        return sherpa_onnx.OfflineRecognizer.from_fire_red_asr(
            encoder=str(spec['encoder']),
            decoder=str(spec['decoder']),
            tokens=str(spec['tokens']),
            num_threads=threads,
            provider='cpu',
        )
    return sherpa_onnx.OfflineRecognizer.from_paraformer(
        paraformer=str(spec['model']),
        tokens=str(spec['tokens']),
        num_threads=threads,
        provider='cpu',
        decoding_method='greedy_search',
    )


def serve(model_dir, run=None):
    from normalize import clean_spacing, simplified, without_final_period
    from punctuation import restore
    import learning
    import rime_dictionary

    model_dir = Path(model_dir)
    spec = detect_model(model_dir)
    if spec is None:
        print(json.dumps({'error': '未识别的本地 ONNX 模型目录'}, ensure_ascii=False), flush=True)
        sys.exit(1)
    try:
        recognizer = build_recognizer(spec, model_dir)
    except Exception as exc:
        print(f'模型加载失败：{exc}', file=sys.stderr, flush=True)
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), flush=True)
        sys.exit(1)

    kind = spec['kind']
    print(json.dumps({'ready': True, 'device': 'cpu'}), flush=True)
    for line in sys.stdin:
        request = samples = vocabulary = context = dict_hints = phrases = stream = text = None
        try:
            request = json.loads(line)
            samples = load_audio(request['path'], run=run or subprocess.run)
            if len(samples) == 0:
                print(json.dumps({'text': ''}, ensure_ascii=False), flush=True)
                continue

            vocabulary = {'rules': []}
            if request.get('learning', True):
                try:
                    vocabulary = learning.load()
                except Exception as exc:
                    print(f'个人词库读取失败，保留原识别：{exc}', file=sys.stderr, flush=True)

            context = request.get('context', '')[-512:] if request.get('learning', True) else ''
            dict_hints = ''
            if spec['supports_hotwords'] and request.get('rime_dictionary', True):
                try:
                    dict_hints = rime_dictionary.hints(context)
                except Exception as exc:
                    print(f'雾凇词库读取失败，保留原识别：{exc}', file=sys.stderr, flush=True)

            phrases = _split_phrases(
                request.get('hotwords', ''),
                learning.hints(vocabulary) if request.get('learning', True) else '',
                dict_hints,
            )

            if kind == 'transducer':
                hw = format_transducer_hotwords(phrases, spec['token_set'], spec['is_sentencepiece'])
                stream = recognizer.create_stream(hotwords=hw) if hw else recognizer.create_stream()
            else:
                stream = recognizer.create_stream()
                if kind == 'funasr-nano':
                    if phrases:
                        stream.set_option('hotwords', ','.join(phrases[:48]))
                    stream.set_option('itn', '1')
                    lang = request.get('language', 'zh')
                    if lang == 'zh':
                        stream.set_option('language', '中文')
                    if context:
                        stream.set_option('user_prompt', f'前文：{context[-120:]}\n语音转写：')
                elif kind == 'qwen3-asr':
                    if phrases:
                        stream.set_option('hotwords', ','.join(phrases[:48]))

            stream.accept_waveform(16000, samples)
            recognizer.decode_stream(stream)
            text = clean_spacing(simplified(stream.result.text.strip()))
            text = learning.apply(text, vocabulary)

            if request.get('punctuation', True) and not spec['native_punctuation']:
                try:
                    text = restore(text)
                except Exception as exc:
                    print(f'补标点失败，保留原转写：{exc}', file=sys.stderr, flush=True)
            print(json.dumps({'text': without_final_period(text)}, ensure_ascii=False), flush=True)
        except Exception as exc:
            print(f'转写失败：{exc}', file=sys.stderr, flush=True)
            print(json.dumps({'error': str(exc)}, ensure_ascii=False), flush=True)
        finally:
            request = samples = vocabulary = context = dict_hints = phrases = stream = text = line = None
