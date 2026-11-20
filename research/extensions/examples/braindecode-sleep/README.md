# Bounded sleep-stage classification

This mode connects Braindecode to the supervised sleep-stage classifier, a
separate operation from the default EEG windowing adapter. It uses the upstream
`SleepStagerChambon2018` architecture as a task-specific baseline. It is not a
claim of current SOTA and downloads no pretrained weights.

Supported input is one EEG channel sampled at 100 Hz, with 3000 samples per
30-second epoch. Five labels are fixed: 0 W, 1 N1, 2 N2, 3 N3, 4 REM. Different
rates, channels, temporal-context models and other biomedical tasks require
their own integration. The input represents physical microvolts, not already
standardized signals.

## Prepare a fixture

Copy this directory into a paper workspace and run `python make_fixture.py`
in the scientific environment. It creates synthetic sine signals with random
noise, labelled by their generated frequency. They are not human EEG and their
scores say nothing about real sleep staging.

Run `fit-25.json`, `fit-75.json` or `fit-100.json` through the existing
`science_extensions.py run --workspace <folder> --request <file>` command.
The owner's Braindecode level must permit the requested level.

- **25:** validate both development splits and check untrained forward shapes.
  No fitted model or learned accuracy is reported.
- **75:** train the specified epoch budget; keep the checkpoint with lowest
  validation NLL, with earliest ties. Export model weights, validation logits
  and a training record as JSON.
- **100:** the same training, with validation confusion/class-count checks.
  Increasing the level does not change normalization or model size.

Copy the returned `model.json` artifact to the workspace root, or put its exact
workspace-relative path in `predict-100.json`. Prediction accepts no test
labels and rejects any subject seen during training or validation. Tier 25
prediction previews one batch; tiers 75 and 100 predict the complete input.
Keep test labels in the downstream evaluator. If using temperature calibration,
fit it only on the returned validation logits, then apply it unchanged to test
logits. Compare the original baseline and relevant scientific endpoints with
the same subject split, seed schedule and training budget.

## Input and output contract

Fit inputs: `train` and `validation` NPZ files, plus a `schedule` JSON file.
Every NPZ contains:

- `x`: float32/float64 array, shape `(N, 3000)`, in microvolts.
- `subject`, `sample_id`: nonempty Unicode string arrays, one per epoch;
  sample IDs are unique and both IDs and subjects are disjoint across splits.
- `sfreq_hz`: scalar numeric 100; `unit`: scalar Unicode `uV`.
- `y`: integer array in 0..4, only for training/validation. Training must contain
  all five stages. Prediction files must omit this array.

Files use `allow_pickle=False`, contain exactly these arrays, and are bounded to
160 MiB both compressed and expanded. Each split contains 5..12000 epochs. The
adapter cannot independently verify whether caller-supplied subject identifiers
or clinical labels are correct; preserve the original data provenance.

The schedule contains `schema_version: 1`, `n_train`, `batch_size`, `model_init`
(unsigned 64-bit seed), `minibatch` (one seed per epoch) and `dropout` (one seed
per batch for each epoch). Orders use NumPy's default PCG64 generator. Supplying
the same schedule supports paired comparisons with another architecture, but
different architectures cannot have identical initial weights.

Fit parameters are `operation: sleep_fit`, `epochs` (1..30, default 20),
`batch_size` (1..128, default 128), `threads` (1..4, default 1), `learning_rate`
(1e-6..0.1, default 0.001) and `weight_decay` (0..0.1, default 0.0001).
At most 5000 optimizer updates are permitted. Training uses AdamW with fixed
betas and deterministic CPU operations. The configured subprocess timeout still
applies to the whole call; set it explicitly for a real dataset.

The model has 8 convolution channels, dropout 0.25 and no batch normalization.
Each epoch is demeaned, then divided by one pooled standard deviation computed
from training epochs only. Validation and prediction use that saved scale.
No dynamic per-epoch variance normalization is added.

Model JSON declares its fixed architecture, development subjects and training
scale, plus numeric tensors; prediction never imports caller-supplied model
code or unpickles a model. `sleep_predict` parameters accept only `operation`,
`batch_size` and `threads`. Outputs preserve sample and subject identifiers and
give raw logits with the explicit class order.

Sources:
- https://braindecode.org/stable/generated/braindecode.models.SleepStagerChambon2018.html
- https://braindecode.org/stable/auto_examples/applied_examples/plot_sleep_staging_chambon2018.html
