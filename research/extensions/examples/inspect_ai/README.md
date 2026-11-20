# Inspect AI: offline record scoring

Copy these files into a paper workspace, enable `inspect_ai` in the owner's
science-extension configuration, then run the selected request through the
extension runner. These records are synthetic wiring examples. No Agent or
model is run. The exact scorer should find two of three outputs correct; at
tier 100 it should also find one paired win net of losses versus the fixture
baseline. This is not an evaluation of AutoConference or an LLM judge.

Replace `data.json` with your recorded outputs and independent reference
answers. Tier 75 requires a group for each row. Tier 100 requires a baseline
answer to the same input for each row. Resource totals use supplied records.

Source: <https://inspect.aisi.org.uk/scorers.html>
