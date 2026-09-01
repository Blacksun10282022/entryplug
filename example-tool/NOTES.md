# Example equipment · Sunzi's Art of War · notes

This is the **synthetic** example content repo that ships with the entry plug: one piece of equipment
(`tools/sunzi/`), a fictional owner's Base (`self/`), a few refit requests, and the two free zones
(`work/`, `workshop/`). The machine's tests and acceptance script only ever run against this.

The corpus, the dictionary entries and the playbooks are in Chinese: they are data, and the machine is meant to
work in whatever language the content is written in. Everything that is the machine talking — the manual,
this file, the CLI — is in English.

## Sources and licence

- Corpus `tools/sunzi/corpus/raw/sunzi-01..13-*.md`: the thirteen chapters of Sunzi's Art of War, **public domain**.
  The text is the zh-hans variant of the Wikisource 《孫子兵法》 page, fetched through the MediaWiki API on
  2026-08-29, split by `== chapter ==` into thirteen files, with the page's appendix and variant notes removed.
  Wikisource marks that page as following the common received text (the 十一家注 / 武经七书 line). If your copy
  differs by a character or two, this repo's files win — anchor-sentence checking only knows this text.
- Everything else (the manual, playbooks, dictionary entries and their observation lines, records, materials,
  rules, proposals, the lecture sample) was written for this repo, **CC0 1.0** (see `LICENSE-CC0`). The owner,
  the company, the prices and the counterparties are all invented.
- The `^pNNNN` anchors and `(src: doc#seq "sentence")` in the dictionary all point at the corpus files above;
  `#seq` is the paragraph number (1-based) inside the plain-text section.

## Which file has which shape

- `tools/sunzi/corpus/raw/*.md`: corpus, header `Title / ID / Kind / Date / Source` + `==== 纯文本 ====`.
- `tools/sunzi/corpus/raw/talk-2026-08-01-shi.txt`: a lecture transcript sample (`Title / BVID / Date` + a plain
  text section + a timestamped section; only the plain text section is indexed).
- `tools/sunzi/corpus/clean/talk-2026-08-01-shi.md`: the cleaned version of the same talk (6-line header +
  `====` + `[m:ss]` paragraphs). When one doc id has a cleaned version, only that one is indexed.
- `self/records/`: the flight log (records); `proposals/pending/`: refit requests, each ending with the owner's
  two copy-paste lines.
- `work/`, `workshop/`: the free zones — not indexed, not protected.

## WARNINGs left in on purpose (they demonstrate the report; they are not mistakes)

- `tools/sunzi/materials/2026-07-10-market-price.md`: kind=price, 30-day shelf life, expired.
- `self/records/2026-07-20-supplier-delay.md`: more than 30 days without an outcome.
- `self/records/2026-08-27-choose-venue.md`: the owner has not answered (chosen is empty), counted as
  "unanswered" on the numbers page.

`plug check` here should report **0 ERROR**; each kind of ERROR is broken on purpose once, in a temporary copy,
by `tests/test_check.py`.
