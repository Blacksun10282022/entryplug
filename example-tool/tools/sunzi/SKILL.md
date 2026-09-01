---
name: sunzi
description: Use Sunzi's Art of War as an everyday tool — read the 形 and 势 in a negotiation, a competition or a conflict; who is moving whom, and what the other side's feigned weakness or delay actually is. Reach for it when the owner describes a situation, pastes a conversation, or asks what a term (势 / 虚实 / 奇正) means. Example equipment; everything in it is fictional or public domain.
---
Where: anywhere (default: back home, in the content repo)
Needs Base: yes
Product copies: none by default — products go to `work/sunzi/`

This is a list of obligations, not a procedure. Order, length and whether to use a playbook at all are your call;
either meet each obligation or say in your reply why you did not. On a long thread, reread this list every few turns.

## Listen first, look things up second
- Read the situation with your own eyes before you go near the playbook directory. Do not fit the situation to the list.
- Work from the tool, not from the corpus: read the dictionary and the playbooks first; open the corpus only when
  you are unsure, or when the owner wants the original wording.
- A pure "what does this term mean" question: Read the dictionary entry. If there is no entry, search the corpus
  (`scope=corpus`) and propose adding one.

## Obligation 1 · Know how the owner thinks first
- Before you judge, Read the lines of `self/RULES.md` that bear on this. You may disagree, but you must name the
  line and say why. Hard limits (ids starting with B) are not open to disagreement: point at the conflict and stop.

## Obligation 2 · Check the playbook directory and report honestly
- Read `playbooks/INDEX.md` and report: hit / partial / no playbook / counter-hit (it ran into a when_not).
  "No playbook" is a normal result. Two playbooks at most, by default.

## Obligation 3 · Make clear who said what
- Anything of the form "Sunzi says / the corpus says" needs an anchor: a `^pNNNN` from a dictionary observation
  line, or `(src: chapter-id#seq "original sentence")`. Say your own reading as your own, marked `[my reading]`;
  end it with one line `[what I did not look up]`.

## Obligation 4 · Judge before you show
- Before the owner sees anything, Write a record: tool · by · situation · verdict + the three sections
  依据 / 最强反证 / 什么会改判. A record holds a judgment, not a diary — you gave options and the owner chose
  one, so write it down on the spot.
- Grep the records for a similar situation and put it in 依据 (write "no similar record" when there is none).
- End the reply with the standing line: "what do you choose? (a sentence / A / B; skip it if you would rather not
  say)" — and do not restate which way the owner is leaning before you ask. Fill in `chosen` when he answers,
  `outcome` when he tells you how it went.

## Obligation 5 · Actions and boundaries
- Default to the playbook's actions; when its stance is warning or diagnostic, the actions point at the owner only.
- Anything that goes outward for him (a quote, an email, a message) needs asking first — that is the sortie lock.

## Obligation 6 · Check backwards, propose only on a hit
- Before you finish, ask: was there anything here that neither the dictionary nor the playbooks cover? Should the
  owner's own phrasing become an alias? On a hit, Write a refit request under `proposals/pending/` (target · base ·
  from + 改成什么 / 为什么 / 最强反证) and end it with the owner's two copy-paste lines. Proposals do not appear in
  your reply.

## Corpus · materials · shelf life
- The corpus is the thirteen chapters under `corpus/raw/` (once something is learned into the dictionary, stop
  going back). Materials live in `materials/`: price 30 days, profile 90 days; when you use one, say which month it is from.
- Products (a written brief, a comparison table, a draft) go to `work/sunzi/`, not into the equipment.
- Run `plug check` before you hand anything over — it runs this equipment's own `checks/` (every chapter a record
  names has to exist).

## Learning (only when the owner asks)
- If he says "learn this chapter": read it and produce only proposals (observation lines / aliases / playbooks)
  into `proposals/pending/`. Do not touch the dictionary directly.
