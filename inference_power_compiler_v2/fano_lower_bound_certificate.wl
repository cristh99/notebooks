(* Independent high-precision replay for the certified Fano control. *)

ClearAll["Global`*"];

classes = 16;
q = 1/4;
mutualInformation = N[
  Log[classes] + (1-q) Log[1-q] + q Log[q/(classes-1)],
  60
];
fano = N[1-(mutualInformation+Log[2])/Log[classes],60];
packing = N[fano/2,60];

If[!(197/1000 < fano < 1/4),
  Print["FAIL: Fano control interval"]; Exit[1]];
If[!(197/2000 < packing < 1/8),
  Print["FAIL: Fano packing interval"]; Exit[1]];

Print[<|
  "classes" -> classes,
  "symmetric_error" -> q,
  "mutual_information" -> mutualInformation,
  "fano_classification_lower" -> fano,
  "one_hot_estimation_lower" -> packing,
  "exact_bayes_error" -> q
|>];
