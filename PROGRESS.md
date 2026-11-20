# Adaptive clearing loop

- Goal: finish the saved Stormtrooper CAM session with verified adaptive coverage, then improve cutting and slicing time without relaxing engagement or clearance.
- 0.1.70 read-only baseline: 200.74 s slicing, 229.0 s Preview for the partial first depth, 255 peels, 9 entries, 342.807 mm² remaining at Z−2; hit the path-point guard. No rapid-contact finding. Partial times are not comparable to a completed job.
- 0.1.71 caches rounded finish geometry per component while rechecking live stock for each trial. Targeted regression passed. The saved-session rerun is logging to `/tmp/gcp-adaptive-cache-RbRmvn.log` (local temporary file).
- Check with `python -X utf8 tools/check_adaptive_session.py`. It reads the current single-model CAM session, does not change settings or export, and exits nonzero if the output is debug-only or has a rapid/tab contact finding.
- Next: inspect cached-run coverage and timing; then distinguish point-budget exhaustion from real residual-shape stalls. Preserve the current engagement setting, depth, and tool when comparing. Do not treat the partial program as production G-code.
