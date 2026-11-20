# Braindecode example

`eeg.json` contains two synthetic two-channel sine signals, labelled train and
test, with a phase difference and linear drift. They represent no human
subjects. Copy the files into a paper's workspace for the integration check.

25 previews the first 32 samples of the first recording. This preview must not
replace the full experimental dataset. 75 processes both recordings separately
and makes eight windows in total. 100 adds per-record quality checks. Labels
are retained, and no train/test statistics are pooled. These levels control
scope, not normalization strength; 75 and 100 produce identical signal windows.

The default `normalization=none` preserves amplitude and converts V to uV if
needed. Keep the study's original downstream preprocessing, including its
training-only fitted scale. The output has `signals`, `output_unit`,
`normalization` and `preview_only`; window arrays use the same output unit and
Braindecode's float32 precision.

Set `normalization=exponential_moving` explicitly to use causal exponential
moving standardization, without an initialization block. This removes absolute
amplitude and changes waveform shape; it can be inappropriate for studies that
retain amplitude information. Validate the method against the original baseline
on training/validation data. Do not select it just because a paper is about EEG
or because the extension level is 100. Only this mode also emits the legacy
`standardized_signals` field, and its output unit is `standardized`.

This preprocessing operation does not perform train-fold z-score fitting,
filtering, encoder inference or classifier evaluation. For explicitly training
a bounded sleep-stage model, see `../braindecode-sleep/`; choosing that operation
is separate from choosing the preprocessing responsibility level.

The signal fixture is generated as
`10*sin(2*pi*(4+channel)*sample/64 + phase) + 0.02*sample`, with phases 0 and
0.4, 128 samples per channel, 64 Hz and units of microvolts. Real input must
declare its unit and train/validation/test split explicitly.

The request accepts these `params`:

- `normalization`: `none` (default) or `exponential_moving`.
- `factor_new`: 0.00001–1, default 0.01; requires `exponential_moving`.
- `eps`: 1e-12–1, default 0.0001 in microvolts; requires `exponential_moving`.
- `window_samples`: 8–8192, default 32, no larger than any input chunk.
- `stride_samples`: 1–`window_samples`, default equal to the window size.

Each input has 1–16 recordings, 1–32 channels per recording and 16–8192
samples per channel, with at most 32768 raw values overall. Window output is
also bounded to 32768 values. The tail that cannot fill a window is reported
and dropped. Exponential moving normalization starts afresh for every chunk,
so chunk boundaries are part of that method's settings. Subject-level leakage must be checked
when constructing the input splits.
