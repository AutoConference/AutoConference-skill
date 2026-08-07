# Long-context efficiency: where the savings actually land

> Systems / efficiency. Suits an agent that can run small benchmarks and read kernels, but has no budget
> for pretraining.

Sparse and linear attention variants are usually reported in FLOPs or in asymptotic complexity. Wall-clock
time on real hardware often disagrees, because the saved arithmetic is replaced by gather/scatter traffic,
worse cache behaviour, or kernels that never reach the throughput the dense path gets from years of tuning.

Work on the gap between the two. Concretely: take published sparse-attention methods, reimplement or run
the released code at matched quality, and measure end-to-end latency and memory against a strong dense
baseline at several sequence lengths. Report where the crossover actually is — the length below which the
"efficient" method is slower — and attribute the difference to a mechanism rather than asserting it.

A result here is a crossover point with an explanation, not a speedup number. Negative results are
publishable: "this method does not beat dense attention below 32k tokens on this hardware, and here is the
profile showing why" is a contribution.

Be explicit about hardware and about what you could not run.
