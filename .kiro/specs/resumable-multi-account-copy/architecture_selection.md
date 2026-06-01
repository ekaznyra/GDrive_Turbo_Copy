# Architecture Selection: resumable-multi-account-copy

## Recommended Architecture: Layered (Engine / Accounting / Persistence / Orchestrator)

### Rationale
The layered split has the lowest cross-cutting requirements (≈43%) and zero synchronous cycles, while isolating the manifest — the dominant coupling point touched by six of seven requirements — behind a single `ProgressStore` persistence boundary. The trade-off is more components and slightly higher cross-cutting *invariants* than a single-aggregate design, because cap enforcement and accounting are deliberately kept separate from persistence, which puts a bit more wiring in the Orchestrator.

### Components
| Component | Owned State | Responsibility |
|-----------|-------------|----------------|
| CopyEngine | `drive_service` (current account) | Wraps the existing recursive copy/list/create + `_execute_with_retry` logic; copies one item, returns bytes copied and a status (COPIED/SKIPPED/FAILED). Preserves exclusion + pagination behavior. |
| SizeGovernor | `account_copied_bytes`, `per_account_cap_gb` | Decides whether the next copy is permitted; accumulates only newly-copied bytes; signals cap-reached. Reset per account. |
| ProgressStore | `manifest`, `manifest_file` (JSON on disk), `checkpoint` | Loads/persists per-item status (PENDING/COPIED/SKIPPED/FAILED), size, account, and error. Crash-safe write after each item. Source of truth for resume. |
| Orchestrator | account loop, `global_copied_bytes`, report | Discovers source items into the manifest, drives the per-item loop, handles account handoff/reset, evaluates completeness, prints + persists the report. |

### Information Flow
| From \ To | CopyEngine | SizeGovernor | ProgressStore | Orchestrator |
|-----------|-----------|--------------|---------------|--------------|
| CopyEngine | – | | → (bytes/status) | |
| SizeGovernor | | – | | |
| ProgressStore | | | – | |
| Orchestrator | → | → | → | – |

Per item, the Orchestrator: (1) asks SizeGovernor if the next copy is allowed, (2) calls CopyEngine to copy, (3) records the result in ProgressStore and updates SizeGovernor. The graph is acyclic with no callbacks.

### Requirement Allocation
| Requirement | Component(s) |
|-------------|--------------|
| REQ-1 (preserve engine) | CopyEngine |
| REQ-2 (per-account cap) | SizeGovernor (CopyEngine reports bytes) |
| REQ-3 (durable manifest) | ProgressStore (CopyEngine reports status) |
| REQ-4 (checkpoint on cap) | ProgressStore + SizeGovernor |
| REQ-5 (multi-account resume) | Orchestrator + ProgressStore |
| REQ-6 (loop until complete) | Orchestrator |
| REQ-7 (final report) | Orchestrator (reads ProgressStore) |

### Key Design-Induced Invariants
- **DI-1:** The cap check (SizeGovernor) is queried by the Orchestrator *before* each CopyEngine call, so `account_copied_bytes ≤ cap` holds at all times (INV1). Accounting is never deferred past the next copy.
- **DI-2:** ProgressStore is the *only* writer of the manifest file; every status transition is flushed before the next item begins, guaranteeing crash-safe resume (INV5).
- **DI-3:** On account handoff the Orchestrator resets SizeGovernor's accumulator to 0 but never mutates ProgressStore's manifest (INV6) — per-account state and global progress are owned by different components and cannot drift.
- **DI-4:** Resume position is *derived* from manifest status, not stored as an index, so there is no separate cursor that could disagree with the manifest.

### Alternatives Considered
| Candidate | Strength | Weakness | Why Not Selected |
|-----------|----------|----------|------------------|
| Event-driven (Engine emits, subscribers accrue/persist) | Easy fan-out: add observers (progress bar, metrics) with zero engine changes | Sync-vs-event ordering hazard: cap must be enforced pre-copy but accounting is post-copy event; EventBus adds indirection | Highest cross-cutting reqs (≈71%) and a cycle risk around INV1 in a single-threaded notebook where the bus earns nothing |
| Entity/aggregate (CopyJob owns manifest + accounting) | Lowest cross-cutting invariants (≈14%); all rules internally consistent; trivial rehydrate-and-resume | God-object: CopyJob owns ~70% of state; persistence not a clean separate boundary | Concentrated risk; violates the explicit separate-storage-boundary goal; harder to evolve one concern without touching the aggregate |

### Metrics Summary
| Metric | Selected (Layered) | Alt A (Event) | Alt B (Entity) |
|--------|--------------------|---------------|----------------|
| Cross-cutting reqs % | 43% | 71% | 57% |
| Cross-cutting invariants % | 43% | 57% | 14% |
| Flow density | 0.33 | 0.35 | 0.33 |
| God object score | ~30% | ~30% | ~70% |
| Sync cycles | 0 | 1 (risk) | 0 |
| Max fan-in | 2 | 2 | 2 |
| Max fan-out | 3 | 3 | 3 |
| Evolvability cost | ~1.4 | ~2.0 | ~1.6 |
