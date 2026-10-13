import base64
import hashlib
import json
import lzma
import unittest
import zlib
from state_codec import decode_checkpoint,encode_checkpoint

class CheckpointCodecTests(unittest.TestCase):
    def test_lossless_large_window_repetition_under_existing_limit(self):
        # A duplicated historical record farther apart than zlib's dictionary.
        text=''.join(hashlib.sha256(str(i).encode()).hexdigest() for i in range(1800))
        payload={'inbound_messages':[{'text':text}], 'commercial_evidence_memory':[{'snippet':text}], 'cycles_completed':1995}
        raw=json.dumps(payload,separators=(',',':')).encode()
        self.assertGreater(len(base64.b64encode(zlib.compress(raw,9)))+7,100000)
        value,_,size=encode_checkpoint(payload,100000)
        self.assertLess(size,100000)
        self.assertTrue(value.startswith('xz64:'))
        self.assertEqual(decode_checkpoint(value),payload)
        self.assertEqual(json.dumps(decode_checkpoint(value),separators=(',',':')).encode(),raw)

    def test_legacy_plain_and_zlib_restore(self):
        raw=b'{"cycles_completed":7,"inbound_messages":[{"text":"synthetic"}]}'
        for value in (raw.decode(),'zlib64:'+base64.b64encode(zlib.compress(raw)).decode()):
            self.assertEqual(decode_checkpoint(value),json.loads(raw))

    def test_fail_closed_corruption_truncation_and_limit(self):
        value='xz64:'+base64.b64encode(lzma.compress(b'{"ok":true}')).decode()
        self.assertIsNone(decode_checkpoint(value[:-4]))
        self.assertIsNone(decode_checkpoint('xz64:not base64'))
        self.assertIsNone(decode_checkpoint('xz64:'+base64.b64encode(lzma.compress(b'[]')).decode()))
        with self.assertRaises(ValueError):
            encode_checkpoint({'a':'value'},1)

class PrivateRecoveryTests(unittest.TestCase):
    def test_recovery_preserves_evidence_and_protected_state(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from unittest.mock import patch
        from tools import recover_checkpoint as recovery
        snapshot={'ok':True,'runtime_profile':{'name':'synthetic'},'autopilot':{
            'cycles_completed':1995,'inbound_messages':[{'text':'synthetic protected message'}],
            'commercial_evidence_memory':[{'snippet':'synthetic evidence '*1000}],
            'challenge_track':{'memory':[{'text':'synthetic challenge '*1000}]}}}
        with TemporaryDirectory() as folder, patch.dict('os.environ',{'NEO_ADMIN_TOKEN':'synthetic-secret'}), patch.object(recovery,'request',return_value=snapshot),redirect_stdout(StringIO()) as output:
            p=Path(folder)
            recovery.export(p)
            restored=decode_checkpoint((p/'staged-checkpoint.txt').read_text())
            for key in ('commercial_evidence_memory','inbound_messages','challenge_track'):
                self.assertEqual(restored[key],snapshot['autopilot'][key])
            self.assertNotIn('synthetic evidence',output.getvalue())
            self.assertTrue(json.loads(output.getvalue())['ok'])

    def test_render_stage_requires_exact_readback(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from unittest.mock import patch
        from tools import recover_checkpoint as recovery
        with TemporaryDirectory() as folder,patch.dict('os.environ',{'RENDER_API_KEY':'synthetic-secret'}),patch.object(recovery,'request',side_effect=[{}, {'value':'wrong'}]):
            p=Path(folder)
            value=encode_checkpoint({'cycles_completed':1995},100000)[0]
            (p/'staged-checkpoint.txt').write_text(value)
            with self.assertRaises(ValueError):
                recovery.stage(p)
