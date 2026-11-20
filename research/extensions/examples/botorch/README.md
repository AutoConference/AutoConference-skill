# BoTorch example

`observations.json` is a tiny synthetic optimization problem for checking the
adapter. Its numbers are not a research result. Copy this directory's data into
the paper workspace before running a request; request paths are relative to that
workspace.

- **25:** check two candidate points already chosen by the researcher. The
  adapter returns posterior means and standard deviations and chooses no point.
- **75:** fit the observations and propose one bounded point using log expected
  improvement. The original experiment must evaluate that point.
- **100:** also check predictions against separate held-out observations. The
  held-out values do not enter fitting or candidate selection.

For real work, replace `train_x`/`train_y` with measured parameter/result pairs
and set physical parameter bounds. Set `params.maximize` to `false` for losses or
costs. `observation_noise_variance` is in squared target units. Data is limited to
256 observations and eight parameters; larger optimization problems need their
own validated adapter. The output's `data` contains the proposed point or checked
predictions; `metrics` contains summaries suitable for the run record.

This checks integration with the [BoTorch project](https://github.com/meta-pytorch/botorch).
It does not establish that Bayesian optimization improves a particular study.
