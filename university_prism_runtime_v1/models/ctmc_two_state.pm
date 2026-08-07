ctmc

module two_state_ctmc
  s : [0..1] init 0;

  [] s=0 -> 2.0:(s'=1);
  [] s=1 -> 1.0:(s'=0);
endmodule

label "up" = s=1;
