#!/usr/bin/env python3
"""Public synthetic GitHub ↔ ChatGPT ↔ Python relay smoke test.
No confidential hardware records, no API keys, no external dependencies.
"""
from pathlib import Path
import json
import math

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"experiments"/"relay-smoke-20261117"
request=json.loads((BASE/"request.json").read_text())
assert request["test_id"]=="SIMULATED-RELAY-20261117-01"
response_path=BASE/"response.json"
if response_path.exists():
    response=json.loads(response_path.read_text())
    assert response["test_id"]==request["test_id"]
    assert response["provenance"] in ("CHATGPT_IN_ACTIVE_CONVERSATION_NOT_AUTOMATIC_TRIGGER", "CHATGPT_WORK_EVENT_TRIGGER")
    calc=response["calculation"]
    assert math.isclose(calc["pump_nominal_W"],1.5,abs_tol=1e-9)
    assert math.isclose(calc["source_max_W"],1.65,abs_tol=1e-9)
    assert calc["pump_nominal_W"]/calc["assumed_converter_efficiency"]>calc["source_max_W"]
    result={"test_id":request["test_id"],"status":"RESPONSE_VALIDATED_BY_PYTHON","reasoning_provenance":response["provenance"],"simulation":True}
else:
    result={"test_id":request["test_id"],"status":"NEEDS_CHATGPT_REASONING","simulation":True}
(BASE/"result.json").write_text(json.dumps(result,indent=2)+"\n")
print(json.dumps(result))
