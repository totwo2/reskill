# reskill — Audit the code before release, collect feedback after

English | [简体中文](README.md)

**Current version v3.5.1**

> The code is written and the tests pass. Everything that is left goes here:
> audit the code → pass the quality gate → write the README and SKILL.md →
> settle the summary and tags → decide the distribution form → publish to both platforms →
> collect downloads and issues.

## What it solves

When you write a skill or a small tool, the real trouble only starts once it is "done":

- **Who was this code written for?** Did you build three features for a requirement nobody had?
- **The README reads like a dev log**, and a stranger bounces off it in three seconds.
- **The summary and tags are technical words**, so the people searching for the outcome never find you.
- **GitHub or SkillHub**, and should it be packed as an installer? All guesswork.

reskill turns those four things into one gated pipeline, and **every step has an independent judge** —
the writer never scores its own work.

## 30-second start

Install it into your AI assistant and say one sentence:

```
"帮我把这个 skill 发出去"
```

It walks the whole thing itself: form decision → fact sheet → write the release artifacts →
hard gate → quality judges → assembly → publish → wrap up.

## One command, run repeatedly (local)

Put `SKILL.md`, `README.md` and the fact sheet in your project, then call the same command over and over:

```bash
python3 scripts/local_publish.py --project <your project>
```

The exit code tells you what to do next:

| Exit code | Meaning |
|---|---|
| **0** | Terminal state reached: `released` or `deferred` |
| **10** | Stopped at a step that needs judgement; **the task sheet is generated**, and it tells you where to write the verdict back |
| **1** | Usage or environment problem — it will not run blind |

Verdicts go back to `<project>/.publish-staging/verdicts/<node>.json`:

```json
{"score": 4.5, "judge": "who judged it", "reason": "criterion (with file:line)"}
```

**The executor never writes this file itself.** The verdict must be delivered by a party outside the
executor — that is the mechanical guarantee behind "scoring your own work does not count".
A malformed verdict (missing signature / missing criterion) is **returned on the spot** and does not
consume a retry: "written it wrong" and "could not do it" are not the same thing.

## How it guarantees quality

Three locks — lose one and things slip through:

| Lock | How |
|---|---|
| **Hardened criteria** | Anything a machine can decide is pushed down into scripts: size, anchors, metadata, whether commands actually run |
| **Unanimous pass** | Quality judges + flow judge + audit — **any single fail sends it back** (not a majority vote) |
| **Safe by default** | Three consecutive failures → **automatically not published**, report kept, read it if you want |

**"Automatically not published" is a design choice, not a failure.** It guarantees nothing embarrassing
goes out; the price is occasionally missing something that should have shipped — publish less, publish
more steadily.

Because you do not have to babysit it, the judgements have to leave their own evidence.

### Decision ledger

Every judgement lands as one line in `ledger.jsonl`:

```
time / node / attempt / verdict / score / score floor / judge signature / criterion
```

**Why scores are mandatory**: with pass/fail alone, "it passed" is all you know — a loosened standard
looks exactly like a competent one. With scores you can spot "the same kind of artifact scored 2 this
time and 4 last time" — the only signal that a standard was quietly relaxed.

## Layout

```
reskill/
├── SKILL.md                        # the LLM execution manual (entry point)
├── publish.md                      # release flow (GitHub / SkillHub)
├── publish-quality.md              # four quality gates + form decision + summary and tags
├── publish-code-audit.md           # third-party source audit (coverage / overreach / hallucination)
├── publish-expert-team.md          # role split and permission boundaries
├── publish-team-roster.md          # the single source of truth for roles
├── publish-flow-control.md         # state machine and node table
├── publish-llm-gate.md             # the judge LLM, including unattended mode
├── feedback-collector.md           # issue checking and feedback extraction
├── notification.md                 # multi-channel notification
├── references/                     # spec source texts (GitHub skills spec, etc.)
├── scripts/
│   ├── local_publish.py            # single entry: one command, called repeatedly (recommended start)
│   ├── publish_flow.py             # state machine + decision ledger (unattended)
│   ├── local_executor.py           # the real local executor (machine nodes / reads the verdict inbox)
│   ├── verdict_dispatch.py         # verdict dispatch: set the task sheet + collect and validate
│   ├── detect_publish_form.sh      # N0 form decision
│   ├── quality_metrics.py          # objective proxy metrics (scores README / SKILL.md)
│   ├── executor_example.py         # sample wiring for an external executor
│   ├── preflight_quality_check.py  # quality gate (criteria split by kind: optimizations need numbers / features need actions)
│   ├── preflight_publish_check.sh  # pre-release check
│   ├── preflight_secret_scan.sh    # credential scan
│   ├── check_discoverability.py    # discoverability: is anyone searching this topic + is the name taken
│   ├── verify_audit_report.py      # audit-table evidence integrity (empty evidence row / fake anchor → exit 1)
│   ├── trace_callchain.py          # overreach decision: trace the call chain from the entry point (reachable / dead / uncertain)
│   ├── verify_ledger.py            # ledger independence evidence: reason must carry anchor / no author voice / no cross-ref → exit 1
│   ├── check_doc_anchors.py       # N4.5 automation: pull README commands/identifiers → find anchors in source
│   ├── verify_brief_factsheet.py  # N0.2 structure check + fact-sheet linkage (R4 non-empty / quote anchor / R3 hard contradiction → exit 1)
│   ├── crosscheck_dual_platform.sh # N3-X cross-platform consistency (version/name match; gh/sh drift → exit 1; positioning is 🟡 only)
│   ├── verify_criteria_hash.py     # Q5 criteria hash ledger + change prompt (never hard-blocks; --strict to REJECT)
│   ├── pack_skillhub.sh            # N6-S packaging: produce a clean copy for SkillHub
│   ├── gh_skill.py                 # GitHub skill operations
│   ├── gh_release.py               # releases and topics
│   ├── check_downloads.py          # download tracking
│   ├── daily_report.py             # daily report
│   └── fetch_my_skills.py          # sync the skill list under your name
└── settings/                       # config, snapshots and release history
```

## Every script can prove itself

No need to read the code — run it and look at the last line:

```bash
cd scripts
python3 local_publish.py --test       # 15 checks: machine nodes advance / semantic nodes stop and set a task sheet / bad verdicts returned
python3 publish_flow.py --test        # 23 checks: skipped steps rejected / low scores blocked / over-limit not published
python3 local_executor.py --test      # 18 checks: machine nodes really run; semantic nodes blocked while the inbox is empty
python3 verdict_dispatch.py --test    # 25 checks: task sheets must carry evidence / validation separates "judged badly" from "judged no"
python3 quality_metrics.py --test     # 6 checks: objective metrics separate good samples from bad
python3 check_discoverability.py --self-test   # 17 checks: dead words caught / no data means no false verdict
python3 preflight_quality_check.py --test     # 9 checks: two criteria classes kept apart / missing numbers on optimizations must FAIL / undeclared kind not punished
python3 verify_audit_report.py --test  # 13 checks: empty evidence rows caught / fake anchors caught / stale reports not falsely accused
python3 trace_callchain.py --test      # 7 checks: reachable chain / zero-reference orphan = dead code / unreachable but referenced = uncertain
python3 verify_ledger.py --test        # 14 checks: only independence evidence (anchor / no author voice / no cross-ref); same judge body = note only
python3 check_doc_anchors.py --test     # 9 checks: command classification / identifier grep / output passes the verifier
python3 verify_brief_factsheet.py --test # 6 checks: empty R4 / no quote / missing fields caught; R3 hard contradiction exit 1; coverage gap is 🟡 only
python3 verify_criteria_hash.py --test  # 5 checks: init baseline / unchanged consistent / change prompt not blocking / --strict blocks / revert consistent
./crosscheck_dual_platform.sh --test  # 5 checks: version match / title has name / positioning 🟡 only / title missing name / gh-sh drift
./detect_publish_form.sh --test       # 5 checks: the four release paths decided correctly
./pack_skillhub.sh --test             # 11 checks: clean copy / real files intact / non-skill rejected
```

Seeing `结果：N 通过 / 0 失败` counts as passing. **188 checks** in total.

## Bring your own executor

The default executor only verifies the machinery; it produces no content. To wire in real generation and
judging, use `--exec`:

```bash
python3 scripts/publish_flow.py --project <project> run --auto \
    --exec "python3 scripts/executor_example.py"
```

The executor reads context from environment variables (`PFLOW_NODE` / `PFLOW_PROJECT` / `PFLOW_STAGING` /
`PFLOW_ATTEMPT` / `PFLOW_NEED` / `PFLOW_MIN_SCORE`) and throws back on the last line of stdout:

```json
{"verdict": "pass|fail", "score": 0-5, "reason": "a verifiable criterion", "judge": "who judged it"}
```

A non-zero exit code, or no JSON → **always judged fail** (the safe default).
See `scripts/executor_example.py` for the template.

## Security

- **Never commit real tokens.** Use `settings/reskill_config.example.yaml` as the template.
- Run `bash scripts/preflight_secret_scan.sh .` before every release.
- SkillHub login credentials stay only in the local CLI state.

## License

MIT
