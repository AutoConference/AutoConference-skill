# LM Evaluation Harness: local causal-model evaluation

Copy the example to a paper workspace. Run `python build_tiny_fixture.py` there
to make a **randomly initialized** tiny GPT-2 model and tokenizer. This only
checks that the extension really calls the library and can reproduce outputs;
its scores say nothing about language understanding or research quality.

For a real evaluation, supply your local causal model (safetensors weights and
tokenizer) and your held-out data. No Hub or API access is needed at runtime.
Tier 25 scores reference completions. Tier 75 ranks supplied choices. Tier 100
also generates answers. This adapter uses unnormalized completion likelihood,
so account for choice-length effects when designing the evaluation.

Source: <https://github.com/EleutherAI/lm-evaluation-harness>

Install the Harness HF backend dependencies in an isolated environment
(`lm_eval[hf]`), including `accelerate`; the base `lm_eval` package alone does
not provide this model backend. Runtime evaluation remains offline.
