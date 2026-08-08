(* Independent exact replay for the multiway classification and packing compiler. *)

ClearAll["Global`*"];

classes = 5;
q = 1/5;
laws = Table[
  If[world == outcome, 1-q, q/(classes-1)],
  {world, classes}, {outcome, classes}
];

uniformBayesError = 1 - Total[Max /@ Transpose[laws]]/classes;
identityRisks = Table[1-laws[[world, world]], {world, classes}];
identityUpper = Max[identityRisks];
separationSquared = 2;
packingLower = separationSquared uniformBayesError/4;

subsetBounds = Table[
  Module[{subsets, errors, bounds},
    subsets = Subsets[Range[classes], {size}];
    errors = Table[
      1 - Total[Max /@ Transpose[laws[[subset]]]]/size,
      {subset, subsets}
    ];
    bounds = separationSquared errors/4;
    {size, DeleteDuplicates[errors], DeleteDuplicates[bounds]}
  ],
  {size, 2, classes}
];

If[uniformBayesError =!= 1/5 || identityUpper =!= 1/5,
  Print["FAIL: multiway classification replay"]; Exit[1]];
If[packingLower =!= 1/10 ||
   subsetBounds =!= {
     {2, {1/8}, {1/16}},
     {3, {1/6}, {1/12}},
     {4, {3/16}, {3/32}},
     {5, {1/5}, {1/10}}
   },
  Print["FAIL: packing progression replay"]; Exit[1]];

Print[<|
  "uniform_bayes_error" -> uniformBayesError,
  "identity_upper" -> identityUpper,
  "classification_matched" -> (uniformBayesError == identityUpper),
  "packing_lower" -> packingLower,
  "subset_bounds" -> subsetBounds
|>];
