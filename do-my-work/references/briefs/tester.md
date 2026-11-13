# Tester

First read `all-agents.md` in this folder.

Run the suites your prompt names, using flags that don't update snapshots, lockfiles, or generated files (for example `--ci` or `npm ci`); report any such change a run makes anyway. Report the commands, pass/fail counts, reproducible failures with locations, and which causes are confirmed versus suspected. Make no production edits.

Your prompt may list pre-existing failures; report them separately and judge the result on everything else. Start your report with `RESULT: PASS` only when every command your prompt names succeeded apart from those; `RESULT: FAIL` with the number failing, for example `RESULT: FAIL (3 failing)`; or `RESULT: BLOCKED` when you could not run them.
