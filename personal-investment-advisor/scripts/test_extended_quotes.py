"""Extended-session price/time contract and offline end-to-end regressions."""
import copy
import io
import json
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import daily_sync
import rebalance_weights
import yf
from quote_evidence_contract import canonical_json_binding, select_quote_observation
from market_calendar import load_table


class ExtendedQuoteTests(unittest.TestCase):
    def info(self, state='PRE'):
        now = time.time()
        return {'symbol':'GOOG','currency':'USD','exchange':'NMS','quoteType':'EQUITY',
                'exchangeTimezoneName':'America/New_York','marketState':state,
                'regularMarketPrice':100.0,'regularMarketTime':now-3*86400,
                'preMarketPrice':110.125,'preMarketTime':now-60,
                'postMarketPrice':111.375,'postMarketTime':now-30}

    def contract(self, info, now=None):
        return yf._quote_contract_report({'symbol':'GOOG','info':info},
                                        {'symbol':'GOOG','market':'US','asset_type':'stock','currency':'USD'},
                                        now_epoch=time.time() if now is None else now,
                                        max_quote_age_seconds=yf.MAX_QUOTE_AGE_SECONDS)

    def test_pre_and_post_price_and_time_are_paired_without_mutation(self):
        for state, session, price, timestamp in [
            ('PRE','PRE','preMarketPrice','preMarketTime'),
            ('PREPRE','PRE','preMarketPrice','preMarketTime'),
            ('POST','POST','postMarketPrice','postMarketTime'),
            ('POSTPOST','POST','postMarketPrice','postMarketTime')]:
            with self.subTest(state=state):
                info=self.info(state); original=copy.deepcopy(info)
                selected=select_quote_observation(info)
                self.assertEqual(selected['session'],session)
                self.assertEqual((selected['price'],selected['epoch']),(info[price],info[timestamp]))
                self.assertEqual(info,original)
                self.assertEqual(self.contract(info)['status'],'matched')
                self.assertEqual(yf.select_portfolio_current_price(None,info),info[price])
                self.assertEqual(daily_sync._record_price({'info':info}),info[price])

    def test_regular_ignores_extended_values(self):
        info=self.info('REGULAR'); info['regularMarketTime']=time.time()-60
        self.assertEqual(select_quote_observation(info)['price'],100.0)
        self.assertEqual(self.contract(info)['status'],'matched')

    def test_closed_chooses_latest_timestamped_pair(self):
        info=self.info('CLOSED')
        self.assertEqual(select_quote_observation(info)['session'],'POST')
        info['regularMarketTime']=time.time()-10
        self.assertEqual(select_quote_observation(info)['session'],'REGULAR')

    def test_missing_extended_pair_keeps_explicit_regular_fallback(self):
        info=self.info();info.pop('preMarketPrice');info.pop('preMarketTime')
        info['regularMarketTime']=time.time()-60
        c=self.contract(info)
        self.assertEqual(c['status'],'matched')
        self.assertIn('extended_quote_unavailable.regular_pair_used',c['warnings'])
        self.assertEqual(c['quote_observation']['session'],'REGULAR')
        info['regularMarketTime']=time.time()-3*86400
        self.assertIn('stale_info.regularMarketTime',self.contract(info)['errors'])

    def test_partial_extended_pair_never_borrows_regular_fields(self):
        for missing in ['preMarketPrice','preMarketTime']:
            info=self.info();info.pop(missing)
            info['regularMarketTime']=time.time()-60
            c=self.contract(info)
            self.assertEqual(c['status'],'failed')
            self.assertEqual(c['quote_observation']['session'],'PRE')

    def test_stale_selected_quote_never_uses_fresh_regular_pair(self):
        info=self.info();info['preMarketTime']=time.time()-86401
        info['regularMarketTime']=time.time()-10
        self.assertIn('stale_info.preMarketTime',self.contract(info)['errors'])

    def test_future_selected_quote_is_rejected(self):
        info=self.info('POST');info['postMarketTime']=time.time()+7200
        self.assertIn('future_info.postMarketTime',self.contract(info)['errors'])

    def test_invalid_extended_price_and_timestamp_are_rejected(self):
        for key in ['preMarketPrice','preMarketTime']:
            for value in [True,float('nan'),float('inf'),-1,None]:
                with self.subTest(key=key,value=value):
                    info=self.info();info[key]=value
                    self.assertEqual(self.contract(info)['status'],'failed')

    def test_legacy_regular_holiday_binding_ignores_newer_post_pair(self):
        calendar=load_table(Path(__file__).resolve().parent.parent/'references/market_holidays.json')
        regular=datetime(2026,1,16,21,tzinfo=timezone.utc)
        post=datetime(2026,1,17,1,tzinfo=timezone.utc)
        now=datetime(2026,1,20,3,tzinfo=timezone.utc).timestamp()
        info=self.info('CLOSED');info['regularMarketTime']=regular.timestamp()
        info.pop('preMarketPrice');info.pop('preMarketTime');info['postMarketTime']=post.timestamp()
        snapshot={'symbol':'GOOG','market_state':'CLOSED','as_of':regular.isoformat()}
        policy,extension=rebalance_weights._consumer_quote_freshness(
            snapshot,{'symbol':'GOOG','market':'US','asset_type':'stock','currency':'USD'},
            {'records':[{'symbol':'GOOG','info':info}]},now,calendar)
        self.assertTrue(extension.get('applied'),extension)
        self.assertGreater(policy['applied_max_age_seconds'],now-regular.timestamp())

    def test_extreme_selected_epoch_with_calendar_is_failed_not_exception(self):
        calendar=load_table(Path(__file__).resolve().parent.parent/'references/market_holidays.json')
        info=self.info('CLOSED');info['postMarketTime']=1e100
        result=yf._quote_contract_report({'symbol':'GOOG','info':info},
            {'symbol':'GOOG','market':'US','asset_type':'stock','currency':'USD'},
            now_epoch=time.time(),max_quote_age_seconds=yf.MAX_QUOTE_AGE_SECONDS,holiday_table=calendar)
        self.assertEqual(result['status'],'failed')
        self.assertTrue(result['errors'])

    def test_lean_info_preserves_both_extended_pairs(self):
        info=self.info()
        lean=yf.filter_info(info)
        for key in ['preMarketPrice','preMarketTime','postMarketPrice','postMarketTime']:
            self.assertEqual(lean[key],info[key])

    def test_native_quote_daily_sync_weight_round_trip(self):
        for state, selected_price in [('PRE',110.125),('POST',111.375),('CLOSED',111.375)]:
            with self.subTest(state=state), tempfile.TemporaryDirectory() as td:
                root=Path(td); positions=root/'positions.json'; quotes=root/'quotes.json'; report_path=root/'daily.json'
                payload={'base_currency':'USD','exchange_rates':{'USD':1.0},'positions':[
                    {'symbol':'GOOG','name':'Synthetic GOOG fixture','quantity':2,'avg_cost':100,'currency':'USD','market':'US','asset_type':'stock'},
                    {'symbol':'CASH_USD','name':'Synthetic cash fixture','quantity':200,'avg_cost':1,'currency':'USD','market':'CASH','asset_type':'cash'}]}
                positions.write_text(json.dumps(payload),encoding='utf-8')
                info=self.info(state); before=copy.deepcopy(info); stdout=io.StringIO()
                with patch.object(sys,'argv',['yf.py','GOOG','--daily-sync','--positions-file',str(positions)]), patch.object(yf,'configure_yfinance_cache'), patch.object(yf,'get_stock_data',return_value=(None,info,[],[])), redirect_stdout(stdout), self.assertRaises(SystemExit) as exit_context:
                    yf.main()
                self.assertEqual(exit_context.exception.code,0,stdout.getvalue())
                quotes.write_text(stdout.getvalue(),encoding='utf-8')
                daily=daily_sync.evaluate_daily_sync(positions_file=str(positions),quotes_file=str(quotes),decision_scope='research_only')
                self.assertTrue(daily['completeness']['complete'],daily.get('errors'))
                snapshot=daily['quote_snapshot'][0]
                observation=select_quote_observation(info)
                self.assertEqual(snapshot['quote_observation'],observation)
                self.assertEqual(snapshot['current_price'],selected_price)
                self.assertAlmostEqual(datetime.fromisoformat(snapshot['as_of'].replace('Z','+00:00')).timestamp(),observation['epoch'],delta=0.000001)
                report_path.write_text(json.dumps(daily),encoding='utf-8')
                weights=rebalance_weights.recalculate_all_weights(str(positions),quotes_file=str(report_path))
                self.assertEqual(weights['status'],'complete',weights.get('errors'))
                stock=next(row for row in weights['current_weights'] if row['symbol']=='GOOG')
                self.assertAlmostEqual(stock['current_weight'],2*selected_price/(2*selected_price+200),places=8)
                self.assertEqual(stock['quote']['quote_observation'],observation)
                for field in ['current_price','as_of','market_state','quote_observation','delete_observation','null_observation']:
                    tampered=copy.deepcopy(daily)
                    row=tampered['quote_snapshot'][0]
                    if field=='current_price':
                        row[field]=99.0
                    elif field=='as_of':
                        row[field]=datetime.fromtimestamp(info['regularMarketTime'],timezone.utc).isoformat()
                    elif field=='market_state':
                        row[field]='REGULAR' if state=='CLOSED' else 'CLOSED'
                    elif field=='delete_observation':
                        row.pop('quote_observation')
                        row['current_price']=99.0
                    elif field=='null_observation':
                        row['quote_observation']=None
                        row['current_price']=99.0
                    else:
                        row[field]['session']='REGULAR'
                    tampered['input_bindings']['quote_snapshot']=canonical_json_binding(tampered['quote_snapshot'])
                    report_path.write_text(json.dumps(tampered),encoding='utf-8')
                    rejected=rebalance_weights.recalculate_all_weights(str(positions),quotes_file=str(report_path))
                    self.assertNotEqual(rejected['status'],'complete',(field,rejected))
                self.assertEqual(info,before)
                self.assertEqual(json.loads(positions.read_bytes()),payload)


if __name__=='__main__':
    unittest.main()
