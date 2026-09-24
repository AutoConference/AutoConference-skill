# Compute env ledger

Written in the format of `shared-references/compute-env-contract.md` §3 so ARIS
compute skills (`/run-experiment`, `/experiment-bridge`, `/experiment-queue`)
read the real resource shape instead of assuming a normal GPU box. The `tier`
line is the one that matters: this is a 2-core, 8 GiB container, not a
workstation, and every cost estimate has to come off those numbers.

### env: example@a100-2c8g
how: system conda at /opt/conda (no venv; pip --user for additions)
tier: {cpus: 2, mem_gib: 8, gpus: 1}
gpus: 1x NVIDIA A100-SXM4-80GB, CUDA 12.8, driver 570.211.01, idle
weights: HF_HOME=$HOME/.cache/huggingface (1.8 PB NFS, no purge window)
validated: 2026-08-26 (witness clean: torch 2.11.0+cu128, cuda available, 7B loads)
stack: python 3.13.14 / torch 2.11.0+cu128 / transformers 5.15.1 / accelerate 1.14.0
       also numpy scipy pandas matplotlib pypdf jq pdflatex xelatex pandoc
absent: node npm docker cron tmux uv gh pdftotext vllm

gotcha: cgroup is the wall, not the host. `nproc` reports 24 and `free` reports
  226 GiB, but memory.max=8 GiB and cpu.max=2. Trust the tier line.
gotcha: a 7B bf16 model loads with host RSS peaking at 7.23 GiB against the
  8 GiB cap. It works, with no headroom. Two models resident is an OOM kill,
  and anything above 7B will not load at all.
gotcha: batched greedy generation measured at 3003.8 tok/s at batch 64 (16.3 GiB
  GPU); 751.6 at batch 16; 45.6 single-stream. Cost every sweep off the batched
  number -- the 66x gap is the difference between a 20-minute run and a day.
gotcha: anything that accumulates host-side tensors per token (output_scores over
  a ~150k vocab) forces batch=1 and therefore the 45.6 tok/s path. This is the
  failure that looks fine in GPU memory and still blows the budget.
gotcha: attention-only microbenchmarks need no weights at all -- host RSS 686 MiB.
  Cheapest honest use of this GPU (sdpa causal: 1.06 ms @1k, 3.17 @8k, 44.4 @32k).
gotcha: no node, so Codex MCP cannot be installed and the cross-model reviewer is
  unavailable. Deterministic verifiers stand in; see research/scripts/check_reproduction.py, which
  emits PAPER_CLAIM_AUDIT.json with reviewer_model "deterministic:repro-gate".
gotcha: $HOME is NFS with very slow metadata -- `du` over it hangs. Do not write
  tens of thousands of small files.
gotcha: no cron and no systemd. Unattended loops are flock + nohup (pipeline/run-heartbeat.sh).

detail sheet: ../machine.json (same numbers, machine-readable)
