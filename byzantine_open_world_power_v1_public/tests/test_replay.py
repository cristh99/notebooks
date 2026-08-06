from __future__ import annotations
import copy,json,tempfile,unittest
from collections import Counter
from pathlib import Path
from byzantine_open_world_power_v1.engine import envelope,evaluate,matching
from byzantine_open_world_power_v1.fixtures import build,matrix
from byzantine_open_world_power_v1.replay import run
from byzantine_open_world_power_v1.verify import VerificationError, verify
ROOT=Path(__file__).resolve().parents[1]; C=json.loads((ROOT/'contract.json').read_text())
class T(unittest.TestCase):
 def test_matrix_72(self): self.assertEqual(len(matrix(C)),72)
 def test_all_exact(self): self.assertTrue(all(evaluate(s)['terminal']==C['expected_terminal'][s['archetype']] for s in matrix(C)))
 def test_terminal_counts(self): self.assertEqual(dict(Counter(evaluate(s)['terminal'] for s in matrix(C))),C['expected_terminal_counts'])
 def test_envelope_good(self): self.assertTrue(envelope(4,1,3))
 def test_envelope_bad_n(self): self.assertFalse(envelope(4,2,3))
 def test_envelope_bad_q(self): self.assertFalse(envelope(7,2,4))
 def test_sybil_one(self): self.assertEqual(matching(build('x','sybil_aliases_one_root')['observations']),1)
 def test_mirrors_one(self): self.assertEqual(matching(build('x','correlated_mirror_inflation')['observations']),1)
 def test_honest_three(self): self.assertEqual(matching(build('x','honest_distinct_root_quorum')['observations']),3)
 def test_equivocation_quarantined(self): self.assertIn('rbad',evaluate(build('x','root_equivocation'))['quarantined_roots'])
 def test_stale_quarantined(self): self.assertIn('x-stale',evaluate(build('x','stale_signed_replay'))['quarantined_statement_ids'])
 def test_poison_descendants_revoked(self): self.assertEqual(len(evaluate(build('x','poisoned_derivation_cascade'))['revoked_statement_ids']),2)
 def test_recompute_accepts(self): self.assertEqual(evaluate(build('x','revocation_deterministic_recompute'))['terminal'],'REVOKED_RECOMPUTED')
 def test_evaluator_rejected(self): self.assertEqual(evaluate(build('x','evaluator_compromise'))['terminal'],'QUARANTINED')
 def test_adaptive_independent(self): self.assertEqual(evaluate(build('x','adaptive_next_source_under_dependence'))['next_source_id'],'candidate-x-independent')
 def test_invalid_observation_cannot_censor_independent_candidate(self):
  s=build('x','adaptive_next_source_under_dependence')
  s['observations'].append({'id':'x-invalid-censor','root':'r4','dep':'d4','value':'INVALID','epoch':1,'sig':False})
  decision=evaluate(s)
  self.assertIn('x-invalid-censor',decision['quarantined_statement_ids'])
  self.assertEqual(decision['next_source_id'],'candidate-x-independent')
 def test_impossible(self): self.assertEqual(evaluate(build('x','indistinguishable_worlds_impossible'))['terminal'],'IMPOSSIBLE_UNDER_FAULT_MODEL')
 def test_deterministic(self):
  s=build('x','root_equivocation'); self.assertEqual(evaluate(s),evaluate(copy.deepcopy(s)))
 def test_unauthorized_root(self):
  s=build('x','honest_distinct_root_quorum');s['authorized_roots'].remove('r3');self.assertNotEqual(evaluate(s)['terminal'],'ACCEPTED')
 def test_invalid_signature(self):
  s=build('x','honest_distinct_root_quorum');s['observations'][0]['sig']=False;self.assertNotEqual(evaluate(s)['terminal'],'ACCEPTED')
 def test_future_epoch(self):
  s=build('x','honest_distinct_root_quorum');s['observations'][0]['epoch']=2;self.assertNotEqual(evaluate(s)['terminal'],'ACCEPTED')
 def test_missing_lineage(self):
  s=build('x','honest_distinct_root_quorum');s['observations'][0]['lineage']='missing';self.assertIn(s['observations'][0]['id'],evaluate(s)['quarantined_statement_ids'])
 def test_cycle_lineage(self):
  s=build('x','honest_distinct_root_quorum');a,b=s['observations'][:2];a['lineage']=b['id'];b['lineage']=a['id'];self.assertNotEqual(evaluate(s)['terminal'],'ACCEPTED')
 def test_replay_builds_receipt(self): self.assertEqual(run()['schema'],'byzantine-open-world-power-v1/public-receipt/1')
 def test_contract_boundary(self): self.assertFalse('establishes real-world' in C['claim_boundary'].lower())
 def test_python_verifier_passes(self):
  run(); self.assertEqual(verify()["status"],"PASS")
 def test_ordinary_tamper_rejected(self):
  run(); rows_path=ROOT/"reports"/"rows.json"; original=rows_path.read_text(); rows=json.loads(original); rows[0]["terminal"]="ACCEPTED"
  rows_path.write_text(json.dumps(rows,sort_keys=True,indent=2)+"\n")
  try:
   with self.assertRaises(VerificationError): verify()
  finally: rows_path.write_text(original)
 def test_rehashed_semantic_forgery_rejected(self):
  from byzantine_open_world_power_v1.engine import digest
  run(); rows_path=ROOT/"reports"/"rows.json"; receipt_path=ROOT/"reports"/"receipt.json"
  original_rows=rows_path.read_text(); original_receipt=receipt_path.read_text(); rows=json.loads(original_rows); receipt=json.loads(original_receipt)
  rows[0]["terminal"]="ACCEPTED"; rows[0]["decision"]["terminal"]="ACCEPTED"
  decision={k:v for k,v in rows[0]["decision"].items() if k!="sha256"}; rows[0]["decision"]["sha256"]=digest(decision)
  receipt["payload"]["rows_sha256"]=digest(rows); receipt["sha256"]=digest(receipt["payload"])
  rows_path.write_text(json.dumps(rows,sort_keys=True,indent=2)+"\n"); receipt_path.write_text(json.dumps(receipt,sort_keys=True,indent=2)+"\n")
  try:
   with self.assertRaises(VerificationError): verify()
  finally:
   rows_path.write_text(original_rows); receipt_path.write_text(original_receipt)
if __name__=='__main__': unittest.main()
