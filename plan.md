# DT-Orchestrator Bridge — Execution Plan & Checklist

> Living document. Tick boxes as you go. Don't delete failed attempts —
> move them to `docs/findings.md` so phase 2 inherits the lessons.

## North Star (do not edit without re-discussing)

> Prove that Matterix DT can be integrated with an SDL orchestrator,
> and that this integration delivers measurable safety value before
> plans reach real hardware. Pick-and-place with stock Matterix assets
> is the carrier. No zinc battery. No real hardware. No USD authoring.

## Three-line project description

- **What**: A PoC that bridges a mini SDL orchestrator with Matterix DT
- **Input**: A simple `PickAndPlace` unit operation (grab beaker, place at target)
- **Stack**: Stock Matterix assets (Franka + Robotiq85 + beaker_500ml) + a real-stub backend
- **Story**: (1) one plan runs on both sim and stub-real; (2) sim catches several classes of unsafe ops before they reach real

## Sequencing principle

Protocol-first. We do NOT pick "sim end first" or "orchestrator end first" —
both are implementations of a shared protocol. The protocol is written first;
both ends are implementations.

---

## Day 0 — Skeleton & contracts (no Matterix yet)

Goal: pushed-up monorepo, green CI, hello-world runs, zero Matterix code.

### Setup
- [ ] Create private GitHub repo `dt-orchestrator-bridge`
- [ ] `git init` locally, set up remote
- [ ] Add `.gitignore`, `.python-version`, `LICENSE` placeholder ("All rights reserved, internal AC project, license TBD")
- [ ] Install `uv` if not already (`curl -LsSf https://astral.sh/uv/install.sh | sh`)

### Spike — verify A1 (configs-only assumption)
- [ ] On a non-GPU machine: `pip install matterix_sm`
- [ ] Run `python -c "from matterix_sm import PickObjectCfg, MoveCfg; print('OK')"`
- [ ] **If fails**: log error in `docs/findings.md`, ping me before proceeding
- [ ] **If succeeds**: list which Cfg classes import cleanly without Isaac runtime, save to `docs/findings.md`

### Repo scaffolding
- [ ] Create `pyproject.toml` at root (uv workspace)
- [ ] Create `packages/twin-core/` with its own `pyproject.toml`
- [ ] Create `packages/twin-sim/` placeholder (empty package, fills in Day 2)
- [ ] `uv sync` works without errors

### Contract layer (twin-core)
- [ ] `src/twin_core/schemas.py` — Pose, Observation, Action (Pydantic v2)
- [ ] `src/twin_core/protocols.py` — ExecutorBackend, FrameService Protocol
- [ ] `src/twin_core/errors.py` — ValidationError hierarchy
- [ ] `src/twin_core/operations.py` — PickAndPlace dataclass + operation_to_workflow stub
- [ ] `src/twin_core/mock_backend.py` — minimal MockBackend implementing ExecutorBackend

### Examples & tests
- [ ] `examples/00_hello_mock.py` — runs MockBackend through PickAndPlace, prints actions
- [ ] `tests/unit/test_mock_backend.py` — basic mock behavior
- [ ] `tests/contract/test_executor_contract.py` — contract test all backends must pass
- [ ] `pytest` runs green locally

### CI & docs
- [ ] `.github/workflows/ci.yml` — runs pytest on push
- [ ] CI badge green on first push
- [ ] `README.md` — three-line description + how to run hello-world
- [ ] `docs/project-charter.md` — full charter (paste from prior discussion)
- [ ] `docs/decisions/0001-protocol-first.md` — first ADR

### Day 0 commit
- [ ] First commit message: `scaffold: monorepo skeleton with executor protocol and mock backend`
- [ ] Push to private remote
- [ ] CI passes on remote

### Optional overnight
- [ ] Start Isaac Sim install in background terminal — if it works by Day 1 morning, bonus

---

## Day 1 — Isaac Sim spike + protocol calibration

Goal: see the real Matterix observation/action with own eyes, calibrate v0 protocol to v1.

### Spike #1 — Isaac Sim + Matterix
- [ ] Install Isaac Lab 2.3 (conda route per Matterix README)
- [ ] Clone Matterix with `--recurse-submodules`, `git lfs pull` for assets
- [ ] Install Matterix packages: `pip install -e source/*`
- [ ] Run `scripts/zero_agent.py --task Matterix-Test-Beakers-Franka-v1 --num_envs 1`
- [ ] **HARD CUTOFF**: if not running by 3pm Day 1, fall back to configs-only-only route, document in findings
- [ ] Run `scripts/run_workflow.py --task Matterix-Test-Beaker-Lift-Franka-v1 --workflow pickup_beaker`
- [ ] **A3 verified** when beaker visibly lifts in sim

### Schema calibration (v0 → v1)
- [ ] Inspect actual shape of Matterix observation dict — record fields, types in findings
- [ ] Inspect actual shape of action_dict — record same
- [ ] Inspect a beaker_500ml asset config — list all defined frames
- [ ] Update `twin_core/schemas.py` — Observation/Action/Pose match Matterix reality
- [ ] Update contract tests — they should still pass with v1 schema
- [ ] Commit: `refactor(schemas): calibrate v1 against real Matterix shapes`

### Findings log (mandatory)
- [ ] `docs/findings.md` updated with: configs-only scope (A1), Matterix obs/action shape, frame inventory of beaker_500ml
- [ ] Note any assumption that turned out wrong

---

## Day 2-3 — Sim backend + orchestrator stub

### Day 2: sim backend
- [ ] `packages/twin-sim/src/twin_sim/backend.py` — wrap Matterix env as ExecutorBackend
- [ ] Handle async/sync bridge — Matterix step is sync, ExecutorBackend protocol must accommodate
- [ ] `packages/twin-sim/src/twin_sim/frame_service.py` — read frames from asset config / USD
- [ ] `examples/01_run_sim.py` — call sim backend with a PickAndPlace, watch beaker move
- [ ] Sim backend passes contract tests
- [ ] Commit: `feat(twin-sim): wrap Matterix env as ExecutorBackend`

### Day 3: orchestrator stub + adapter
- [ ] In twin-core: flesh out `operation_to_workflow()` — translate PickAndPlace to Matterix WorkflowDict
- [ ] Write `MiniOrchestrator` class (in twin-core) — accepts `list[UnitOperation]`, dispatches via backend
- [ ] `examples/02_orchestrator_to_sim.py` — orchestrator drives sim
- [ ] **Day 3 milestone**: orchestrator-driven workflow lifts the beaker in sim
- [ ] Commit: `feat(orchestrator): mini orchestrator drives sim end-to-end`

### A4 verification
- [ ] Confirm: Matterix asset frames are sufficient for PickAndPlace at this abstraction level
- [ ] If not — what's missing? Add note to findings

---

## Day 4-5 — Real-stub backend

- [ ] `packages/twin-real/` package created
- [ ] `twin_real/backend.py` — implements ExecutorBackend, mirrors sim API exactly
- [ ] Internal state machine: gripper open/closed, ee pose
- [ ] Latency simulation: each action sleeps 0.5–2s
- [ ] Failure injection: `TWIN_REAL_INJECT_FAILURE=...` env var
- [ ] Raises `StateMachineViolation` on inconsistent commands
- [ ] Passes the same contract tests as sim backend
- [ ] `examples/03_orchestrator_to_real_stub.py` — orchestrator drives stub
- [ ] Commit: `feat(twin-real): stub backend with state machine and failure injection`

---

## Day 6-7 — Safety layer

Demo target: 4 workflows, 3 caught, 1 passes.

### Pre-flight checks (Day 6)
- [ ] `twin_core/validation.py` — schema validator (use Pydantic)
- [ ] Frame existence checker — uses FrameService.lookup, raises FrameNotFound
- [ ] State machine pre-validator — replays plan against a state model, catches StateMachineViolation
- [ ] Each error includes: error class, plan segment, asset/frame in question, human-readable why
- [ ] Tests for each error class

### Sim dry-run (Day 7)
- [ ] `twin_sim/dry_run.py` — given a workflow, runs in sim, returns success/failure + reason
- [ ] Catches PhysicalInfeasibility (collision, unreachable target)
- [ ] Construct 4 demo workflows:
  - [ ] WF1: schema violation (e.g., wrong frame type)
  - [ ] WF2: frame not found
  - [ ] WF3: physical infeasibility (target out of reach OR through obstacle)
  - [ ] WF4: clean — passes everything
- [ ] `examples/04_safety_demo.py` — runs all 4, shows the 3 catches + 1 pass with structured logs

### Fallback if a category is too hard
- [ ] If physical infeasibility hard to trigger reliably — substitute with unit mismatch or rate-of-change violation. Document switch in findings.

---

## Day 8 — Arbitrator

- [ ] `packages/twin-arbiter/` (or just a module in twin-core)
- [ ] Mode enum: `sim_only` | `real_only` | `sim_first_then_real`
- [ ] In `sim_first_then_real`: runs sim dry-run; on pass, dispatches to real; on fail, propagates error and does NOT touch real
- [ ] `examples/05_sim_first_then_real.py` — feed it WF3 (physically infeasible) and WF4 (clean) — show real only sees WF4
- [ ] Commit: `feat(arbiter): mode-driven dispatch with sim-first gating`

---

## Day 9 — (Stretch) Shadow mode

Skip without guilt if Day 6-8 ran long.

- [ ] Arbitrator mode `shadow` — sim and real run in parallel
- [ ] Divergence detector — compare ee pose between sim obs and stub obs at each step
- [ ] If divergence > threshold, raise `DivergenceAlert`, log both observations
- [ ] `examples/06_shadow_mode.py` — inject deliberate offset in stub, watch detector fire

---

## Day 10 — Report + demo

- [ ] `docs/findings.md` final pass — every assumption marked verified/falsified/partial
- [ ] `docs/architecture.md` — final architecture with diagram
- [ ] Update `docs/project-charter.md` if scope shifted
- [ ] Demo script written — 5 minute walkthrough hitting all 3 demo points
- [ ] Demo recording (Loom / OBS / whatever)
- [ ] One-page summary for leadership review

---

## Decisions to log as ADRs as they happen

Anything in this list, write `docs/decisions/000N-<topic>.md` (3 paragraphs:
context, decision, alternatives). Don't be precious — write fast, revise later.

- [x] 0001 protocol-first architecture (Day 0)
- [ ] 0002 monorepo + uv workspace
- [ ] 0003 Matterix as dependency, not fork
- [ ] 0004 Pydantic v2 for schemas
- [ ] 0005 real-stub vs. real hardware in PoC scope
- [ ] 0006 safety error taxonomy (4 classes)
- [ ] 0007 arbitrator modes
- [ ] (add as you go)

---

## Pre-flight discipline (every commit)

- [ ] Tests pass locally (`uv run pytest`)
- [ ] CI green on push
- [ ] Commit message follows conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`)
- [ ] If decision was made — corresponding ADR exists

## Things to flag to leadership early

- [ ] Sync with Alan: confirm scope and demo expectations (Day 1 or 2)
- [ ] Sync with Sean / Willi: confirm no overlap with other Matterix work
- [ ] Reach out via SiLA Slack to UniteLabs (low priority, phase 2 prep)

## Risks tracker

| ID | Risk | Status | Mitigation |
|----|------|--------|------------|
| R1 | Matterix configs-only scope unclear | open | Day 0 spike |
| R2 | Isaac Sim install fails | open | Day 1 hard cutoff 3pm |
| R3 | Schema mismatch needs rework | open | v0 → v1 calibration Day 2 |
| R4 | Safety category hard to construct | open | Substitute category |
| R5 | Out of time for Day 9 stretch | open | Acceptable, document as phase 2 |

---

dt-orchestrator-bridge/
├── README.md
├── plan.md                                ← 你的 checklist
├── pyproject.toml                         ← uv workspace root
├── .gitignore
├── .python-version
├── docs/
│   ├── project-charter.md                 ← 上一轮起草的完整版
│   └── decisions/
│       └── 0001-protocol-first.md
├── packages/
│   ├── twin-core/
│   │   ├── pyproject.toml
│   │   └── src/twin_core/
│   │       ├── __init__.py
│   │       ├── protocols.py               ← ExecutorBackend, FrameService
│   │       ├── schemas.py                 ← Observation, Action, Pose
│   │       ├── operations.py              ← PickAndPlace, adapter
│   │       ├── errors.py                  ← ValidationError 层级
│   │       └── mock_backend.py            ← MockBackend for Day 0
│   └── twin-sim/                          ← Day 2 才填，先占位
│       └── pyproject.toml
├── workflows/
│   └── README.md
├── examples/
│   └── 00_hello_mock.py
├── tests/
│   ├── unit/
│   │   └── test_mock_backend.py
│   └── contract/
│       └── test_executor_contract.py
└── .github/workflows/
    └── ci.yml