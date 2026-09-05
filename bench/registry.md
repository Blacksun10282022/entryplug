# registry · the private benchmark register (hashes only, never the cases)

Before every run of the private, real benchmark, add a line here and commit it; results may only cite that line.
Precedent: ARC Prize publishes a public leaderboard from a private evaluation set.

| registered | case file sha256 | cases | protocol version | model · harness | note |
|---|---|---|---|---|---|
| 2026-09-05 | f63b5f0a772d3a086cf441bf5eeaadeee33c65835df1a80e8d04dffdfbecc8ac | 6 | 1 (docs/BENCH.md) | fable 5.1 max · Opus 5 max · gpt-5.6 max · gpt-6-astra xhigh; Claude Code 2.1.259 · codex-cli 0.153.4 | equipment A (a reading manual); situations: three about others, three about the owner |
| 2026-09-05 | 7f26d537c63f32a735fa107a4b756731ad1e5a83ddab23ed9917ac4f953f0cdf | 6 | 1 (docs/BENCH.md) | same four pilots and harnesses | equipment B (a screening manual); six synthetic job ads, one hard gate each |

## Result register (self-reported vs measured, split by equipment, never a total)

Interval = Wilson 95% on the proportion of the six situations where the blind judge picked the equipped answer (ties not counted as wins). By the rule above, "better than the bare model" may be written only where the lower bound clears 0.50: that is every 6/6 row (0.61) and no other row.

| date | register line | equipment | n | blind pick went the system's way | sounds like me 1–5 | same answer 3 times | gold-set recall@10 | cost multiple | one sentence, self-reported |
|---|---|---|---|---|---|---|---|---|---|
| 2026-09-05 | A line | A · pilot fable 5.1 · judge fable 5.1 | 6 | 6/6 = 1.00 [0.61, 1.00] | - | - | - | 12x $ | 6/6 on the sum |
| 2026-09-05 | A line | A · pilot Opus 5 · judge fable 5.1 | 6 | 6/6 = 1.00 [0.61, 1.00] | - | - | - | 17x $ | 6/6 on the sum; the strongest bare model, so the smallest gain |
| 2026-09-05 | A line | A · pilot gpt-5.6 · judge fable 5.1 | 6 | 6/6 = 1.00 [0.61, 1.00] | - | - | - | 9x tokens | 6/6 on the sum |
| 2026-09-05 | A line | A · pilot gpt-6-astra · judge fable 5.1 | 6 | 6/6 = 1.00 [0.61, 1.00] | - | - | - | 7.5x tokens | 6/6 on the sum; the shortest answers |
| 2026-09-05 | A line | A · pilot fable 5.1 · judge gpt-6-astra (reads the materials) | 6 | 1/6 = 0.17 [0.03, 0.56] | - | - | - | 12x $ | 1W 1T 4L on the sum: this judge docks true facts used to strengthen a motive reading |
| 2026-09-05 | A line | A · pilot gpt-6-astra · judge gpt-6-astra (reads the materials) | 6 | 2/6 = 0.33 [0.10, 0.70] | - | - | - | 7.5x tokens | 2W 2T 2L: near-even under the strict judge |
| 2026-09-05 | B line | B · pilot fable 5.1 · judge fable 5.1 | 6 | 6/6 = 1.00 [0.61, 1.00] | - | - | - | 6.2x $ | 6/6 on the sum |
| 2026-09-05 | B line | B · pilot gpt-6-astra · judge fable 5.1 | 6 | 6/6 = 1.00 [0.61, 1.00] | - | - | - | 5.1x tokens | 6/6 on the sum |
| 2026-09-05 | B line | B · pilot Opus 5 · judge gpt-5.6 | 6 | 6/6 = 1.00 [0.61, 1.00] | - | - | - | 3x $ | 6/6 on the sum; under judge fable 1W 1T 4L (it docks file names in the body, which the owner keeps on purpose) |
| 2026-09-05 | B line | B · pilot gpt-5.6 · judge gpt-5.6 | 6 | 3/6 = 0.50 [0.19, 0.81] | - | - | - | 5.4x tokens | 3W 1T 2L: passes only as a tie; under judge gpt-6-astra (reads the materials) 6/6 |
| 2026-09-05 | B line | B · pilot fable 5.1 · judge gpt-6-astra (reads the materials) | 6 | 4/6 = 0.67 [0.30, 0.90] | - | - | - | 6.2x $ | 4W 0T 2L |
| 2026-09-05 | B line | B · pilot gpt-6-astra · judge gpt-6-astra (reads the materials) | 6 | 3/6 = 0.50 [0.19, 0.81] | - | - | - | 5.1x tokens | 3W 2T 1L |
| 2026-09-05 | B line | B · pilot gpt-5.6 · judge gpt-6-astra (reads the materials) | 6 | 6/6 = 1.00 [0.61, 1.00] | - | - | - | 5.4x tokens | 6/6 under the judge that read the owner's materials; 3W 1T 2L under judge gpt-5.6 and 2W 2T 2L under judge fable 5.1 |
| 2026-09-05 | B line | B · pilot Opus 5 · judge gpt-6-astra (reads the materials) | 6 | 5/6 = 0.83 [0.44, 0.97] | - | - | - | 3x $ | 5W 0T 1L under the judge that read the owner's materials |

## Drift table (a line per model change or rerun; a drop gets registered too)

| date | model · harness | register line | change |
|---|---|---|---|
| 2026-09-05 | gpt-6-astra xhigh · codex-cli 0.153.4 | A line, B line | fourth pilot added; the model needs codex-cli 0.153.4 or newer |
| 2026-09-05 | gpt-6-astra as judge, reading the owner's materials | A line, B line | a judge that cannot open the cited materials docks true facts as unverifiable; every judge row above says whether it read them |
