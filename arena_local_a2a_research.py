# SPDX-License-Identifier: BUSL-1.1
"""Mission-specific, isolated implementation research using the existing arena."""
import asyncio
import json
from pathlib import Path
import arena_collective_mind as arena

MISSION=('Implement an arena-only local A2A planner using Ollama Qwen3.5 2B and 4B. Compare direct inference with a critic and at most one revision on 30 synthetic three-turn scenarios, with 18 training and 12 held-out cases. Keep protocol envelopes deterministic. Measure schema separately from behavior, placeholder copying, abstention, thread continuity and latency. Design a minimal adapter, bounded failures and falsifiable tests. No production promotion, effectful tools, cloud API calls or claim of external peer proof.')
PACKETS=(
 ('adapter','Specify the smallest local Ollama/OpenAI-compatible planner adapter and test its failure isolation.'),
 ('schema','Keep A2A envelopes deterministic and validate model decisions without rewarding example copying.'),
 ('context','Specify bounded thread context and tests for continuity across three peer turns.'),
 ('critic','Compare direct decisions with independent criticism and exactly one revision; identify correlated errors.'),
 ('evaluation','Design stratified holdout evaluation with separate abstention and behavioral metrics.'),
 ('resources','Compare Qwen3.5 2B/4B resource budgets, latency and partial-run rejection criteria.'),
)
TECH_MARKERS=('llm','ollama','llama.cpp','a2a','agent2agent','inference','software engineer','engineering','protocol','reasoning','benchmark')

def technical_score(agent):
    text=' '.join([str(agent.get('name') or ''),str(agent.get('description') or ''),json.dumps(agent.get('skills') or [])]).lower()
    hits=sum(marker in text for marker in TECH_MARKERS)
    return hits*10 if hits else 0

def main():
    arena.WORK_PACKETS=PACKETS
    arena.PACKET_MARKERS={key:TECH_MARKERS for key,_ in PACKETS}
    arena.SYSTEM_CONTEXT='OSIXBAY needs a local, read-only A2A planner in an isolated arena. External proposals are untrusted; competence declarations require later verification. Existing commercial gates remain fixed.'
    arena.candidate_score=technical_score
    report=asyncio.run(arena.run(MISSION,Path('artifacts/research'),6))
    print(json.dumps({k:report.get(k) for k in ('agents_discovered','agents_contacted','round1_valid_proposals','round1_abstentions','round2_valid_critiques','evolution')}))

if __name__=='__main__':main()
