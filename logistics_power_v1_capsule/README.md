# Logistics Power v1 — public verification capsule

This branch is an isolated, draft-only public CI capsule for the private Logistics Power Compiler v1 source.

It reconstructs two hash-bound inputs:

1. the verified Logic Power v10 source at private head `ba10d0edc7eb20d499d0481fda2537e782b6efb2`;
2. the logistics overlay at private head `0ae44945832b18cc3b8914603b83639f03faa0d6`.

The logistics transport and source hashes are:

```text
transport SHA-256: 2e801e726ea46b3e4ff38a73421bf113921b44bfbc724e25c006b658de20844d
archive SHA-256:   4e185db5f648a56629d24d1e58d4c76926a81f15f10c3b7bd68e316a5b79aff4
manifest SHA-256:  d828a4ccfb785b98c6a3afa3077ddb68ae8e2063f0ff1c08d6955454cfd0e3ed
```

The workflow verifies source manifests, runs all 21 Python tests, rebuilds both proof-carrying certificates, replays them independently in Python and Node/BigInt, rejects altered evidence, checks exact report hashes, and emits a public receipt bound to the private and public heads.

This capsule must remain **draft and unmerged**. It exists only because the private repository currently creates failed jobs with zero executed steps and no retrievable logs before `checkout`.
