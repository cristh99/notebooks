#!/usr/bin/env python3
import json
from pathlib import Path
expected=json.loads(Path('expected_receipt.json').read_text())
actual=json.loads(Path('output/receipt.json').read_text())
if actual != expected:
    raise SystemExit('receipt mismatch')
print(json.dumps({'status':'PASS','receipt_match':True,'data_sha256':actual['data_sha256'],'config_sha256':actual['config_sha256']},sort_keys=True))
