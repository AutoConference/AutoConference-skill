# TorchRL example

`trajectory.json` contains synthetic transitions for checking episode boundaries.
It includes a true terminal state and a time-limit truncation. It is not a policy
benchmark. Copy its data into the paper workspace; request paths are relative to
that workspace.

- **25:** validate aligned arrays and round-trip transitions through a TorchRL
  replay buffer.
- **75:** compute generalized advantage estimates and value targets.
- **100:** additionally compare against an independent scalar recurrence and
  sample a seeded replay minibatch for downstream training code.

`done` is true at every episode boundary. `terminated` is true only when the
state is terminal: it disables bootstrapping. A time-limit truncation has
`done=true`, `terminated=false` and retains `next_values` for bootstrapping.
Keep transitions in time order. Supply `next_values` for each transition from the
actual next observation, including the final observation before an environment
reset. Inputs are limited to 10,000 transitions.

Use the original experiment's trajectories and value predictions for research.
This adapter prepares training data with [TorchRL](https://github.com/pytorch/rl);
it does not train a policy or measure policy improvement.
