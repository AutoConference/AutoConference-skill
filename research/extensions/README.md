# Scientific extensions

Run a scientific tool for one explicit part of your research. The agent keeps
planning, comparing baselines, analysing results and responding to reviewers
through its existing workflow. Tools run on your machine.

## Choose what a tool may do

Each tool has its own maximum level: **0 off**, **25 assist/check**, **75 main
module**, **100 complete bounded subtask**. These are responsibility levels,
not percentages of compute, probabilities or quality scores. The plan may
choose a lower level, but cannot exceed the owner's setting. A subject label
alone is not a reason to use a tool.

New kit setup initializes an automatic profile once, allowing all eight tools
up to 100. Updated existing kits also create missing configuration at their
next real ideation/planning step; experiments already past planning are unchanged.
The agent still checks the subtask and installed dependencies and may choose
a lower level or none. Existing settings, including zero levels and partial
configurations, are preserved. The commands below let the owner adjust limits. Nothing here
installs a package, downloads a model, calls a paid API or changes identity.

```sh
python3 research/extensions/science_extensions.py init
python3 research/extensions/science_extensions.py set openmm 100
python3 research/extensions/science_extensions.py list
```

These commands edit `custom/science-extensions.json`, which survives kit
updates. Its optional `python` field names the interpreter in your scientific
environment; `timeout_seconds` bounds each adapter process (default 180,
maximum 3600). Each process uses one CPU thread where supported. The runner
is not an operating-system sandbox or a total-memory limit.

## Eight fields, eight initial adapters

- **Mathematics / BoTorch:** fit observed experiments, check candidates,
  propose the next parameter vector, and test predictions on held-out data.
- **Machine learning / TorchRL:** validate supplied trajectories, compute
  advantages and value targets, and audit episode boundaries.
- **Language models / lm-evaluation-harness:** evaluate a supplied local
  model's likelihoods, choices and bounded generations on supplied prompts.
- **Agent systems / Inspect AI:** score saved predictions against targets,
  then inspect groups, costs and paired baseline outcomes. This is evaluation
  of records, not execution or benchmarking of a live agent.
- **Vision / SAM 2.1:** use point or box prompts for segmentation, or produce
  bounded automatic mask proposals from a local tiny checkpoint. Models and
  images are supplied explicitly.
- **Biomedicine / Braindecode:** make windows and check supplied EEG recordings,
  preserving amplitude and splits by default. Exponential moving normalization
  is an explicit method choice, independent of the responsibility level. Separate
  `sleep_fit` and `sleep_predict` operations train a task-specific Chambon2018
  baseline and predict held-out subjects; see `examples/braindecode-sleep/`.
- **Physics / DeepXDE:** check or solve two explicit ODE families on CPU,
  with independent residual and initial-condition checks. Other equations
  need their own adapter implementation.
- **Chemistry / OpenMM:** run a prepared small molecular system on the
  Reference CPU platform, then check conservation and step-size sensitivity.

The directory includes scientific frameworks as well as pretrained models.
Their upstream benchmark claims do not establish that our adapters improve
research. Exact input schemas, upstream links, licences and per-tool levels
are in `catalog-parts/`; runnable examples are in `examples/`.

OpenVLA-OFT, Biomni and the other surveyed projects remain candidates for
additional adapters. They are not advertised as executable integrations in
this version. In particular, OpenVLA-OFT's usual GPU requirements exceed the
8 GB test machine; SAM 2.1 provides the first executable vision integration.

## Run an example or your own data

Install only the selected tool's dependencies in a virtual environment of
your own. The runner reports missing dependencies without installing them.
For example, OpenMM needs `openmm`; the other projects' official installation
instructions are linked from the directory. Model weights have their own
requirements; the SAM example explains the explicit download separately.

`requirements-cpu-tested.txt` records the tool versions and compatibility
constraints used to test all eight examples together on Windows with Python
3.12. To recreate that CPU environment in a virtual environment, run
`python -m pip install -r research/extensions/requirements-cpu-tested.txt`.
It is not a full cross-platform lockfile. SAM 2 source and its checkpoint
are supplied separately, as described in its example.

Copy the chosen `examples/<id>/` directory to your paper workspace. The
provided datasets are synthetic connection tests. Replace them with your
study's data to run a real experiment. A `request-25.json`, `request-75.json`
or `request-100.json` names the tool, purpose, inputs and parameters.

```sh
python3 research/extensions/science_extensions.py status --workspace work/example
python3 research/extensions/science_extensions.py run --workspace work/example --request request-100.json
python3 research/extensions/science_extensions.py report --workspace work/example
```

`status` checks package availability, not whether a particular dataset or
checkpoint is valid. `run` validates the actual inputs and records failures.
Use paths relative to the workspace, with `/` separators. Inputs may be local
directories (for a model), but cannot contain symbolic links or escape the
workspace. Keep output directories separate from input directories.

The HTML report is a local, read-only view. Its level buttons show what each
level does and the runs recorded for it; they do not change the owner's setting.

## In the research pipeline

With an extension enabled:

1. Step 2 receives the enabled tools and writes
   `refine-logs/EXTENSION_PLAN.json` with `schema_version: 1` and a `requests`
   list. If no tool fits, it writes an empty list and explains why in `reason`.
2. Step 3 checks that the selected tools are allowed and their dependencies
   are available. A failed check stops this study before its experiments.
3. Step 5 prepares real inputs and calls `run-plan --workspace .`. The
   pipeline also calls it after the turn, reusing successful runs only while
   inputs, artifacts, adapter code and recorded package versions are unchanged.
   A failed or missing selected result stops the study.
4. Step 6 reads the results. Step 10 runs `replay-plan` to check the same
   inputs and versions again, alongside the existing reproducibility gate.

Each request is `{id, tier, purpose, inputs, params}`. There is at most one
request per tool in a plan. More complex sweeps belong in the original
experiment scripts and their replay manifest.

Run records include the selected tier, owner maximum, package versions,
input and adapter hashes, numeric results, artifacts, elapsed time and any
failure. Replay checks complete structured outputs and artifacts as well as
summary metrics (numeric tolerance: relative `1e-5`, absolute `1e-7`). It
does not establish statistical significance or scientific correctness.

The records live under `runs/extension-runs/`, with plan and gate summaries
under `refine-logs/`. The existing research-record builder collects and
anonymises these directories. It omits binary models, large trajectories and
other files outside its limits as before. If an extension's result supports
a paper's claim, the original experiment and aggregation replay manifest
must include that result; this runner does not bypass the evidence chain.

Share useful configuration and lessons through the existing Skills draft
and owner publication flow. A report is not automatically published.

## 中文使用说明

八类工具分别处理明确的科研子任务。四档含义是：0 不调用，25 辅助检查，
75 承担主要模块，100 完整完成指定子任务。每个工具单独配置上限，Agent
可以选择更低档位；不合适时说明原因并跳过。

新用户安装时会自动建立配置；旧用户升级后，在下一次进入选题或规划时补齐
缺少的配置文件，已进入实验阶段的论文照常继续。默认允许八类工具最高使用到
100 档；Agent 仍需检查任务是否适合、依赖是否齐全，也可以降低档位或不用。
已有配置完整保留，包括 0 档、较低上限和只配置了部分工具的情况。用
`set 工具名 档位` 调整，设为 0 即关闭该工具。配置保存在
`custom/science-extensions.json`。工具调用、环境检查、
结果记录和复现检查接在原有科研流程里。计算仍在用户自己的机器上运行。

`examples/` 是合成数据的接入示例，可以验证调用是否工作。正式研究需要
替换成真实数据并做好对照实验。网页报告由 `report` 命令生成，切换档位
只是查看对应说明和运行结果，修改配置仍用 `set` 命令。

这版不包含 Challenge 活动功能，也没有改动网站上的 Agent 设置同步。
