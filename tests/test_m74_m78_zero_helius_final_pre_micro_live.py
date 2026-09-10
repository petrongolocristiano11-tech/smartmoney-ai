from __future__ import annotations
from datetime import datetime, timedelta, timezone
import pytest
from backend.app.services.gen4_zero_helius_final_pre_micro_live_service import (
    M74M78Error, QUALIFIED, build_m76_consensus_signals, build_preparation_report,
    canonical_sha256, evaluate_m74_candidate, evaluate_m75_canary,
    evaluate_m76_independence, evaluate_post_discovery, sign_canary_evidence,
    sign_independence_evidence, validate_policy, validate_report,
)

def signed(obj, key='plan_payload_sha256'):
    out=dict(obj); out['integrity']={key: canonical_sha256(out)}; return out

def m72_bundle():
    plan=signed({
      'scope':'M72_CONTROLLED_NEW_WALLET_ACQUISITION_PLAN_DISARMED','state':'PREPARED_DISARMED',
      'execution_authorized':False,'execution_performed':False,
      'provider':{'maximum_requests':6,'credit_cap':600,'retries':0},
    })
    report={
      'evaluation':'PASS','scope':'M72_DEFINITIVE_DISCOVERY_ROTATION_READ_ONLY',
      'decision':{'new_wallet_discovery_required':True},
      'rotation_summary':{'qualified_pending_short_canary':0},
      'controlled_acquisition_plan':plan,
    }
    return report,plan

def candidate(wallet='A'*32, good=True):
    return {
      'wallet_address':wallet,'disposition':QUALIFIED if good else 'OBSERVE_ONLY','history_complete':True,'open_positions':0,
      'economic_analysis':{'metrics':{'closed_trade_count':100,'history_span_days':35,'net_pnl_sol':0.1,'profit_factor':1.5,'win_rate_percent':45,'maximum_drawdown_percent':10},
                           'recent_metrics':{'closed_trade_count':20,'profit_factor':1.2},
                           'checks':{'closed_sample':True,'history_span':True,'net_pnl':True,'profit_factor':True,'win_rate':True,'drawdown':True,'recent_sample':True,'recent_pnl':True,'recent_profit_factor':True,'recent_drawdown':True,'unique_tokens':True,'token_concentration':True,'positive_without_best':True,'stability_windows':True,'positive_stability_windows':True,'worst_stability_pf':True,'zero_open_positions':True},
                           'failure_reasons':[],'economic_gate_passed':True}
    }

def canary_records(start=None, attempts=20, closes=10, hours=24, reject=0):
    start=start or datetime(2026,8,1,tzinfo=timezone.utc); rows=[]
    for i in range(attempts):
      rows.append({'event_type':'ENTRY_ATTEMPT','timestamp_utc':(start+timedelta(hours=hours*i/max(1,attempts-1))).isoformat(),
                   'webhook_covered':True,'unsigned_build_success':True,'entry_rejected':i<reject,
                   'end_to_quote_ms':500,'price_impact_bps':100,'price_deterioration_bps':200,
                   'worker_failure':False,'policy_violation':False})
    for i in range(closes): rows.append({'event_type':'CLOSED_TRADE','timestamp_utc':(start+timedelta(hours=hours)).isoformat(),'worker_failure':False,'policy_violation':False})
    rows.append({'event_type':'CANARY_TERMINAL_STATE','timestamp_utc':(start+timedelta(hours=hours)).isoformat(),'open_position_count':0,'unresolved_failure_count':0,'worker_failure':False,'policy_violation':False})
    return rows

def test_preparation_report_zero_everything():
    r,p=m72_bundle(); out=build_preparation_report(r,p,prepared_at=datetime(2026,8,15,tzinfo=timezone.utc)); validate_report(out)
    assert out['current_state']=='AWAITING_HELIUS_RENEWAL_AND_NEW_WALLET_DISCOVERY'
    assert all(out['safety'][k]==0 for k in ('network_requests','helius_requests','helius_credits','database_reads','database_writes','jupiter_requests','live_orders'))
    assert out['safety']['signer_access'] is False

def test_m72_tamper_fails_closed():
    r,p=m72_bundle(); p['provider']['credit_cap']=601
    with pytest.raises(M74M78Error): build_preparation_report(r,p)

def test_m74_good_candidate_passes():
    out=evaluate_m74_candidate(candidate()); assert out['passed'] is True

def test_m74_observe_only_fails_even_with_good_metrics():
    out=evaluate_m74_candidate(candidate(good=False)); assert out['passed'] is False; assert out['checks']['m73_disposition'] is False

@pytest.mark.parametrize('field,value',[
 ('profit_factor',1.29),('win_rate_percent',29.9),('maximum_drawdown_percent',15.1),('net_pnl_sol',0.0),('closed_trade_count',99),('history_span_days',29.9)])
def test_m74_economic_boundaries_fail(field,value):
    c=candidate(); c['economic_analysis']['metrics'][field]=value; assert evaluate_m74_candidate(c)['passed'] is False

def test_m74_rejects_tampered_qualified_disposition_when_economic_gate_false():
    c=candidate(); c['economic_analysis']['economic_gate_passed']=False
    assert evaluate_m74_candidate(c)['passed'] is False

def test_m74_rejects_if_any_original_economic_check_false():
    c=candidate(); c['economic_analysis']['checks']['positive_without_best']=False
    assert evaluate_m74_candidate(c)['passed'] is False

def test_m75_exact_boundaries_pass():
    out=evaluate_m75_canary('A'*32,canary_records(),admitted=True); assert out['passed'] is True

def test_m75_not_admitted_fails():
    assert evaluate_m75_canary('A'*32,canary_records(),admitted=False)['passed'] is False

def test_m75_23h59_fails():
    assert evaluate_m75_canary('A'*32,canary_records(hours=23.99),admitted=True)['checks']['observation_hours'] is False

def test_m75_19_attempts_fail():
    assert evaluate_m75_canary('A'*32,canary_records(attempts=19),admitted=True)['checks']['entry_attempts'] is False

def test_m75_9_closed_fail():
    assert evaluate_m75_canary('A'*32,canary_records(closes=9),admitted=True)['checks']['closed_trades'] is False

def test_m75_reject_rate_over_20_fails():
    assert evaluate_m75_canary('A'*32,canary_records(reject=5),admitted=True)['checks']['entry_reject_rate'] is False

def test_m75_webhook_under_95_fails():
    rows=canary_records(); rows[0]['webhook_covered']=False; rows[1]['webhook_covered']=False
    assert evaluate_m75_canary('A'*32,rows,admitted=True)['checks']['webhook_coverage'] is False

def test_m75_unsigned_must_be_100():
    rows=canary_records(); rows[0]['unsigned_build_success']=False
    assert evaluate_m75_canary('A'*32,rows,admitted=True)['checks']['unsigned_build_coverage'] is False

def test_m75_p95_guards():
    rows=canary_records(); rows[0]['end_to_quote_ms']=5001; rows[1]['end_to_quote_ms']=5001
    assert evaluate_m75_canary('A'*32,rows,admitted=True)['checks']['end_to_quote_p95'] is False

def test_m75_exact_95_webhook_and_20_reject_boundaries_pass():
    rows=canary_records(reject=4); rows[0]['webhook_covered']=False
    out=evaluate_m75_canary('A'*32,rows,admitted=True)
    assert out['metrics']['webhook_coverage_percent']==95.0
    assert out['metrics']['entry_reject_rate_percent']==20.0
    assert out['checks']['webhook_coverage'] is True
    assert out['checks']['entry_reject_rate'] is True

def test_m75_exact_p95_limits_pass():
    rows=canary_records()
    for row in rows[:2]:
        row['end_to_quote_ms']=5000; row['price_impact_bps']=500; row['price_deterioration_bps']=1000
    out=evaluate_m75_canary('A'*32,rows,admitted=True)
    assert out['checks']['end_to_quote_p95'] is True
    assert out['checks']['price_impact_p95'] is True
    assert out['checks']['price_deterioration_p95'] is True

def test_m75_worker_failure_fails():
    rows=canary_records(); rows[0]['worker_failure']=True
    assert evaluate_m75_canary('A'*32,rows,admitted=True)['checks']['worker_failures'] is False

def test_m75_policy_violation_fails():
    rows=canary_records(); rows[0]['policy_violation']=True
    assert evaluate_m75_canary('A'*32,rows,admitted=True)['checks']['policy_violations'] is False

def test_m75_open_position_at_terminal_fails():
    rows=canary_records(); terminal=next(r for r in rows if r['event_type']=='CANARY_TERMINAL_STATE'); terminal['open_position_count']=1
    out=evaluate_m75_canary('A'*32,rows,admitted=True)
    assert out['checks']['zero_open_positions'] is False
    assert out['passed'] is False

def test_m75_unresolved_failure_at_terminal_fails():
    rows=canary_records(); terminal=next(r for r in rows if r['event_type']=='CANARY_TERMINAL_STATE'); terminal['unresolved_failure_count']=1
    out=evaluate_m75_canary('A'*32,rows,admitted=True)
    assert out['checks']['zero_unresolved_failures'] is False
    assert out['passed'] is False

def test_m75_missing_or_duplicate_terminal_state_fails_closed():
    rows=[r for r in canary_records() if r['event_type']!='CANARY_TERMINAL_STATE']
    assert evaluate_m75_canary('A'*32,rows,admitted=True)['passed'] is False
    rows=canary_records(); rows.append(dict(next(r for r in rows if r['event_type']=='CANARY_TERMINAL_STATE')))
    assert evaluate_m75_canary('A'*32,rows,admitted=True)['passed'] is False

def test_m76_requires_two_confirmed_distinct_clusters():
    wallets=['A'*32,'B'*32]; conf=[{'wallet_address':wallets[0],'independence_confirmed':True,'cluster_id':'c1'},{'wallet_address':wallets[1],'independence_confirmed':True,'cluster_id':'c2'}]
    assert evaluate_m76_independence(wallets,conf)['passed'] is True

def test_m76_same_cluster_fails():
    wallets=['A'*32,'B'*32]; conf=[{'wallet_address':w,'independence_confirmed':True,'cluster_id':'c1'} for w in wallets]
    assert evaluate_m76_independence(wallets,conf)['passed'] is False

def test_m76_unconfirmed_fails():
    wallets=['A'*32,'B'*32]; conf=[{'wallet_address':wallets[0],'independence_confirmed':True,'cluster_id':'c1'},{'wallet_address':wallets[1],'independence_confirmed':False,'cluster_id':'c2'}]
    assert evaluate_m76_independence(wallets,conf)['passed'] is False

def test_consensus_two_independent_within_180s_passes():
    conf=[{'wallet_address':'A'*32,'independence_confirmed':True,'cluster_id':'c1'},{'wallet_address':'B'*32,'independence_confirmed':True,'cluster_id':'c2'}]
    t=datetime(2026,8,1,tzinfo=timezone.utc)
    ev=[{'wallet_address':'A'*32,'token_mint':'T'*32,'side':'BUY','timestamp_utc':t.isoformat(),'requested_size_sol':0.05},{'wallet_address':'B'*32,'token_mint':'T'*32,'side':'BUY','timestamp_utc':(t+timedelta(seconds=179)).isoformat(),'requested_size_sol':0.05}]
    out=build_m76_consensus_signals(ev,conf); assert len(out)==1; assert out[0]['independent_wallet_count']==2

def test_consensus_exact_180s_and_point_one_exposure_passes():
    conf=[{'wallet_address':'A'*32,'independence_confirmed':True,'cluster_id':'c1'},{'wallet_address':'B'*32,'independence_confirmed':True,'cluster_id':'c2'}]
    t=datetime(2026,8,1,tzinfo=timezone.utc)
    ev=[{'wallet_address':'A'*32,'token_mint':'T'*32,'side':'BUY','timestamp_utc':t.isoformat(),'requested_size_sol':0.05},{'wallet_address':'B'*32,'token_mint':'T'*32,'side':'BUY','timestamp_utc':(t+timedelta(seconds=180)).isoformat(),'requested_size_sol':0.05}]
    out=build_m76_consensus_signals(ev,conf); assert len(out)==1; assert out[0]['requested_exposure_sol']==0.1

def test_consensus_181s_fails():
    conf=[{'wallet_address':'A'*32,'independence_confirmed':True,'cluster_id':'c1'},{'wallet_address':'B'*32,'independence_confirmed':True,'cluster_id':'c2'}]
    t=datetime(2026,8,1,tzinfo=timezone.utc)
    ev=[{'wallet_address':'A'*32,'token_mint':'T'*32,'side':'BUY','timestamp_utc':t.isoformat(),'requested_size_sol':0.05},{'wallet_address':'B'*32,'token_mint':'T'*32,'side':'BUY','timestamp_utc':(t+timedelta(seconds=181)).isoformat(),'requested_size_sol':0.05}]
    assert build_m76_consensus_signals(ev,conf)==[]

def test_consensus_exposure_over_point_one_fails():
    conf=[{'wallet_address':'A'*32,'independence_confirmed':True,'cluster_id':'c1'},{'wallet_address':'B'*32,'independence_confirmed':True,'cluster_id':'c2'}]
    t=datetime(2026,8,1,tzinfo=timezone.utc)
    ev=[{'wallet_address':'A'*32,'token_mint':'T'*32,'side':'BUY','timestamp_utc':t.isoformat(),'requested_size_sol':0.06},{'wallet_address':'B'*32,'token_mint':'T'*32,'side':'BUY','timestamp_utc':(t+timedelta(seconds=10)).isoformat(),'requested_size_sol':0.05}]
    assert build_m76_consensus_signals(ev,conf)==[]

@pytest.mark.parametrize('key,value',[('maximum_open_positions',6),('minimum_history_span_days',29.0),('canary_minimum_entry_attempts',19),('canary_minimum_closed_trades',9),('canary_maximum_worker_failures',1)])
def test_frozen_policy_drift_fails_closed(key,value):
    with pytest.raises(M74M78Error): validate_policy({key:value})

def test_canary_terminal_policy_cannot_be_disabled():
    with pytest.raises(M74M78Error): validate_policy({'canary_require_zero_open_positions':False})
    with pytest.raises(M74M78Error): validate_policy({'canary_require_zero_unresolved_failures':False})

def m73_report(wallets):
    report={'evaluation':'PASS','scope':'M73_CONTROLLED_NEW_WALLET_ACQUISITION_AND_QUALIFICATION',
            'version':'canonical-parser-gen4-controlled-new-wallet-qualification/1',
            'candidate_results':[candidate(w) for w in wallets],
            'safety':{'helius_request_cap':6,'helius_credit_cap':600,'helius_retries':0,
                      'automatic_enhanced_api':False,'official_realtime_counter_mutated':False,
                      'paper_orders':0,'live_orders':0,'signer_authorized':False}}
    report['integrity']={'report_payload_sha256':canonical_sha256(report)}
    return report

def test_full_future_evaluation_ready_but_never_authorized():
    r,p=m72_bundle(); wallets=['A'*32,'B'*32]
    can=sign_canary_evidence({w:canary_records() for w in wallets})
    ind=sign_independence_evidence([{'wallet_address':wallets[0],'independence_confirmed':True,'cluster_id':'c1'},{'wallet_address':wallets[1],'independence_confirmed':True,'cluster_id':'c2'}])
    out=evaluate_post_discovery(r,p,m73_report(wallets),can,ind,evaluated_at=datetime(2026,8,15,tzinfo=timezone.utc)); validate_report(out)
    assert out['m78_final_transition']['micro_live_ready'] is True
    assert out['m78_final_transition']['micro_live_execution_authorized'] is False
    assert out['m77_micro_live_envelope']['maximum_total_budget_sol']==0.05
    assert out['m77_micro_live_envelope']['maximum_order_budget_sol']==0.01
    assert out['m77_micro_live_envelope']['maximum_order_count']==3

def test_one_good_wallet_never_ready():
    r,p=m72_bundle(); w='A'*32
    out=evaluate_post_discovery(r,p,m73_report([w]),sign_canary_evidence({w:canary_records()}),sign_independence_evidence([{'wallet_address':w,'independence_confirmed':True,'cluster_id':'c1'}]),evaluated_at=datetime(2026,8,15,tzinfo=timezone.utc))
    assert out['m78_final_transition']['micro_live_ready'] is False

def test_consensus_excludes_wallet_that_did_not_pass_m74_m75():
    r,p=m72_bundle(); good=['A'*32,'B'*32]; bad='C'*32; wallets=good+[bad]
    m73=m73_report(wallets); m73['candidate_results'][2]['disposition']='OBSERVE_ONLY'; m73['integrity']={'report_payload_sha256':canonical_sha256({k:v for k,v in m73.items() if k!='integrity'})}
    can=sign_canary_evidence({w:canary_records() for w in wallets})
    conf=[{'wallet_address':good[0],'independence_confirmed':True,'cluster_id':'c1'},{'wallet_address':good[1],'independence_confirmed':True,'cluster_id':'c2'},{'wallet_address':bad,'independence_confirmed':True,'cluster_id':'c3'}]
    t=datetime(2026,8,1,tzinfo=timezone.utc)
    events=[{'wallet_address':bad,'token_mint':'X'*32,'side':'BUY','timestamp_utc':t.isoformat(),'requested_size_sol':0.05},{'wallet_address':good[0],'token_mint':'X'*32,'side':'BUY','timestamp_utc':(t+timedelta(seconds=10)).isoformat(),'requested_size_sol':0.05}]
    out=evaluate_post_discovery(r,p,m73,can,sign_independence_evidence(conf,events),evaluated_at=datetime(2026,8,15,tzinfo=timezone.utc))
    assert out['m78_final_transition']['micro_live_ready'] is True
    assert out['m76_consensus_signals']==[]

def test_future_m73_tamper_detected():
    r,p=m72_bundle(); wallets=['A'*32,'B'*32]; m73=m73_report(wallets); m73['candidate_results'][0]['history_complete']=False
    with pytest.raises(M74M78Error): evaluate_post_discovery(r,p,m73,sign_canary_evidence({w:canary_records() for w in wallets}),sign_independence_evidence([{'wallet_address':wallets[0],'independence_confirmed':True,'cluster_id':'c1'},{'wallet_address':wallets[1],'independence_confirmed':True,'cluster_id':'c2'}]))

def test_canary_evidence_tamper_detected():
    r,p=m72_bundle(); wallets=['A'*32,'B'*32]; can=sign_canary_evidence({w:canary_records() for w in wallets}); can['wallet_records'][wallets[0]][0]['webhook_covered']=False
    with pytest.raises(M74M78Error): evaluate_post_discovery(r,p,m73_report(wallets),can,sign_independence_evidence([{'wallet_address':wallets[0],'independence_confirmed':True,'cluster_id':'c1'},{'wallet_address':wallets[1],'independence_confirmed':True,'cluster_id':'c2'}]))

def test_independence_evidence_tamper_detected():
    r,p=m72_bundle(); wallets=['A'*32,'B'*32]; ind=sign_independence_evidence([{'wallet_address':wallets[0],'independence_confirmed':True,'cluster_id':'c1'},{'wallet_address':wallets[1],'independence_confirmed':True,'cluster_id':'c2'}]); ind['confirmations'][1]['cluster_id']='c1'
    with pytest.raises(M74M78Error): evaluate_post_discovery(r,p,m73_report(wallets),sign_canary_evidence({w:canary_records() for w in wallets}),ind)

def test_report_tamper_detected():
    r,p=m72_bundle(); out=build_preparation_report(r,p); out['current_state']='BAD'
    with pytest.raises(M74M78Error): validate_report(out)
