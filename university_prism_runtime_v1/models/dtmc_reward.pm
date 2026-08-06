dtmc

module reward_chain
  s : [0..1] init 0;

  [] s=0 -> 0.5:(s'=0) + 0.5:(s'=1);
  [] s=1 -> (s'=1);
endmodule

label "goal" = s=1;

rewards "steps"
  s=0 : 1;
endrewards
