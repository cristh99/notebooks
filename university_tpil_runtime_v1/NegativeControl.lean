import Std

-- This file must fail kernel checking.
example : False := by
  exact True.intro
