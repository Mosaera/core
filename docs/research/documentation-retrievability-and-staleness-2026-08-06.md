# Documentation retrievability and staleness — external research

> **Reference research, not a Mosaera spec.** External, point-in-time research gathered 2026-08-06 to
> answer two questions before building anything: *why did documented knowledge fail to reach the
> work*, and *how do mature orgs stop docs going stale*. It is **not** normative and is not maintained
> against the code. Binding decisions live in [`../adr/`](../adr/README.md). Where this and those
> disagree, they win.

**Evidence grading is used throughout and is the point of this document.** Most published advice here
is unmeasured. Distinguishing what is *measured* from what is merely *practised* is what makes this
worth keeping.

- **[MEASURED]** — controlled study or dataset with numbers
- **[OBSERVED]** — large-scale empirical/descriptive, no causal claim
- **[PRACTISED]** — widely adopted, no measurement found
- **[ASSERTED]** — vendor or blog claim only

## Why this was commissioned

In one session (2026-08-06) two findings were **rediscoveries** of knowledge already in the repo:

- **F62** re-derived the `unsatisfied_claim` / `_GIVE_UP_ALLOWED_REASONS` allowlist defect that had
  been measured and written up the previous day *and quoted at length in the roadmap's Current focus*
  — then a feature was built on that same broken allowlist.
- **F58** rediscovered **F30** from scratch, one day later.

Corpus at the time: 129 files, 22,080 lines, 86 ADRs, a 1109-line roadmap, a 2954-line findings log.

## Part A — the four things NOT to build

These are the expensive mistakes the research avoided. Recorded first, with numbers, because they are
each individually tempting.

### A1. RAG / semantic search over the docs — **don't**

- Anthropic's reported position: tried RAG, moved to agentic search because "it outperformed
  everything — by a lot, and this was surprising" [ASSERTED, no published numbers]
  (Latent Space, May 2025). Cline published the same conclusion:
  [Why Cline Doesn't Index Your Codebase](https://cline.bot/blog/why-cline-doesnt-index-your-codebase-and-why-thats-a-good-thing) ·
  [Why I Stopped Using RAG for Coding Agents](https://jxnl.co/writing/2025/09/11/why-i-stopped-using-rag-for-coding-agents-and-you-should-too/)
- RAG failure modes are largely *silent*: of 143 enterprise deployments studied, 73% hit a critical
  failure in the first quarter and **41% of those went undetected by standard eval suites**
  [OBSERVED, secondhand — verify primary before quoting].
- Agent memory systems measurably **entrench wrong facts**: [MemSyco-Bench](https://arxiv.org/pdf/2607.01071)
  (sycophancy in agent memory), [MemTrace](https://arxiv.org/pdf/2605.28732) (error attribution).
- **Important caveat on the grep-beats-RAG result:** it is about *code*, where identifiers are exact
  and greppable. It does **not** transfer to prose. An engineer grepping a component name will not
  hit a roadmap paragraph describing the defect in narrative English — unless the prose contains the
  identifier verbatim. See [Nuss & Bolts](https://www.nuss-and-bolts.com/p/on-the-lost-nuance-of-grep-vs-semantic).

### A2. More content in `CLAUDE.md` / `AGENTS.md` — **don't**

- [Two-Agent Ablation Study](https://arxiv.org/html/2607.27250) **[MEASURED]** — 291 runs, 3 repos,
  3 repeats, conditions none/always-on/selective. Claude 53.3% (none) vs 55.6% (context); Codex 58.8%
  (none) vs 56.9–52.9% (context). **No significant difference either way.** Author conclusion:
  *"Context strategy does not measurably move correctness on either agent."*
- LLM-generated context files (i.e. `/init` output) measured **~3% lower** task success at **>20%
  higher** inference cost [MEASURED, secondhand].
- [Agent READMEs: An Empirical Study](https://arxiv.org/html/2511.12884v1) **[OBSERVED]** — 2,303
  files / 1,925 repos. Median ~500 words. Flesch Reading Ease **16.6** (legal-document territory).
  Evolution is **append-only**: 67.4% revised repeatedly, median +57 words per commit, deletions rare.
- The field is openly contradictory (Lulla 2026 finds efficiency gains; Gloaguen 2026 finds none).
- **What the evidence does support is routing indexes with on-demand loading** — a different thing
  that is frequently conflated with large always-on context.

### A3. Reorganising by Diátaxis — **don't**

- [Diátaxis](https://diataxis.fr/) / [Divio](https://docs.divio.com/documentation-system/) are
  **[PRACTISED]**, adopted by Canonical, Django, Cloudflare — with **no controlled study** found
  showing improved retrieval time or success.
- Critiques: [Tom Johnson](https://idratherbewriting.com/blog/what-is-diataxis-documentation-framework)
  (real users don't separate modes cleanly; the split forces duplication and orphans),
  [Peter Williams](https://newton.cx/~peter/2023/divio-documentation-system/).
- **The structural gap that matters for us:** Diátaxis has **no category for "this component is
  currently broken, measured on date D"**. It is a taxonomy of *stable instructional content*, not of
  *live engineering state* — which is exactly what a findings log is. It would improve authoring
  discipline and coverage auditing; it does nothing for finding a fact you didn't know existed.

### A4. A deeper documentation hierarchy — **don't**

[Is Progressive Disclosure All You Need for Long-Context Agents?](https://arxiv.org/html/2607.17598v1)
**[MEASURED]** — compares raw (agent reads docs) vs flat (one routing file indexing chunks) vs
hierarchical (recursive per-chunk):

- Multi-corpus (K=20 docs): raw 0.257 → **flat 0.462** (~1.8×), at roughly **half the tokens**.
- **Hierarchical collapsed: 0.640 vs flat 0.913** on single-doc MC. Deep nesting *hurt*.
- Null result worth knowing: on Codex, no improvement at all — that harness reconstructs retrieval
  natively.
- Stated limitations: memorization confound on canonical texts, narrow corpora, some comparisons
  within standard error.

**One flat index with stable IDs beats a tree.**

## Part B — what the evidence supports

### B1. Retrieval failure is a *delivery* failure — the strongest result here

The **lessons-learned systems** literature (Weber & Aha) studied large organizational repositories
(military, NASA, DoE) and found they fail **not** because knowledge is missing or badly written, but
because retrieval is **passive** — it requires the worker to decide to go look, at the moment they
don't know they need to.

Their intervention was **active delivery / monitored distribution**: the system watches the work being
done and *pushes* the relevant lesson into the decision surface, unprompted. **[MEASURED]** —
significantly improved plan-execution measures versus a searchable repository.

- [Intelligent lessons learned systems](https://www.sciencedirect.com/science/article/abs/pii/S0957417400000464)
- [Intelligent delivery of military lessons learned](https://www.sciencedirect.com/science/article/abs/pii/S0167923602001227)

**This is the most directly transferable result in the whole report: attach the knowledge to the
artifact the worker touches, rather than improving the index.**

### B2. Information Foraging explains our specific failure

Developers follow *information scent* — surface cues that predict value — and abandon a trail when
scent is weak, **even when the prey is at the end of it**. Piorkowski et al. measured that developers
are **bad at predicting the value of navigation choices** and optimize on cost, not value.

- [Foraging and Navigations, Fundamentally (FSE 2016)](http://web0.cs.memphis.edu/~sdf/publications/Piorkowski_et_al_FSE_2016.pdf) **[MEASURED]**
- [An IFT Perspective (TOSEM 2013)](https://dl.acm.org/doi/10.1145/2430545.2430551)

Applied to F62: a defect described inside a long roadmap section has **no scent from where the
engineer is standing** (in `disposition.py`). Quoting it "at length in the most-read section"
increased exposure but not scent — **and length actively reduces scent.**

### B3. Context rot — the machine version of the same failure

- [Chroma, *Context Rot*](https://research.trychroma.com/context-rot) **[MEASURED]** — 18 frontier
  models, **all** degrade at **every** input-length increment; a 200K window can show serious accuracy
  loss by 50K tokens.
- *Lost in the Middle* (Liu et al.) **[MEASURED]** — U-shaped position curve, **>30% accuracy drop**
  for mid-context facts.

**Implication:** a 2954-line findings log and a 1109-line roadmap, pasted wholesale, are the *worst
possible* delivery vehicle — the important fact sits in the middle.

### B4. Derived status cannot go stale; typed status structurally can

Both of our failures were hand-typed fields duplicating a fact that lives elsewhere. The literature is
consistent: **statuses a human types are structurally unfixable; statuses that are derived cannot go
stale.**

- [Towards identifying and minimizing customer-facing documentation debt](https://arxiv.org/html/2402.11048)
  (Ericsson) **[OBSERVED]** — 318 documentation defects classified from 1,663 bug reports; 7–11 days
  average to resolve; named causes are *"absence of robust, single information sources"* and *"lack of
  verified co-evolution between source code and documentation"*. **59% judged preventable by
  automation.**
- Broader literature: documentation debt is **removed less often and more slowly** than other
  technical-debt types — i.e. it ratchets.
- [Gojko Adzic, *Specification by Example, 10 years later*](https://gojko.net/2020/03/17/sbe-10-years.html)
  **[OBSERVED]** — the collaboration part succeeded; the *living documentation* promise failed. Only
  12% kept specs in version control, 57% let Jira become the de facto source, **29% abandoned the
  automation**. **Executable docs decay to ordinary docs the moment execution becomes optional.**

## Part C — mechanically enforceable checks (what actually catches what)

| Failure class | Mechanically catchable? | By what |
|---|---|---|
| Doc example no longer compiles/runs | **Yes, fully** | doctests, `mdbook test`, byexample |
| Doc snippet drifted from source | **Yes, fully** | [embedme](https://github.com/zakhenry/embedme) `--verify`, [cog](https://nedbatchelder.com/code/cog/) `--check` |
| Doc cites a symbol that no longer exists | **Yes** (high precision, low recall) | rustdoc intra-doc links; [arXiv 2212.01479](https://arxiv.org/abs/2212.01479) |
| Dead URL / anchor / relative path | **Yes, fully** | [lychee](https://github.com/lycheeverse/lychee), our own `check_doc_links.py` |
| Dangling ADR ID / one-way supersession / index drift | **Yes, fully** | custom lint + generated index |
| Missing owner / expired review date | **Yes, fully** | [giantswarm/frontmatter-validator](https://github.com/giantswarm/frontmatter-validator) |
| Code changed, mapped doc didn't | **Yes, noisily** | docs-map + diff gate (*the map itself decays and needs its own lint*) |
| Documented API ≠ implemented API | **Yes** (APIs only) | [oasdiff](https://github.com/Tufin/oasdiff), Schemathesis |
| **ADR policy governs code but status says not-started** | **Partly** | `enforced-by:` referent check; **grep for the ADR ID across source — a citation contradicts `not-started`** |
| **Roadmap says DONE, feature is half-broken** | **Only if derived** | hand-typed DONE is unfixable |
| Comment/prose semantically inconsistent with code | **No** — research only, too noisy to gate | Deep-JIT, CUP/HebCUP, SEOCD — use as a review *queue* |
| Rationale no longer valid; misleading but literally true | **No** | human review only |

### ADR practice at 50+ (we are at 86)

Multiple sources converge on **~50 active decisions** as the point where a folder of markdown "stops
being adequate and starts being a liability".

Named failure modes: **no lifecycle management** (*"'superseded' means someone remembers to update the
status field. In practice, nobody does"*) · **decisions happen elsewhere** (Slack/issues, so the ADR
is a second source of truth) · **mega-ADRs** that rot at documentation speed · **Fairy Tale**
(consequences list only pros, so nothing can later contradict them) · **Groundhog Day** (re-litigated
because unfindable).

Highest-yield lints named in the literature, *almost nobody implements the second*:
status ∈ enum · **bidirectional supersession** · every referenced ADR ID resolves · generated index,
never hand-maintained · an `accepted` ADR must carry `enforced-by`/`superseded-by`/`expires` (forces
the author to say how it could ever be falsified).

Sources: [10 ADR anti-patterns](https://bool.dev/blog/detail/10-adr-antipatterns) ·
[Zimmermann on ADR creation](https://ozimmer.ch/practices/2023/04/03/ADRCreation.html) ·
[MADR](https://adr.github.io/madr/) · [Log4brains](https://github.com/thomvaill/log4brains) ·
[adr-log](https://github.com/adr/adr-log)

## Part D — three things the sources agree on that cut against "add more checks"

1. **Google: corpus size is itself the defect.** *"A small set of fresh and accurate docs is better
   than a large assembly of documentation in various states of disrepair."* Dead docs "misinform,
   they slow down, they incite despair in engineers and laziness in team leads." Their recommendation
   during migrations is **default-to-deletion**, not default-to-review.
   [Google documentation best practices](https://google.github.io/styleguide/docguide/best_practices.html)
2. **Gojko: any check that can be skipped will be.** 29% abandonment of the automation is what turns
   living documentation back into documentation.
3. **The ADR literature: statuses don't get updated because the decision happened somewhere else.** A
   staleness bot pointed at the file addresses the symptom, not the two-sources-of-truth cause.

## Sources

Consolidated above. Primary sources most worth reading in full, in order:
[Weber & Aha (active delivery)](https://www.sciencedirect.com/science/article/abs/pii/S0167923602001227) ·
[Progressive Disclosure](https://arxiv.org/html/2607.17598v1) ·
[Context Rot](https://research.trychroma.com/context-rot) ·
[Two-Agent Ablation](https://arxiv.org/html/2607.27250) ·
[Ericsson documentation debt](https://arxiv.org/html/2402.11048) ·
[Google docguide](https://google.github.io/styleguide/docguide/best_practices.html) ·
[Aghajani et al., Software Documentation Issues Unveiled](https://neverworkintheory.org/2021/10/06/software-documentation-issues-unveiled.html)
