# SPDX-License-Identifier: BUSL-1.1
"""Bounded, lossless checkpoint codecs; legacy zlib64 remains readable."""
import base64
import json
import lzma
import zlib
from runtime_observation import OBSERVATION

MAX_RAW_BYTES = 32 * 1024 * 1024

def encode_checkpoint(payload: dict, max_bytes: int) -> tuple[str, int, int]:
    with OBSERVATION.phase('checkpoint_json'):
        raw=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    if len(raw)>MAX_RAW_BYTES:
        raise ValueError('checkpoint raw size exceeds safe limit')
    with OBSERVATION.phase('checkpoint_zlib'):
        value='zlib64:'+base64.b64encode(zlib.compress(raw,9)).decode('ascii')
    # XZ's larger dictionary preserves repeated history that zlib's 32 KiB
    # window cannot reuse. No records, strings, labels or counters are removed.
    if len(value)>min(60000,max_bytes):
        with OBSERVATION.phase('checkpoint_lzma'):
            alternate='xz64:'+base64.b64encode(lzma.compress(raw,preset=3)).decode('ascii')
        if len(alternate)<len(value):
            value=alternate
    size=len(value)
    if size>max_bytes:
        raise ValueError(f'compressed state exceeds safe env limit: {size}>{max_bytes}')
    return value,len(raw),size

@OBSERVATION.timed('checkpoint_decode')
def decode_checkpoint(value: str) -> dict | None:
    try:
        value=(value or '').strip()
        if len(value)>MAX_RAW_BYTES:
            return None
        if value.startswith(('zlib64:','xz64:')):
            prefix,encoded=value.split(':',1)
            packed=base64.b64decode(encoded,validate=True)
            if prefix=='xz64':
                decoder=lzma.LZMADecompressor(memlimit=64*1024*1024)
                raw=decoder.decompress(packed,max_length=MAX_RAW_BYTES+1)
                if not decoder.eof or decoder.unused_data:
                    return None
            else:
                decoder=zlib.decompressobj()
                raw=decoder.decompress(packed,MAX_RAW_BYTES+1)
                if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                    return None
            if len(raw)>MAX_RAW_BYTES:
                return None
            value=raw.decode('utf-8')
        payload=json.loads(value)
        return payload if isinstance(payload,dict) else None
    except (ValueError,TypeError,UnicodeError,lzma.LZMAError,zlib.error):
        return None
