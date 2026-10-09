# Private blind review of real research classification errors

This is a diagnostic instrument, not human-reviewed research evidence. No real cases or human labels have yet been collected by CI.

August 2026 public Hacker News data were previously used to screen gametes in PR #232. Recollecting the same public month is DEVELOPMENT diagnosis, not new independent validation. Search indices can change; earlier aggregate reports contain no raw source identifiers, so exact earlier cases cannot be restored.

## Local collection

Use a private, access-controlled absolute directory outside the repository. The tool performs zero network calls in default plan mode. Collection is explicit, read-only and limited to 16 free public HN Algolia queries:

    python experiments/research-human-review/review.py plan
    python experiments/research-human-review/review.py collect --private-dir /absolute/secure/oxibay-review-001

It creates a new restricted (0700) directory and 0600 files. Never put this directory on a public shared drive, in Git, or in GitHub Actions. The local-only blind_cases.jsonl contains public HN titles, excerpts, HN links, case IDs and topics, **but not machine decisions**. It draws up to five examples from each of six classifier stages, max 30 total, and avoids multiple excerpts from the same HN discussion. The machine-only prediction mapping is separately held in private_predictions.json. Never show that mapping to reviewers until after labels are sealed.

## Two independent reviews

Two humans independently read the public context and complete reviewer_1.csv and reviewer_2.csv with one of real_demand, no_demand or uncertain for every case. Purchase evidence and justification may be recorded locally. A real_demand label reflects a concrete problem/request, not a verified customer or willingness to pay. Reviewers must not see each other's labels or the machine stage during evaluation.

    python experiments/research-human-review/review.py aggregate --private-dir /absolute/secure/oxibay-review-001

Missing, uncertain or disputed cases block completed status. The private aggregate includes agreed potential false negatives and false positives, disagreements and stage summaries without identifiers, text, URLs or notes. With fewer than 12 cases it reports insufficient sample. Two files alone cannot prove actual reviewer independence, and balanced per-stage sampling cannot estimate population error rates. This tool never trains the student, changes the classifier or alters commercial thresholds.

Only **synthetic** tests and plan mode run on GitHub. There is no automatic collection or upload of real source content. If double-reviewed evidence identifies a classifier error, create a separate shadow-only fix, with a new preregistered independent future evaluation. Do not merge or deploy this diagnostic branch automatically.