# Windows CI

The workflow checks formatting, runs the unit/GUI/CLI tests with Qt's offscreen
platform, and runs a real local HTTP demo without a desktop window.

Use `python -m pytest`, not the bare `pytest` entry point. The first hosted run
failed during test collection with `ModuleNotFoundError: benchdesk`: dependencies
were installed, but the console entry point did not put the repository root on
the import path. Module invocation uses the selected Python interpreter and makes
the source package importable from the checkout, without a machine-specific
`PYTHONPATH` override.

To reproduce from the repository root:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest -q
python -m benchdesk --headless --demo
```

Passing these checks does not validate the packaged executable on another PC,
code signing, or a production service. Those remain separate release checks.
