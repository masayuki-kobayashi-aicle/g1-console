## What and why

<!-- One or two sentences. Link the issue if there is one. -->

## How it was tested

- [ ] `bash tests/run_tests.sh` passes
- [ ] Tried with `python3 server.py --mock`
- [ ] Tried on a real robot (model / firmware / mounting: hanging, seated, standing):

## Safety checklist

- [ ] This change does not send motion, mode or actuator commands, or it keeps the existing guards (operator lock, clamping, liveness check, caution dialog)
- [ ] Behavior that was not tested on a real robot is marked "unverified"
- [ ] No logs, addresses, tokens or photos of a private environment are included
- [ ] If the API changed, `python3 g1console/api_spec.py` was run
