# OpenMM example

Copy these files into a paper's experiment workspace before running the extension.
`system.json` is a synthetic two-particle harmonic bond with an explicit force
constant and displaced initial separation. It is a small integration fixture.

At 25 the adapter evaluates energy and forces. At 75 it generates a reference
trajectory. At 100 it also checks conservation and repeats the trajectory with
half the integration time step. It does not evaluate a learned propagator.

For a prepared local molecule, replace the `system` input with `pdb`. That path
must stay inside the workspace. The PDB must already contain the atoms needed by
OpenMM's bundled Amber14/TIP3P parameters, and have 2 to 256 atoms. No force-field
file, model, or dataset is fetched by the adapter. Its integrator is Verlet (NVE).

The request accepts these `params`:

- `steps`: 1–5000, default 100, used at 75 and 100.
- `sample_every`: 1–`steps`, default `ceil(steps/100)`; at most 500 sampled intervals.
- `timestep_ps`: 0.00001–0.004, default 0.001.
- `initial_temperature_k`: 0–1000, default 0; a positive value generates seeded
  initial velocities. This does not add a thermostat. Zero uses the supplied
  JSON velocities, or zero velocities when none are supplied.
- `seed`: 1–2147483647, default 17.

At most 60000 position coordinates are retained; increase `sample_every` for
a larger molecule. The 100-level repeat uses twice as many steps at half the
step size, keeping physical duration fixed. Energy and momentum drift are
reported for the NVE trajectory. Scientific comparisons must match force
field, integrator, time step and sampling interval; this adapter does not
substitute for a Langevin reference run.
