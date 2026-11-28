# M1 Audit Checklist

## Canonical Evidence

- [ ] m1.md exists
- [ ] m1-ci-evidence.md exists
- [ ] m1-attestation.md exists

## CI Evidence

- [ ] Workflow run exists
- [ ] Workflow URL recorded
- [ ] Workflow success verified
- [ ] Tested SHA recorded
- [ ] SHA exists in repository history

## Documentation Integrity

- [ ] No TBD values
- [ ] No TODO values
- [ ] No placeholder URLs
- [ ] No placeholder SHAs
- [ ] No unsupported claims
- [ ] No contradictory statuses

## Governance

- [ ] Attestation completed
- [ ] Attestation references CI run
- [ ] Attestation references tested SHA
- [ ] Attestation committed

---

## Status Determination

### BLOCKED

Use when:

- CI URL missing
- SHA missing
- placeholders remain
- evidence missing

### CI PASS

Use when:

- workflow verified
- URL verified
- SHA verified
- evidence committed

### COMPLETE

Use when:

- CI PASS achieved
- attestation completed
- audit checklist complete
- no unsupported claims remain