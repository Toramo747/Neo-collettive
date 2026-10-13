"""Observation only: join provider receipts to ingestion outcomes.

Query slots are cycle-local ordinals, never hashes of private query text.
Provider/reason codes are fixed enums. Public leaves are numbers only.
"""
from collections import Counter
from evidence_integrity import canonical_url
from ingestion_diagnostics import canonical_source

PROVIDERS = ('unknown', 'bing-rss', 'brave', 'google-pse', 'hn', 'github',
             'stackexchange', 'remotive-api', 'remoteok-api', 'persisted-price-validation')
REASONS = ('unknown', 'missing_url', 'routing_duplicate', 'query_irrelevant',
           'relevance_error', 'routing_limit', 'self_contamination_rejected',
           'noise_domain', 'github_noise', 'github_no_buyer_problem_context',
           'no_family', 'weak_family_relevance', 'context_too_short', 'no_demand_signal', 'unjoined')


class DroughtFunnel:
    def __init__(self, memory):
        self.urls = {canonical_url(str(x.get('url') or '')) for x in memory if isinstance(x, dict)} - {''}
        self.fingerprints = {str(x.get('fingerprint') or '') for x in memory if isinstance(x, dict)} - {''}
        self.receipts = []
        self.outcomes = {}
        self.new_urls = set()
        self.queries = {}
        self.by_key = {}

    def key(self, query, url, source):
        query = ' '.join(str(query or '').lower().split())
        slot = self.queries.setdefault(query, len(self.queries) + 1)
        return slot, canonical_url(str(url or '')), canonical_source(source)

    def add(self, query, row, relevant, reason=''):
        slot, url, source = self.key(query, row.get('url'), row.get('source') or 'unknown')
        fp = str(row.get('fingerprint') or '')
        receipt = {'query_slot': slot, 'provider_code':
                             PROVIDERS.index(source) if source in PROVIDERS else 0,
                             'source': source, 'url': url, 'fingerprint': fp, 'relevance_pass': int(bool(relevant)),
                             'reason': reason, 'duplicate_memory': int(bool(
                                 (url and url in self.urls) or (fp and fp in self.fingerprints)))}
        self.receipts.append(receipt)
        self.by_key.setdefault((slot, url, source), []).append(receipt)

    def provider(self, source):
        source = canonical_source(source)
        return PROVIDERS.index(source) if source in PROVIDERS else 0

    def has_receipt(self, query, url, source="unknown"):
        return self.key(query, url, source) in self.by_key

    def relevant(self, query, url, source="unknown"):
        for receipt in self.by_key.get(self.key(query, url, source), []):
            if not receipt['reason']:
                receipt['relevance_pass'] = 1

    def outcome(self, query, url, reason='', source='unknown'):
        self.outcomes[self.key(query, url, source)] = reason

    def new_signal(self, url, query, source="unknown"):
        self.new_urls.add(self.key(query, url, source))

    def snapshot(self):
        groups = {}
        private = []
        for receipt in self.receipts:
            row = dict(receipt)
            reason = row['reason']
            if not reason:
                reason = self.outcomes.get((row['query_slot'], row['url'], row['source']), 'unjoined')
            useful = int(not reason)
            row['reason'] = reason or 'useful'
            private.append(row)
            key = (row['query_slot'], row['provider_code'])
            counts = groups.setdefault(key, Counter())
            counts.update(raw_results=1, relevance_pass=row['relevance_pass'], useful=useful,
                          new_signal_row=int(bool(useful and (row['query_slot'], row['url'], row['source']) in self.new_urls)),
                          duplicate_memory=row['duplicate_memory'],
                          new_rejected=int(bool(reason and not row['duplicate_memory'])))
            if reason:
                code = REASONS.index(reason) if reason in REASONS else 0
                counts['reason_' + str(code)] += 1
        public = []
        for (slot, provider), counts in sorted(groups.items()):
            public.append({'query_slot': slot, 'provider_code': provider,
                           **{k: counts[k] for k in ('raw_results', 'relevance_pass', 'useful',
                               'new_signal_row', 'duplicate_memory', 'new_rejected')},
                           'rejections': [{'reason_code': int(k[7:]), 'count': n}
                                          for k, n in sorted(counts.items()) if k.startswith('reason_')]})
        unjoined = sum(row['reason'] == 'unjoined' for row in private)
        return {'schema_v': 1, 'rows': public, 'unjoined_total': unjoined,
                'measurement_reliable': unjoined == 0, 'private_results': private,
                'private_queries': [{'query_slot': slot, 'query': query}
                                    for query, slot in self.queries.items()]}


def public_drought(value):
    """Explicit allowlist; reject arbitrary labels, URLs and text even as keys."""
    value = value if isinstance(value, dict) else {}
    def number(x):
        return max(0, int(x)) if isinstance(x, (int, float)) and not isinstance(x, bool) else 0
    rows = []
    for row in value.get('rows', []) if isinstance(value.get('rows'), list) else []:
        if not isinstance(row, dict):
            continue
        clean = {k: number(row.get(k)) for k in ('query_slot', 'provider_code', 'raw_results',
                 'relevance_pass', 'useful', 'new_signal_row', 'duplicate_memory', 'new_rejected')}
        clean['rejections'] = [{'reason_code': number(x.get('reason_code')), 'count': number(x.get('count'))}
                               for x in row.get('rejections', []) if isinstance(x, dict)]
        rows.append(clean)
    unjoined = number(value.get('unjoined_total'))
    return {'schema_v': 1, 'rows': rows, 'unjoined_total': unjoined,
            'measurement_reliable': unjoined == 0}
