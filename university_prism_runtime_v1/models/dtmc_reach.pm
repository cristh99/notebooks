dtmc

module reachability
  s : [0..2] init 0;

  [] s=0 -> 0.4:(s'=1) + 0.6:(s'=2);
  [] s=1 -> (s'=1);
  [] s=2 -> (s'=2);
endmodule

label "goal" = s=1;
