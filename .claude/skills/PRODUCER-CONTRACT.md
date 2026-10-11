# Producer contract — eleven cross-cutting behaviors (binding for all producer skills)

> The five producer skills (`nmt-market-research`, `nmt-craft-value-proposition`, `nmt-product-requirements`,
> `nmt-craft-go-to-market`, `nmt-analyze-interviews`) share eleven behaviors that came directly from user
> testing feedback. Specifying them once here keeps the five skills in sync. Each skill points to this file and wires the
> concrete hooks (intake questions, template blocks) into its own flow. The companion file
> `READABILITY-CONTRACT.md` governs the 3-layer output; this file governs intake + framing + integrity.

The eleven behaviors:

1. **Helicopter-view first** — orient the user before the first question.
2. **Output format choice** — Markdown (fast) or HTML (easier to read).
3. **Critical treatment of all user input** — everything the user provides is a hypothesis; surface the risks inside it in a dedicated block.
4. **Visible validation debt** — print how many unvalidated assumptions the artifact stands on; `GO` → `GO (to validation)`.
5. **Configurable output path** — default `Skills-Results/…`, but accept the host repo's convention.
6. **Deep-mode QA loop + web-MCP fallback** — Deep mode must meet an evidence floor and self-check; recommend a web MCP when the built-in fetch is blocked.
7. **Market and language intake** — ask which market and which audience language, and build everything from that answer.
8. **Repo context by permission** — list the context files found on disk and read them only after a yes.
9. **Every claim carries its status** — quoted, derived, or the model's hypothesis; a spoken number is an opinion.
10. **Frequency counts on aggregated claims** — how many sources said it, and which; a single source can't carry a segment.
11. **Confidence scaled to the input** — thin input gets ranges, a visible warning, and the top-3 inputs that would fix it.

---

## 1. Helicopter-view first (before the first intake question)

The very first thing the skill prints — before STAGE 0 / the first `AskUserQuestion` — is a short orientation block, in plain language, in the user's chosen document language. From user testing — *"I always ask Claude to first explain schematically what we'll do, then go deep. The skill jumps straight to 'describe your idea.'"*

Keep it to ~8–12 lines:

- **What you'll get** — the one deliverable, in one line.
- **The steps** — 3–6 numbered phases, one line each.
- **Where AI works vs. where you decide / validate** — name explicitly that AI does the analysis; the user picks direction and runs the field validation (interviews, sales, tests). AI cannot validate for them.
- **The two modes** — *Quick (default): no internet, ~3–5 min, reasoning only — good for a first cut, hypotheses, "did I miss something."* · *Deep (opt-in): subagents + web research, longer — real competitor/market/review data.* (From user testing: people didn't know Quick vs Deep existed, or what Quick is for.)
- **Rough cost** — a ballpark of time and token usage so the user can choose a model (Quick: light; Deep: heavy — best on a top model with a web MCP).
- **One honest caveat** — *"This speeds up the thinking, not the proving. The numbers and segments are hypotheses until you check them in the field."*

End with: *"Ready? First, a few questions."* → proceed to intake. Don't make the user read a wall — this is a map, not a manual.

## 2. Output format choice — Markdown or HTML

Ask once, in the intake batch (alongside mode). From user testing — *"reading walls of markdown is painful; give me HTML I can open in a browser."*

> **Output format** — **Markdown** (default; faster to generate; opens anywhere) · **HTML** (a bit slower to generate; easier to read — collapsible sections and working in-page navigation).

**Both formats keep every link clickable** — source links (Rule 2) and the Layer-1→2→3 drill-down `▸` links. That's the answer to *"what about the links?"*: HTML doesn't lose them, it makes them nicer (real in-page anchors + sources opening in a new tab).

If the user picks **HTML**, the single output file (Rule 4 — still exactly one file per run) is a **self-contained `.html`** with the **same** content as the Markdown version — identical attribution, disclaimers, the three layers, every table, every link — rendered as:

- **Inline CSS only, no external dependencies** (opens offline, no network, no build step). A clean reading width (~720px), system font stack, comfortable line-height.
- **Working navigation** — the "How to read this" jump links and every `▸` drill-down link are real in-page `href="#id"` anchors to matching `id="…"` targets. A small sticky top bar with *Level 1 · Level 2 · Level 3* jumps.
- **Collapsible depth** — Layer 3 sections and every `▸ methodology trace` are `<details>` elements (Level 1–2 open by default; Level 3 collapsed) so the reader expands only what they want. This also answers a separate complaint about non-collapsible long content.
- **Source links** open in a new tab (`target="_blank" rel="noopener"`).
- Filename: same pattern as the Markdown file, with the `.html` extension. Do **not** also write the `.md` — one file per run.

Build the HTML by rendering the finished content you would have written as Markdown — same layers, same anchors. Don't water it down for HTML; it is the same report in a more readable shell.

## 3. Critical treatment of all user input (everything is a hypothesis)

From user testing: on a project that came in with a deck + landing + codebase, the skill *took the descriptions as truth, baked them into the wedge, and never proposed checking them* — substituting the team's imagined Job for the customer's real one. The canon forbids skipping field validation (Phase II).

**Rule: treat every input the user provides — free-text claims, uploaded decks, landing pages, codebases, past research, "everyone wants X" — as a hypothesis, never as established fact.** This extends the existing user-claims ledger to *all* materials, not just spoken claims.

Two concrete obligations:

**(a) Actively hunt for risks inside the provided material.** Don't just record claims — interrogate them. For each load-bearing input, ask:
- Is this a customer-validated fact, or the team's belief about the customer? (A landing page is the team's hypothesis about value, not proof customers want it.)
- Does the stated Job / segment look like the customer's real Job, or the team's projection? (The most expensive error — seen in real runs.)
- Are there internal contradictions, or numbers presented as data that are actually guesses?
- What would have to be true for this to hold — and is that checked?

**(b) Emit a dedicated, visible block in the output** — *"What you gave me — and the risks I see in it."* This is Ivan's explicit ask: *"when you gave me this information, I see these risks in it,"* marked separately. Place it in **Layer 2** (where trust is built), as its own subsection, and surface the single worst one in **Layer 1** as (or alongside) the make-or-break risk. Format:

```markdown
## What you told me — and the risks I see in it
*Everything below is taken as a hypothesis, not as fact. These are the inputs the analysis leans on, and what I'd check before trusting each.*

| What you provided / claimed | How I treated it | The risk I see in it | How to check it fast |
|---|---|---|---|
| {claim / material, tagged data / observation / hunch} | {used as hypothesis in {where}} | {the specific risk — e.g., "this is your team's stated value, not customer-validated; the real Job may differ"} | {the cheapest falsifying test} |
```

**Hard gate:** no verdict, target-segment pick, wedge, value proposition, or PRD scope may rest *primarily* on an unvalidated user input without the output saying so explicitly and pointing a RAT row at it. If the wedge is built on a Job taken from the user's materials and not confirmed by customer evidence, that is named as the single most expensive risk.

## 4. Visible validation debt + "GO (to validation)"

From user testing — *"A PRD built in 20 minutes on guesses looks as convincing as one after 8 interviews. Print the debt."* And: *"`GO` reads to a founder as 'build it — 3 months'; by your own algorithm GO means 'go validate' — 8 interviews and a fake door."*

Two changes:

**(a) Validation-debt line in Layer 1** — one line, near the top of the answer:

> **Validation debt:** this stands on **{N}** unvalidated assumptions — **{M}** of them fatal (would sink it if wrong). The fatal ones are the first things to check. [see them ▸](#l2-risks)

N = count of risky assumptions in the RAT / risk table. M = those tagged "kills it if wrong." Count honestly; a Quick run on thin input has high debt — say so. This makes a fast artifact legibly fast, not falsely authoritative.

**(b) Verdict wording** — wherever a skill emits a `GO` verdict, write **`GO (to validation)`**, never bare `GO`. Keep `NARROW` and `PIVOT` as-is (they already read as "not yet building"). In Layer 1 add a half-line gloss the first time: *"GO (to validation) — the idea is worth the next step, which is checking it in the field, not building it yet."*

**(c) Hand-off carries the debt.** When a skill hands off to the next in the chain (`/nmt-market-research` → `/nmt-craft-value-proposition` → `/nmt-product-requirements` → `/nmt-craft-go-to-market`), the next skill **opens by asking what from the prior artifact's validation debt has since been checked**, and re-tags anything still unvalidated. Debt travels down the chain; it is not silently dropped.

## 5. Configurable output path

From user testing: hard-coding `Skills-Results/{slug}/…` in the repo root breaks teams whose agent-ready repos keep research elsewhere (e.g., `*/docs/research`).

Add to intake (one line, default is the current behavior — no friction for the common case):

> **Where to save the result** — default `Skills-Results/{project}/{skill}/…` · or give a folder / path convention to match your repo (e.g., `docs/research/`).

If the user gives a path, write the single result file there, keeping the same `{YYYY-MM-DD_HH-MM}_{product-slug}-{skill}-result.{md|html}` filename. If they skip, use the default. Never write more than one file regardless of location (Rule 4).

## 6. Deep-mode QA loop + web-MCP fallback

From user testing: *"`/nmt-craft-value-proposition` promised deep research, made two queries, and quit."* And: *"G2 is blocked from Claude Code — use a firecrawl/exa MCP."* Also: Deep results sometimes had methodology errors and undersized SAM.

**(a) Evidence floor (not just a ceiling).** Each Deep-mode research leg has web *caps* (max fetches). Treat the **lower bound as a floor**: a leg may not return "done" until it has either hit a real minimum of distinct sources for its task or explicitly reported *why* fewer were possible (blocked, none exist). "Did two queries and stopped" is a failure state, not a completion.

**(b) Self-critic loop on each leg.** After a research leg returns, run a short critic pass (Quick: inline self-critique; Deep: a critic check) asking: *enough distinct sources? load-bearing claims actually verified against a source? any methodology error (segment by demographics, Big-Job-as-segment, features-before-criteria, undersized market)? gaps left?* If it fails, re-run the leg with the gap named — up to 2 extra rounds. Don't ship a leg that failed its own critic.

**(c) Web-MCP fallback.** When the built-in fetch is blocked or thin on a needed source (G2, Capterra, local-market sites), tell the user once and use a web-research MCP if available:

> Some sources (e.g., G2, Capterra) block the built-in fetch. For fuller Deep research, enable a web-research MCP — [Firecrawl](https://www.firecrawl.dev/) or [Exa](https://exa.ai/) (both ship MCP servers) — and I'll use it. Without it, I'll note where coverage was thin.

If such an MCP is connected (discoverable via tool search), prefer it for blocked sources; otherwise proceed and flag thin coverage in the verification checklist.

## 7. Market and language intake (a mandatory intake question)

From user testing: a run for a Central Asian market came back with US acquisition channels, US price anchors, and US competitor names — an artifact the user could not act on.

**Ask in the intake batch, always, before any analysis:**

> **Market & language** — which country or region are your customers in, and what language do they speak? (e.g. *Kazakhstan, Russian-speaking* · *Germany, German* · *US, English*)

Everything downstream comes from that answer: examples, named competitors, acquisition channels, price anchors, regulation, units and currency, and the tone of any copy. **Never fall back to a US or Russian default because it is the best-covered market in the training data.** Central Asia is not Russia, the UK is not the US, and a wrong market makes every channel and every price in the artifact useless.

Keep the **audience language** separate from the **document language** — the user may want the report in English about a Russian-speaking audience. Ask for both when they differ.

If the question goes unanswered (non-interactive run), name the market you are assuming in one line at the top of the output, and tag every market-specific number as unverified for their market.

## 8. Repo context — list first, read only after a yes

At intake, scan the working directory for files that look like product context: a `README`, product docs, survey exports, review dumps, analytics exports, interview notes or transcripts. **Do not read them yet.** List what you found and ask:

> I found files here that look like product context: {list}. May I read them? **This context is processed only by your agent locally — it is not sent anywhere.**

Read only what the user approves. If they decline — or if there is no way to ask — proceed without the files and say so in one line. Even under a blanket yes, never open files that look like secrets or private material (`.env`, credentials, personal notes); name the specific files you are about to read.

Anything read this way is still user input under §3: a hypothesis, entered in the *"What you told me"* ledger, never a fact.

## 9. Every claim carries its status

Every claim in the output is one of three things, and says which:

- **Backed** — a quote or a number that is actually in the source. Cite it: the quote, or the file and row it came from.
- **Derived** — inferred from the data. Say *from what*: *"derived from the 4 calls where the buyer named price before delivery."*
- **Model hypothesis** — the skill's own idea, present in none of the sources. Label it as such.

**A number a respondent said out loud is that person's opinion, not a market fact.** *"60–70% of deals go through tenders"* ships as *"per the sales director — an estimate, not a measured figure."* A spoken number never becomes a market-sizing input, a chart value, or a headline without an outside source behind it (Rule 2).

**Ideas the model invented stay out of the findings.** A warranty nobody mentioned, a persona nobody described, a channel nobody named — these may appear **only** in a clearly-marked *"Hypotheses to validate"* section, never inside the value proposition, the segments, the sizing, or the verdict as if the data supported them.

## 10. Frequency counts on every aggregated claim

Wherever the skill aggregates claims from source material — interviews, sales calls, reviews, support logs, survey open-ends, documents the user supplied — **every segment-level or market-level claim carries a frequency count and its source references**: *"said in 7 of 22 interviews: #3, #7, #9, #11, #14, #18, #21."* Without the count and the list, the claim does not ship.

**A claim supported by exactly one source may not appear in a segment-level or market-level conclusion.** It goes into a separate list — *"Single signals — verify before acting"* — with its source and what would confirm it.

**One vivid quote is never "the segment's main pain."** Vividness is not frequency; a memorable sentence from one respondent is the most common way a report invents a segment that isn't there.

## 11. Confidence scaled to the input the user actually gave

Claimed confidence is computed per run from the evidence on hand. This complements the fixed disclaimers (Rule 3) — those are static, this one is measured.

Count the real evidence: interviews, analytics exports, reviews, documents, verifiable external sources.

**Thin input** — no interviews, no analytics, just a description of the idea:

- Put a warning in the header, where it can't be missed: **"Thin input: estimates are ±X ranges, segments are hypotheses."**
- Give every number as a **range**, not a point value; write *hypothesis* beside every segment.
- List the **top 3 inputs that would most raise accuracy**, concrete and ordered by how much each would move the answer — *"10 interviews with {segment}," "your last 6 months of activation data," "your win/loss notes."*

With richer input, tighten the ranges and say what they now rest on. A Quick run on one paragraph must never read with the same confidence as a Deep run on twenty interviews.

---

## How each skill wires this in (integration checklist)

A producer skill satisfies this contract when:

- [ ] It prints the **helicopter-view** block before the first intake question (§1).
- [ ] Its intake batch includes the **output-format** question (§2) and the **output-path** question (§5).
- [ ] If HTML is chosen, it writes one self-contained `.html` with working anchors + `<details>` (§2).
- [ ] Its template carries the **"What you told me — and the risks I see in it"** block, and its intake/self-critic enforces the input-as-hypothesis gate (§3).
- [ ] Its Layer-1 template carries the **validation-debt line**, and every `GO` is **`GO (to validation)`** (§4).
- [ ] On hand-off, it asks what validation debt has been retired since the prior artifact (§4c).
- [ ] Deep mode enforces the **evidence floor + self-critic loop** and offers the **web-MCP fallback** (§6).
- [ ] Its intake asks **market + audience language**, and every example, channel, and price anchor comes from that market (§7).
- [ ] It **lists repo context files and waits for a yes** before reading them, with the local-processing notice (§8).
- [ ] Every claim is tagged **backed / derived / hypothesis**; spoken numbers are labelled as opinion; invented ideas sit only in *Hypotheses to validate* (§9).
- [ ] Every aggregated claim carries a **frequency count + source list**; single-source claims sit in *Single signals* (§10).
- [ ] Confidence is **scaled to the input**: thin input gets the header warning, ranges, and the top-3 missing inputs (§11).
