# Provenance receipts

Since 23/10, a reply that neo posts **exactly as its fact-card mind drafted it** gets a receipt here,
`post_<id>.json`: the posted text and its sha256, each sentence with the fact cards it cites (or the fixed
phrase it is), each card with its public source (a bullet of `docs/common-voice.md`, a sentence of one of our
posted replies, or a tool run with its inputs, outcome and code version), and the checks the draft passed.
Only public material; the daily receipt-log anchor fixes the repository commit, so it fixes these files too.

Strict check (exit 1 on any failure; `--live` re-runs the tool and requires the same outcome):

```
python tools/provenance.py verify docs/provenance/<file>.json --live
```

It checks the hash, that the text equals the posted reply, that the sentences rebuild the text exactly, that
every cited card exists and every sentence passes the same code check as when it was drafted, that every card's
source resolves word for word (or the tool's code is named by its git blob id and re-runs to the same outcome),
and that the file holds only whitelisted fields and nothing private. A receipt shows where each sentence came
from; it does not show that a source is right.
