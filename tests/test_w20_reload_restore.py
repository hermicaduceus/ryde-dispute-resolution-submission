"""W20 review F2: remembered selection outlives reload failure/invalidation."""
import unittest
from tests.w20_support import SCOPES
from tests.w20_reload_support import drive
from tests.test_w20_back_state import filled

class ReloadRestore(unittest.TestCase):
    def check_restored(self,out):
        initial,restored,details=out['snapshots']
        self.assertEqual([False,True,False],restored['visible'])
        self.assertEqual(initial['trip'],restored['trip'])
        self.assertFalse(restored['disabled'])
        self.assertEqual(initial,details)
        posts=[c for c in out['calls'] if c['method']=='POST']
        self.assertEqual(1,len(posts));self.assertEqual('A',posts[0]['body']['trip_id'])
        self.assertEqual('Keep description 😀',posts[0]['body']['description'])
        self.assertEqual(12.34,posts[0]['body']['claim_amount_sgd'])
    def test_failed_reload_retry_restores_trip_and_entire_draft(self):
        for role,category,trip,rows in SCOPES:
            with self.subTest(role=role,category=category):
                ops=filled(rows)+[['snapshot'],['trips',None],['id','details-back'],['id','trip-back'],['trips',['A','B']],['id','category-next'],['snapshot'],['id','trip-next'],['snapshot'],['submit']]
                self.check_restored(drive(role,0 if category=='route_deviation' else 1,ops))
    def test_second_back_during_pending_reload_restores_after_retry(self):
        for role,category,trip,rows in SCOPES:
            with self.subTest(role=role,category=category):
                ops=filled(rows)+[['snapshot'],['manual',True],['id','details-back'],['id','trip-back'],['manual',False],['id','category-next'],['resolve'],['snapshot'],['id','trip-next'],['snapshot'],['submit']]
                self.check_restored(drive(role,0 if category=='route_deviation' else 1,ops))
    def test_stale_list_without_trip_cannot_replace_newer_restoration(self):
        for role,category,trip,rows in SCOPES:
            with self.subTest(role=role,category=category):
                ops=filled(rows)+[['snapshot'],['manual',True],['trips',['B']],['id','details-back'],['id','trip-back'],['trips',['A','B']],['id','category-next'],['resolve',1],['resolve',0],['snapshot'],['id','trip-next'],['snapshot'],['submit']]
                self.check_restored(drive(role,0 if category=='route_deviation' else 1,ops))
    def test_current_list_without_trip_never_restores_unavailable_selection(self):
        for role,category,trip,rows in SCOPES:
            with self.subTest(role=role,category=category):
                out=drive(role,0 if category=='route_deviation' else 1,filled(rows)+[['trips',['B']],['id','details-back'],['snapshot']])
                self.assertEqual([],out['final']['trip']);self.assertTrue(out['final']['disabled'])
                self.assertEqual([False,True,False],out['final']['visible'])
