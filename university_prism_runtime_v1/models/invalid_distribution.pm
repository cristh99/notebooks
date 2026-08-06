dtmc

module invalid_distribution
  s : [0..1] init 0;

  [] s=0 -> 0.8:(s'=0) + 0.8:(s'=1);
  [] s=1 -> (s'=1);
endmodule
