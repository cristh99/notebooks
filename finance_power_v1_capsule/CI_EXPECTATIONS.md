# CI acceptance conditions

The capsule passes only if all conditions hold:

1. the Logic Power v10 package is reconstructed from the existing public,
   private-head-bound capsule;
2. all ten Finance Power v1 tests pass;
3. all five exact cases produce replayable certificates;
4. all five negative controls produce constructive impossibility witnesses;
5. two independent report builds are byte-identical;
6. the public receipt and report artifact are emitted.
