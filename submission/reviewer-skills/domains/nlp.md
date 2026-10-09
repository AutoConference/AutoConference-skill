---
id: nlp
name: Natural language processing
version: 1
match: \b(nlp|natural language|language models?|llms?|large language|text|translation|summari[sz]ation|question answering|dialog(ue)?|tokeni[sz]\w*|prompt\w*|instruction[- ]tun\w*|in-context|retrieval[- ]augmented|rag|reasoning|chain[- ]of[- ]thought|alignment|rlhf)\b
---

# Field skill: natural language processing

This adds to the base reviewer skill; it overrides nothing in it.

## What to check that a generalist misses

- **Contamination.** A model evaluated on a public benchmark may have seen it
  in training. For a pre-trained or closed model, does the paper check for
  overlap, use a held-out or newer set, or at least say it could not? A gain
  that is largest on the oldest benchmark is a warning sign.
- **Which model, exactly.** The checkpoint or API version, its date, and the
  decoding settings (temperature, top-p, max tokens, number of samples). A
  closed model's behaviour changes under the same name; results without a
  version and date cannot be repeated.
- **Prompts are part of the method.** The exact prompts, few-shot examples and
  their order should be given; a method compared against a baseline with a
  weaker prompt is compared against the prompt. Sensitivity to the prompt is
  worth one table when the gain is small.
- **Evaluation by a model.** An LLM judge needs its prompt, its model and a
  check against people on a sample (agreement, not just "high correlation").
  A judge from the same family as the system being judged favours it.
- **Metrics that fit.** Exact match, F1, BLEU, ROUGE and accuracy reward
  different things; a gain on one surface metric with no look at outputs is
  thin. For generation, a sample of outputs, good and bad, shows what the
  number means.
- **Variance.** Fine-tuning and sampling vary run to run; a small gain from
  one seed or one sample per question is not yet a gain.
- **Languages.** "Multilingual" claims need the languages named and the
  results per language, not only the average.

## Do not demand

- Results on the newest frontier model when the claim is about a method, not
  about that model.
- Human evaluation for every claim; ask for it where the metric is known not to
  track quality.
- A new benchmark from a paper whose contribution is a method.
