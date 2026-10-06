"""W20 intake-only grammar and raw Unicode cap; no new app symbols required."""
import json
import unittest
from app.server import _validate_filing, _validate_reply, _HTTPError
from tests.w16_support import Server, filing, script
from tests.w20_support import SCOPES, drive

MESSAGE = 'Intake answers must be at most 2000 characters.'
class IntakeValidation(unittest.TestCase):
    def accepted(self, body):
        try:
            return _validate_filing(body)
        except _HTTPError as error:
            self.fail('valid filing refused: %s' % error)
    def test_every_key_raw_unicode_below_at_above_limit(self):
        for role, category, trip, rows in SCOPES:
            for key, _, kind in rows:
                for n in (1999,2000,2001):
                    for char in ('x','😀'):
                        value = char*n if kind=='open' else 'Yes - '+char*(n-6)
                        body=filing(category,trip,role,answers={key:value})
                        with self.subTest(role=role,category=category,key=key,n=n,char=char):
                            if n>2000:
                                with self.assertRaises(_HTTPError) as caught: _validate_filing(body)
                                self.assertEqual(400,caught.exception.status)
                                self.assertEqual(MESSAGE,str(caught.exception))
                            else:self.assertEqual({key:value},self.accepted(body)['answers'])
    def test_raw_limit_includes_trailing_whitespace(self):
        for role,category,trip,rows in SCOPES:
            for key,_,kind in rows:
                value=('x' if kind=='open' else 'Yes - x')
                value += ' '*(2001-len(value))
                with self.subTest(role=role,category=category,key=key):
                    with self.assertRaises(_HTTPError):_validate_filing(filing(category,trip,role,answers={key:value}))
    def test_exact_choice_grammar_all_choice_keys(self):
        good=['','Yes','No','Yes - details','No - 😀\nmore','Yes - \t text  ']
        bad=['Maybe - explanation','yes - explanation','No -\u2003','random prose','yes','YES','no',' Yes','No ','Yes\n','No\r\n','Yes- why','Yes: why','Yes — why','Yes -','Yes - ','No - \t\n','Yes - \u2003','Yesterday','Nope','\nYes',' ','Yes -x','No -because',' Yes - x','Maybe Yes - x','prose No - y','\tNo - y']
        for role, category, trip, rows in SCOPES:
            for key,_,kind in rows:
                if kind!='yes_no':continue
                for value in good+bad:
                    with self.subTest(role=role,category=category,key=key,value=value):
                        body=filing(category,trip,role,answers={key:value})
                        if value in bad:
                            with self.assertRaises(_HTTPError) as caught:_validate_filing(body)
                            self.assertEqual(400,caught.exception.status)
                        else:self.assertEqual({key:value},self.accepted(body)['answers'])
    def test_missing_blanks_types_and_open_prose(self):
        for role,category,trip,rows in SCOPES:
            body=filing(category,trip,role);body.pop('answers')
            self.assertEqual({},self.accepted(body)['answers'])
            for key,_,kind in rows:
                for value in ('', 'random prose' if kind=='open' else 'No'):
                    self.assertEqual({key:value},self.accepted(filing(category,trip,role,answers={key:value}))['answers'])
                for value in (None,True,2,[],{}):
                    with self.subTest(role=role,key=key,value=value):
                        with self.assertRaises(_HTTPError):_validate_filing(filing(category,trip,role,answers={key:value}))
    def test_http_refusal_precedes_llm_and_disk_and_valid_preserved(self):
        llm=script();server=Server(llm=llm);self.addCleanup(server.close)
        for role,category,trip,rows in SCOPES:
            for key,_,kind in rows:
                for value in ['x'*2001] if kind=='open' else ['Yes - '+'😀'*1995,'malformed']:
                    with self.subTest(role=role,category=category,key=key,value=value[:15]):
                        before=list(server.out.iterdir());calls=len(llm.calls)
                        status,payload=server.json('POST','/api/disputes',filing(category,trip,role,answers={key:value}))
                        self.assertEqual(400,status,payload)
                        self.assertEqual(before,list(server.out.iterdir()))
                        self.assertEqual(calls,len(llm.calls))
            valid={key:('😀'*2000 if kind=='open' else ('No - kept\nexactly' if key!='safety_concern' else '')) for key,_,kind in rows}
            status,view=server.json('POST','/api/disputes',filing(category,trip,role,answers=valid))
            self.assertEqual(200,status,view)
            self.assertEqual(valid,server.case(view['run_id'])['intake']['form_answers'])
    def test_followup_cap_not_introduced(self):
        value='😀'*2001
        try:
            replies = _validate_reply({'answers':[{'question':'q','answer':value}]},['q'])
        except _HTTPError as error:
            self.fail('valid uncapped follow-up refused: %s' % error)
        self.assertEqual([{'question':'q','answer':value}],replies)

class IntakeUI(unittest.TestCase):
    def test_no_explanation_serialized_boundaries(self):
        for role,category,trip,rows in SCOPES:
            for key,_,kind in rows:
                if kind!='yes_no':continue
                for n in (1999,2000,2001):
                    with self.subTest(role=role,category=category,key=key,n=n):
                        value='😀'*(n-5)
                        out=drive(role,0 if category=='route_deviation' else 1,[['value','description','kept'],['choice',key,'No'],['explain',key,value],['submit']])
                        posts=[c for c in out['calls'] if c['method']=='POST']
                        if n>2000:
                            self.assertEqual([],posts)
                            self.assertEqual(MESSAGE,out['error'])
                            with self.assertRaises(_HTTPError):_validate_filing(filing(category,trip,role,answers={key:'No - '+value}))
                        else:
                            self.assertEqual(1,len(posts))
                            self.assertEqual('No - '+value,posts[0]['body']['answers'][key])
                            try:_validate_filing(posts[0]['body'])
                            except _HTTPError as error:self.fail('valid No answer refused: %s' % error)
    def test_all_fields_serialized_unicode_boundaries_preserve_text(self):
        for role,category,trip,rows in SCOPES:
            for key,_,kind in rows:
                for n in (1999,2000,2001):
                    with self.subTest(role=role,category=category,key=key,n=n):
                        value='😀'*(n if kind=='open' else n-6)
                        ops=[['value','description','kept'],['value','claim-amount','2.50']]
                        ops += [['open',key,value]] if kind=='open' else [['choice',key,'Yes'],['explain',key,value]]
                        out=drive(role,0 if category=='route_deviation' else 1,ops+[['submit']])
                        posts=[c for c in out['calls'] if c['method']=='POST']
                        if n>2000:
                            self.assertEqual([],posts)
                            self.assertEqual(MESSAGE,out['error']);self.assertTrue(out['errorVisible'])
                            row=next(r for r in out['final']['rows'] if r['key']==key)
                            self.assertEqual(value,row['value'] if kind=='open' else row['explanation'])
                        else:
                            self.assertEqual(1,len(posts),out)
                            self.assertEqual(value if kind=='open' else 'Yes - '+value,posts[0]['body']['answers'][key])
                            self.assertEqual({k:('' if k!=key else posts[0]['body']['answers'][key]) for k,_,_ in rows}, posts[0]['body']['answers'])
                            try:
                                cleaned = _validate_filing(posts[0]['body'])
                            except _HTTPError as error:
                                self.fail('form-generated answer refused: %s' % error)
                            self.assertEqual(posts[0]['body']['answers'],cleaned['answers'])
