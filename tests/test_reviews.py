import unittest
from database.reviews import fingerprint,apply_decision

class ReviewTests(unittest.TestCase):
    def test_approval_is_bound_to_content_and_candidates(self):
        p=dict(source_id='1',body='post',issues=[],duplicate_candidates=[{'id':'2','content_sha256':'a'}],review_status='REVIEW',content_sha256='a')
        r=dict(fingerprint=fingerprint(p),decision='READY',reason='Reviewed originals')
        self.assertEqual(apply_decision(p,r)['review_status'],'DRAFT')
        for change in ({'content_sha256':'b'},{'body':'changed'},{'duplicate_candidates':[]}):
            self.assertEqual(apply_decision(dict(p,**change),r)['review_status'],'REVIEW')
        bad=dict(p,issues=['salary unclear'])
        r['fingerprint']=fingerprint(bad)
        self.assertEqual(apply_decision(bad,r)['review_status'],'REVIEW')
    def test_duplicate_and_needs_info_are_held(self):
        p=dict(body='post',issues=[],review_status='DRAFT')
        for decision in ('DUPLICATE','NEEDS_INFO'):
            r=dict(fingerprint=fingerprint(p),decision=decision,reason='Evidence')
            self.assertEqual(apply_decision(p,r)['review_status'],decision)
