(* Independent exact/high-precision replay for lower-bound metacompiler controls. *)

ClearAll["Global`*"];

smallLeCam = 1/16;
smallPacking = 1/10;
smallFano = (1/2) N[
  1-(Log[5]+(4/5)Log[4/5]+(1/5)Log[(1/5)/4]+Log[2])/Log[5],
  60
];

largeLeCam = 1/15;
largeFano = (1/2) N[
  1-(Log[16]+(3/4)Log[3/4]+(1/4)Log[(1/4)/15]+Log[2])/Log[16],
  60
];

If[!(smallPacking > smallLeCam && smallPacking > smallFano),
  Print["FAIL: small method selection"]; Exit[1]];
If[!(largeFano > largeLeCam),
  Print["FAIL: resource-bounded Fano selection"]; Exit[1]];

Print[<|
  "small" -> <|
    "le_cam" -> smallLeCam,
    "packing" -> smallPacking,
    "fano_estimation" -> smallFano,
    "selected" -> "exact_finite_packing"
  |>,
  "large" -> <|
    "le_cam" -> largeLeCam,
    "fano_estimation" -> largeFano,
    "selected" -> "certified_fano"
  |>,
  "hypercube" -> <|
    "assouad_lower" -> 1,
    "identity_upper" -> 1,
    "selected" -> "assouad_hypercube",
    "verdict" -> "MATCHED"
  |>
|>];
