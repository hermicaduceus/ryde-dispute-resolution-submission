"""W20 wizard draft preservation/reset behaviour driven through existing DOM seam."""
import unittest
from tests.w20_support import SCOPES, drive

def filled(rows):
    ops=[['value','description','Keep description 😀'],['value','claim-amount','12.34']]
    for i,(key,_,kind) in enumerate(rows):
        ops += [['open',key,'Open '+key+' 😀']] if kind=='open' else [['choice',key,'Yes' if i%2 else 'No'],['explain',key,'Explanation '+key+' 😀']]
    return ops
class BackState(unittest.TestCase):
    def test_repeated_back_continue_preserves_trip_all_controls_and_submission(self):
        for role,category,trip,rows in SCOPES:
            with self.subTest(role=role,category=category):
                ops=filled(rows)+[['snapshot']]
                for _ in range(3):ops += [['id','details-back'],['snapshot'],['trip',0],['id','trip-next'],['snapshot']]
                out=drive(role,0 if category=='route_deviation' else 1,ops+[['submit']])
                initial=out['snapshots'][0]
                self.assertEqual([False,False,True],initial['visible'])
                for i in (1,3,5):
                    back=out['snapshots'][i];self.assertEqual([False,True,False],back['visible'])
                    self.assertEqual(initial['trip'],back['trip']);self.assertFalse(back['disabled'])
                for i in (2,4,6):self.assertEqual(initial,out['snapshots'][i])
                posts=[c for c in out['calls'] if c['method']=='POST'];self.assertEqual(1,len(posts))
                expected={key:'Open '+key+' 😀' if kind=='open' else ('Yes' if i%2 else 'No')+' - Explanation '+key+' 😀' for i,(key,_,kind) in enumerate(rows)}
                self.assertEqual(expected,posts[0]['body']['answers'])
                self.assertEqual('A',posts[0]['body']['trip_id'])
                self.assertEqual('Keep description 😀',posts[0]['body']['description']);self.assertEqual(12.34,posts[0]['body']['claim_amount_sgd'])
    def test_back_continue_without_trip_reclick_preserves_submission(self):
        for role,category,trip,rows in SCOPES:
            with self.subTest(role=role,category=category):
                ops=filled(rows)+[['snapshot']]
                for _ in range(3):ops += [['id','details-back'],['id','trip-next'],['snapshot']]
                out=drive(role,0 if category=='route_deviation' else 1,ops+[['submit']])
                initial=out['snapshots'][0]
                for snapshot in out['snapshots'][1:]:self.assertEqual(initial,snapshot)
                posts=[c for c in out['calls'] if c['method']=='POST']
                self.assertEqual(1,len(posts));self.assertEqual('A',posts[0]['body']['trip_id'])
                expected={key:'Open '+key+' 😀' if kind=='open' else ('Yes' if i%2 else 'No')+' - Explanation '+key+' 😀' for i,(key,_,kind) in enumerate(rows)}
                self.assertEqual(expected,posts[0]['body']['answers'])
                self.assertEqual('Keep description 😀',posts[0]['body']['description'])
                self.assertEqual(12.34,posts[0]['body']['claim_amount_sgd'])
    def test_different_trip_clears_question_answers(self):
        for role,category,trip,rows in SCOPES:
            out=drive(role,0 if category=='route_deviation' else 1,filled(rows)+[['id','details-back'],['trip',1],['id','trip-next']])
            self.assert_clean(out['final']['rows'])
    def test_category_switch_clears_even_shared_safety(self):
        for role,category,trip,rows in SCOPES:
            other=1 if category=='route_deviation' else 0
            out=drive(role,0 if category=='route_deviation' else 1,filled(rows)+[['id','details-back'],['id','trip-back'],['category',other],['id','category-next'],['trip',0],['id','trip-next']])
            self.assert_clean(out['final']['rows'])
    def test_category_roundtrip_does_not_restore_old_answers(self):
        for role,category,trip,rows in SCOPES:
            index=0 if category=='route_deviation' else 1
            out=drive(role,index,filled(rows)+[['id','details-back'],['id','trip-back'],['category',1-index],['category',index],['id','category-next'],['trip',0],['id','trip-next']])
            self.assert_clean(out['final']['rows'])
    def assert_clean(self,rows):
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual('',row['value'])
            if row['choices']:
                self.assertEqual('',row['explanation']);self.assertTrue(row['explanationHidden'])
                self.assertTrue(all(not c['selected'] and c['pressed']=='false' for c in row['choices']))
    def test_switch_choice_clears_old_explanation_same_choice_keeps(self):
        for role,category,trip,rows in SCOPES:
            key=next(k for k,_,t in rows if t=='yes_no')
            out=drive(role,0 if category=='route_deviation' else 1,[['choice',key,'Yes'],['explain',key,'Keep'],['choice',key,'Yes'],['snapshot'],['choice',key,'No'],['snapshot']])
            a,b=[next(r for r in s['rows'] if r['key']==key) for s in out['snapshots']]
            self.assertEqual('Keep',a['explanation']);self.assertEqual('',b['explanation'])
            self.assertEqual([False,True],[c['selected'] for c in b['choices']]);self.assertEqual(['false','true'],[c['pressed'] for c in b['choices']])
