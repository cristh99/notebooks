mdp

module scheduler_choice
  s : [0..2] init 0;

  [low]  s=0 -> 0.2:(s'=1) + 0.8:(s'=2);
  [high] s=0 -> 0.9:(s'=1) + 0.1:(s'=2);
  [] s=1 -> (s'=1);
  [] s=2 -> (s'=2);
endmodule

label "goal" = s=1;
