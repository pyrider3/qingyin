"""Bound combined Whisper hints by actual tokenizer tokens, not characters."""
def bounded(text, tokenizer, limit, tail=False):
    if not text:
        return ''
    tokens = tokenizer.encode(' '+text.strip()).ids
    if len(tokens) <= limit:
        return text
    result = tokenizer.decode(tokens[-limit:] if tail else tokens[:limit]).strip()
    # A cut may split UTF-8 bytes or change segmentation after decoding.
    while result and len(tokenizer.encode(' '+result).ids) > limit:
        result = result[1:] if tail else result[:-1]
    return result


def prepare(context, hotwords, tokenizer):
    # faster-whisper separately allows 223 previous tokens AND 223 hotword
    # tokens. Their sum plus control tokens can exceed Whisper's 448 slots.
    # Keep hotwords <= 80 even when rolling audio history reaches 223 tokens.
    return bounded(context, tokenizer, 96, tail=True), bounded(hotwords, tokenizer, 80)
