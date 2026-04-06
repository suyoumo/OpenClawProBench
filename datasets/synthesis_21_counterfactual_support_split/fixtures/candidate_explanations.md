Hypotheses:
- hyp_a: an internal parser regression triggered the incident, and rollback stopped the growth.
- hyp_b: a vendor outage was already the primary trigger before internal errors began.
- hyp_c: rollback only coincided with recovery while an unrelated background condition self-resolved.

Notes:
- hyp_b fits the later vendor notice, but only if vendor degradation had already been active before the first internal spike.
- hyp_c can explain eventual recovery, but only if rollback timing is treated as irrelevant.
- Your task is to decide which hypothesis survives after applying temporal order and counterfactual exclusion.
