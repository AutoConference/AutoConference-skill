# Research direction (ODE–JEPA + SIGReg)

Owner mode-2 direction for AutoConference authoring.

Train and evaluate an **ODE–JEPA** world model with LeWM’s **single loss**  
`L = L_JEPA + λ·SIGReg(Z)` (λ=0.1, M=1024) on **official LeWM PushT HDF5 only**  
(`pusht_expert_train` under `$STABLEWM_HOME`). Action-conditioned ODESolve of `v_θ`.  
No synthetic trajectories for reported metrics. No JVP, no B0/B1/B2 ablations, no  
dyn-recon as primary, no stop-grad/EMA on the SIGReg+pred path.

- Primary seed: LeWM arXiv:2603.19312  
- Secondary: ODEWorld arXiv:2607.27924  
- Brief: `research/ode-jepa/PAPER_BRIEF.md`  
- Results: `research/ode-jepa/outputs/lewm_pusht/` and store `docs/ode-jepa-lewm-protocol-results.md`  
- Prior synthetic phase-1 under `outputs/phase1/` is **non-final**
