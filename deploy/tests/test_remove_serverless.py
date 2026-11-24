from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('retirement',Path(__file__).resolve().parents[1]/'remove_serverless.py')
retirement=importlib.util.module_from_spec(spec);spec.loader.exec_module(retirement)


class FakeAPI:
    def __init__(self):
        self.calls=[]
        self.endpoint={'id':retirement.ENDPOINT,'name':'owned-current','registry':'registry-owned',
            'type':'QUEUE','mounts':{'network':[],'global':[]},'workers':{'min':0,'max':0},
            'env':{'PASSWORD':'private-secret'}}
        self.templates=[{'id':'template-one','name':'owned-current'},{'id':'template-two','name':'owned-old'}]
        self.registry={'id':'registry-owned','name':'owned-registry'};self.pods=[];self.other_endpoints=[]
        self.allocated=False;self.ignore_delete=False

    def call(self,path,method='GET',body=None,missing_ok=False):
        self.calls.append((path,method,deepcopy(body)))
        route='/v2/serverless/'+retirement.ENDPOINT
        if path==route:
            if method=='PATCH':self.endpoint['workers'].update(body['workers']);self.allocated=False
            if method=='DELETE' and not self.ignore_delete:self.endpoint=None
            return deepcopy(self.endpoint)
        if path==route+'/workers':
            count=int(self.allocated)
            return {'workers':[] if not count else [{'id':'old-worker'}],
                    'summary':{key:count if key in ('running','total') else 0 for key in
                               ('running','idle','initializing','throttled','unhealthy','total')}}
        if path=='/v2/templates':return {'templates':deepcopy(self.templates),'pagination':{'hasNextPage':False,'nextCursor':None}}
        if path=='/v2/serverless':return {'endpoints':deepcopy(self.other_endpoints),'pagination':{'hasNextPage':False,'nextCursor':None}}
        if path=='/v2/pods':return {'pods':deepcopy(self.pods),'pagination':{'hasNextPage':False,'nextCursor':None}}
        if path.startswith('/v2/templates/'):
            rid=path.rsplit('/',1)[1]
            if method=='DELETE':self.templates=[row for row in self.templates if row['id']!=rid]
            return deepcopy(next((row for row in self.templates if row['id']==rid),None))
        if path=='/v2/registries/registry-owned':
            if method=='DELETE':self.registry=None
            return deepcopy(self.registry)
        raise AssertionError('Unexpected provider route')


class RetirementTests(unittest.TestCase):
    def test_unknown_inventory_completeness_never_becomes_an_empty_account(self):
        from unittest.mock import Mock
        api=Mock();api.call.return_value={'pods':[]}
        with self.assertRaises(retirement.CleanupError):retirement.rows(api,'/v2/pods','pods')

    def state(self):
        return {'endpoint_id':retirement.ENDPOINT,'endpoint_name':'owned-current','endpoint_name_history':[{'name':'owned-old'}],
                'registry_id':'registry-owned','registry_name':'owned-registry'}

    def test_preview_never_writes_and_saves_only_scoped_metadata(self):
        api=FakeAPI()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'report.json';report=retirement.retire(api,self.state(),path)
            self.assertEqual(json.loads(path.read_text()),report)
        self.assertEqual(report['result'],'PREVIEW');self.assertTrue(all(method=='GET' for _,method,_ in api.calls))
        self.assertNotIn('private-secret',json.dumps(report))

    def test_apply_deletes_only_owned_resources_and_rechecks_absence(self):
        api=FakeAPI();api.endpoint['workers']={'min':1,'max':1};api.allocated=True
        with tempfile.TemporaryDirectory() as folder:report=retirement.retire(api,self.state(),Path(folder)/'report.json',True)
        self.assertEqual(report['result'],'PASS');self.assertTrue(report['endpoint_absent_verified'])
        self.assertEqual(len(report['deleted']),4);self.assertFalse(report['storage_deleted'])
        self.assertEqual([body for _,method,body in api.calls if method=='PATCH'],[{'workers':{'min':0,'max':0}}])
        for index,(path,method,_) in enumerate(api.calls):
            if method=='DELETE':self.assertEqual(api.calls[index+1][:2],(path,'GET'))
        self.assertFalse(any('/volumes' in path or '/run' in path for path,_,_ in api.calls))

    def test_changed_identity_or_persistent_mount_blocks_all_writes(self):
        for key,value in [('id','foreign-id'),('name','foreign-name'),('registry','foreign-registry'),
                          ('mounts',{'network':[{'id':'keep-models'}],'global':[]})]:
            api=FakeAPI();api.endpoint[key]=value
            with tempfile.TemporaryDirectory() as folder,self.assertRaises(retirement.CleanupError):
                retirement.retire(api,self.state(),Path(folder)/'report.json',True)
            self.assertTrue(all(method=='GET' for _,method,_ in api.calls))

    def test_unrelated_resources_are_preserved_and_registry_is_not_cascaded(self):
        api=FakeAPI();api.templates.append({'id':'foreign-template','name':'unrelated'})
        api.other_endpoints=[{'id':'foreign-endpoint','name':'unrelated'}]
        with tempfile.TemporaryDirectory() as folder:report=retirement.retire(api,self.state(),Path(folder)/'report.json',True)
        self.assertEqual(report['result'],'PARTIAL');self.assertIsNotNone(api.registry)
        self.assertEqual(api.templates,[{'id':'foreign-template','name':'unrelated'}])
        self.assertFalse(any('foreign' in path and method!='GET' for path,method,_ in api.calls))

    def test_template_in_use_is_not_deleted(self):
        api=FakeAPI();api.pods=[{'id':'pod-keep','templateId':'template-one'}]
        with tempfile.TemporaryDirectory() as folder,self.assertRaises(retirement.CleanupError):
            retirement.retire(api,self.state(),Path(folder)/'report.json',True)
        self.assertEqual(len(api.templates),2);self.assertIsNotNone(api.registry)

    def test_unverified_delete_stops_and_keeps_pending_action(self):
        api=FakeAPI();api.ignore_delete=True
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'report.json'
            with self.assertRaises(retirement.CleanupError):retirement.retire(api,self.state(),path,True)
            report=json.loads(path.read_text())
        self.assertEqual(report['pending_action']['kind'],'endpoint');self.assertEqual(len(api.templates),2)

    def test_repeated_cleanup_verifies_absence_and_preserves_deletion_audit(self):
        api=FakeAPI()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'report.json';first=retirement.retire(api,self.state(),path,True)
            api.calls.clear();second=retirement.retire(api,self.state(),path,True)
        self.assertEqual(second['deleted'],first['deleted']);self.assertEqual(second['result'],'PASS')
        self.assertTrue(all(method=='GET' for _,method,_ in api.calls))
