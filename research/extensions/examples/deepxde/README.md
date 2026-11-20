# DeepXDE example

This analytic oscillator checks the local adapter. Copy the files into a paper
workspace. It is not a benchmark showing that a PINN beats a numerical solver.

25 checks the reference solution with autodiff. 75 trains a small CPU PINN and
reports its error. 100 adds held-out residual and initial-condition checks.
The same seed and training budget are used at 75 and 100, so the extra checks
are the difference, rather than extra training time.

The other supported input is
`{"equation":"exponential_decay","duration":1,"rate":1,"initial_value":1}`.
These explicit families keep the executable input bounded. General equations
need their own reviewed adapter; equation strings are never evaluated.

The oscillator is `x'=v, v'=-omega^2*x`; its input has `initial_position`
(default 0), `initial_velocity` (1), `omega` (1) and `duration` (1). Decay is
`u'=-rate*u`, with `initial_value` (1), `rate` (1) and `duration` (1).
`duration` is 0.01–10, `omega`/`rate` are 0.01–10, and initial values are
between -100 and 100.

The request accepts these `params`:

- `iterations`: 1–2000, default 200; used at 75 and 100.
- `domain_points`: 8–512, default 32; training collocation points.
- `width`: 4–64, default 16; `hidden_layers`: 1–3, default 2.
- `learning_rate`: 0.00001–0.05, default 0.01.
- `test_points`: 8–512, default 64; `seed`: 0–2147483647, default 17.

75 and 100 use identical training when these settings match. The 100-level
midpoint checks are evaluated separately from the optimizer's loss. All runs
use PyTorch CPU, one thread and float64. Numerical error is reported directly;
the adapter has no universal accuracy threshold.
