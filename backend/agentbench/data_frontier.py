"""Private-holdout data engineering and data science frontier cases.

The public contracts are deliberately precise while the generated records and
evaluation histories remain private.  This prevents a polished memo or a
hard-coded public sample from receiving a frontier score.
"""

from __future__ import annotations

import textwrap
from typing import Any

DATA_CASE_VERSION = "2.0.0"


def _validator(kind: str, weight: float, **config: Any) -> dict[str, Any]:
    return {"type": kind, "weight": weight, "config": config}


PIPELINE_SPEC = textwrap.dedent(
    """
    # Incremental revenue ledger contract

    Implement `process_batch(state, events, customer_versions)` in `pipeline.py`.
    It returns `{"state": ..., "aggregates": [...], "audit": [...]}` and must not
    mutate any input object. All returned values must be JSON serializable.

    Event fields are `event_id`, `kind` (`sale` or `refund`), `order_id`,
    `occurred_at`, `received_at`, and `amount_cents`. A sale also has
    `customer_id`; a refund refers to its sale by `order_id`. Timestamps are ISO
    8601 with an explicit offset. Money is a positive integer number of cents.

    * Exact duplicate event IDs are ignored across and within batches. Reusing an
      event ID with different canonical JSON raises `EventConflict` and the whole
      batch is atomic.
    * Received order is not event order. A refund may precede its sale and must be
      retained. Cumulative refunds may not exceed the sale; an invalid batch is
      rejected atomically.
    * Customer rows are SCD2 intervals `[valid_from, valid_to)`; `valid_to=null`
      means open ended. Attribute the sale using `occurred_at`, not ingestion time.
    * Revenue day is the UTC date of the sale. Refunds reduce the original sale's
      day and segment, never the refund arrival day.
    * `aggregates` is the complete snapshot sorted by `(date, segment)`, with rows
      `{"date":"YYYY-MM-DD","segment":str,"net_cents":int}`; zero rows are omitted.
    * `audit` contains one immutable hash-chain entry for every newly accepted
      unique event. Replays add no entries. Each row exposes increasing `seq`,
      `event_id`, `prev_hash`, and `hash`; the state must preserve the chain.

    Only Python 3.12 standard library is available. The hidden evaluator runs
    multi-batch, late-data, collision, SCD-boundary, timezone and replay histories.
    """
).strip() + "\n"


PIPELINE_STARTER = textwrap.dedent(
    """
    class EventConflict(ValueError):
        pass


    def process_batch(state, events, customer_versions):
        # Return a new incremental state, aggregate snapshot, and audit chain.
        raise NotImplementedError
    """
).strip() + "\n"


def _pipeline_validator() -> str:
    return textwrap.dedent(
        r'''
        import argparse, copy, hashlib, importlib, json, random, sys, traceback
        from datetime import datetime, timezone
        from pathlib import Path

        METRICS = {key: 0.0 for key in (
            "contract", "event_time_scd", "exactly_once", "late_refund",
            "atomic_replay", "audit_chain", "history_generalization",
        )}
        EVIDENCE = {}
        sys.path.insert(0, str(Path.cwd()))
        parser=argparse.ArgumentParser(); parser.add_argument('--seed',default='0'*64); args=parser.parse_args()
        rng=random.Random(int(hashlib.sha256(args.seed.encode()).hexdigest()[:16],16))

        def canon(value):
            return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

        CUSTOMERS = [
            {"customer_id":"c1","valid_from":"2025-12-01T00:00:00Z","valid_to":"2026-01-01T00:00:00Z","segment":"legacy"},
            {"customer_id":"c1","valid_from":"2026-01-01T00:00:00Z","valid_to":None,"segment":"growth"},
            {"customer_id":"c2","valid_from":"2020-01-01T00:00:00Z","valid_to":None,"segment":"enterprise"},
        ]

        def event(eid, kind, order, occurred, received, amount, customer=None):
            value = {"event_id":eid,"kind":kind,"order_id":order,"occurred_at":occurred,"received_at":received,"amount_cents":amount}
            if customer is not None:
                value["customer_id"] = customer
            return value

        def rows(result):
            assert isinstance(result, dict) and set(("state","aggregates","audit")) <= set(result)
            json.dumps(result, ensure_ascii=False)
            actual = result["aggregates"]
            assert isinstance(actual, list)
            assert actual == sorted(actual, key=lambda x: (x["date"], x["segment"]))
            return {(x["date"], x["segment"]): x["net_cents"] for x in actual}

        def run_metric(name, fn):
            try:
                detail = fn()
                METRICS[name] = 100.0
                EVIDENCE[name] = {"ok": True, **(detail or {})}
            except Exception as exc:
                EVIDENCE[name] = {"ok": False, "error": repr(exc), "trace": traceback.format_exc()[-1800:]}

        try:
            module = importlib.import_module("pipeline")
            process = module.process_batch
            conflict_type = module.EventConflict
        except Exception as exc:
            EVIDENCE["import"] = {"ok": False, "error": repr(exc), "trace": traceback.format_exc()[-1800:]}
            print("AGENTBENCH_METRICS=" + canon({"metrics":METRICS,"evidence":EVIDENCE}))
            raise SystemExit(0)

        def contract():
            source_state = {}
            events = [event("e1","sale","o1","2026-01-02T00:30:00+08:00","2026-01-02T02:00:00+08:00",1200,"c1")]
            before = canon([source_state, events, CUSTOMERS])
            result = process(source_state, events, copy.deepcopy(CUSTOMERS))
            assert canon([source_state, events, CUSTOMERS]) == before, "inputs mutated"
            assert rows(result) == {("2026-01-01","growth"):1200}
            return {"json_serializable": True, "utc_day": True}

        def event_time_scd():
            events = [
                event("b","sale","old","2025-12-31T23:59:59Z","2026-02-01T00:00:00Z",700,"c1"),
                event("a","sale","new","2026-01-01T00:00:00Z","2025-12-31T19:00:00-05:00",900,"c1"),
                event("c","sale","tz","2026-01-02T00:15:00+14:00","2026-01-03T00:00:00Z",500,"c2"),
            ]
            actual = rows(process({}, list(reversed(events)), copy.deepcopy(CUSTOMERS)))
            assert actual == {("2025-12-31","legacy"):700,("2026-01-01","growth"):900,("2026-01-01","enterprise"):500}, actual
            return {"scd_half_open": True, "offset_normalized": True}

        def exactly_once():
            sale = event("dup","sale","o2","2026-01-03T12:00:00Z","2026-01-03T12:01:00Z",333,"c2")
            first = process({}, [sale, copy.deepcopy(sale)], copy.deepcopy(CUSTOMERS))
            replay = process(copy.deepcopy(first["state"]), [copy.deepcopy(sale)], copy.deepcopy(CUSTOMERS))
            assert rows(replay) == {("2026-01-03","enterprise"):333}
            assert len(replay["audit"]) == len(first["audit"]) == 1
            changed = copy.deepcopy(sale); changed["amount_cents"] = 334
            frozen = canon(first["state"])
            try:
                process(first["state"], [changed], copy.deepcopy(CUSTOMERS))
                raise AssertionError("conflicting event id accepted")
            except conflict_type:
                pass
            assert canon(first["state"]) == frozen
            return {"deduplicated": True, "collision_rejected": True}

        def late_refund():
            refund = event("r1","refund","late","2026-02-05T00:00:00Z","2026-02-05T00:00:01Z",250)
            first = process({}, [refund], copy.deepcopy(CUSTOMERS))
            assert rows(first) == {}, first["aggregates"]
            sale = event("s1","sale","late","2025-12-20T21:00:00-05:00","2026-02-06T00:00:00Z",1000,"c1")
            second = process(first["state"], [sale], copy.deepcopy(CUSTOMERS))
            assert rows(second) == {("2025-12-21","legacy"):750}
            third = process(second["state"], [event("r2","refund","late","2026-02-07T00:00:00Z","2026-02-07T00:00:00Z",750)], copy.deepcopy(CUSTOMERS))
            assert rows(third) == {}
            return {"refund_before_sale": True, "original_bucket": True}

        def atomic_replay():
            base = process({}, [event("s2","sale","bounded","2026-01-04T00:00:00Z","2026-01-04T00:00:00Z",500,"c2")], copy.deepcopy(CUSTOMERS))
            frozen = canon(base["state"])
            bad = [event("r3","refund","bounded","2026-01-05T00:00:00Z","2026-01-05T00:00:00Z",200), event("r4","refund","bounded","2026-01-05T00:00:01Z","2026-01-05T00:00:01Z",400)]
            try:
                process(base["state"], bad, copy.deepcopy(CUSTOMERS))
                raise AssertionError("over-refund accepted")
            except (ValueError, conflict_type):
                pass
            assert canon(base["state"]) == frozen, "failed batch mutated state"
            once = process(base["state"], [bad[0]], copy.deepcopy(CUSTOMERS))
            twice = process(once["state"], [bad[0]], copy.deepcopy(CUSTOMERS))
            assert canon(once) == canon(twice), "replay changed snapshot"
            return {"batch_atomic": True, "restart_replay_stable": True}

        def audit_chain():
            history = [event(f"h{i}","sale",f"oh{i}",f"2026-01-0{i+1}T00:00:00Z",f"2026-02-0{i+1}T00:00:00Z",100+i,"c2") for i in range(1,4)]
            first = process({}, history[:2], copy.deepcopy(CUSTOMERS))
            second = process(first["state"], history[2:], copy.deepcopy(CUSTOMERS))
            audit = second["audit"]
            assert [row["seq"] for row in audit] == list(range(1, len(audit)+1))
            assert [row["event_id"] for row in audit] == ["h1","h2","h3"]
            assert audit[0]["prev_hash"] in ("", None, "0"*64)
            for left, right in zip(audit, audit[1:]):
                assert right["prev_hash"] == left["hash"]
            assert all(isinstance(row["hash"], str) and len(row["hash"]) == 64 for row in audit)
            return {"entries": len(audit), "linked": True}

        def history_generalization():
            checks=0
            for trial in range(4):
                history=[]; sales={}; refunds={}; accepted={}; state={}
                for i in range(32):
                    oid=f'random-{trial}-{i}'; amount=rng.randrange(100,50000); refund=rng.randrange(1,amount+1)
                    history.extend([event('sale-'+oid,'sale',oid,'2026-01-02T00:00:00Z','2026-02-02T00:00:00Z',amount,'c2'),
                                    event('refund-'+oid,'refund',oid,'2026-02-03T00:00:00Z','2026-02-04T00:00:00Z',refund)])
                rng.shuffle(history)
                history.extend(copy.deepcopy(history[:9])); rng.shuffle(history)
                for begin in range(0,len(history),7):
                    batch=history[begin:begin+7]; customers=copy.deepcopy(CUSTOMERS)
                    before=canon([state,batch,customers]); result=process(state,batch,customers)
                    assert canon([state,batch,customers])==before, 'history inputs mutated'
                    for row in batch:
                        if row['event_id'] in accepted: continue
                        accepted[row['event_id']]=row
                        if row['kind']=='sale': sales[row['order_id']]=row['amount_cents']
                        else: refunds[row['order_id']]=refunds.get(row['order_id'],0)+row['amount_cents']
                    net=sum(amount-refunds.get(oid,0) for oid,amount in sales.items())
                    assert rows(result)==({('2026-01-02','enterprise'):net} if net else {})
                    assert len(result['audit'])==len(accepted)
                    for left,right in zip(result['audit'],result['audit'][1:]): assert right['prev_hash']==left['hash']
                    state=json.loads(canon(result['state'])); checks+=1
            return {'checked_batches':checks,'seeded_histories':4}

        for name, fn in (("contract",contract),("event_time_scd",event_time_scd),("exactly_once",exactly_once),("late_refund",late_refund),("atomic_replay",atomic_replay),("audit_chain",audit_chain),("history_generalization",history_generalization)):
            run_metric(name, fn)
        print("AGENTBENCH_METRICS=" + canon({"metrics":METRICS,"evidence":EVIDENCE}))
        '''
    ).strip() + "\n"


EXPERIMENT_SPEC = textwrap.dedent(
    """
    # Cluster-randomized online experiment audit

    Implement `analyze(payload)` in `experiment_audit.py`; return a JSON object.
    Each unit has `cluster_id`, binary `assigned`, binary `received`, `pre`,
    optional `outcome`, `response_probability`, and `stratum`.

    Required fields:

    * `itt`: difference between treatment and control means of cluster-level IPW
      outcome means. Missing outcomes are omitted and observed outcomes use
      weight `1/response_probability`; clusters, not users, are analysis units.
    * `cluster_se`: sqrt(s_t^2/n_t + s_c^2/n_c), using sample variances of the
      cluster IPW means.
    * `cuped_theta`: pooled sample covariance(cluster pre mean, cluster IPW
      outcome mean) divided by sample variance of cluster pre means. Pre is
      centered at the pooled cluster mean. `cuped_itt` is the arm difference of
      adjusted cluster outcomes.
    * `first_stage`: treatment-control difference of cluster mean `received`;
      `cace=cuped_itt/first_stage`, or null when the denominator is effectively 0.
    * `holm_rejections`: hypothesis names rejected by Holm's step-down procedure
      at `payload.alpha`, returned in input-name order.
    * `sequential_crossed`: whether any look satisfies
      `abs(z) >= 1.959963984540054 / sqrt(information_fraction)`.
    * `simpson_flag`: true when the sign of the raw user-level arm difference is
      opposite to the sign of the equally weighted average of within-stratum arm
      differences (zero is not opposite).

    Reject invalid probabilities, mixed treatment assignment inside a cluster,
    non-finite numbers and strata missing either arm. Hidden tests include
    unequal cluster sizes, informative missingness, noncompliance, tied p-values,
    Simpson reversal and near-zero first stages. Do not use post-treatment fields
    for CUPED.
    """
).strip() + "\n"


EXPERIMENT_STARTER = "def analyze(payload):\n    raise NotImplementedError\n"


def _experiment_validator() -> str:
    return textwrap.dedent(
        r'''
        import argparse, copy, hashlib, importlib, json, math, random, sys, traceback
        from pathlib import Path
        sys.path.insert(0, str(Path.cwd()))
        KEYS=("estimands","cluster_uncertainty","cuped","noncompliance","multiplicity_sequential","simpson_validation")
        metrics={key:0.0 for key in KEYS}; evidence={}
        parser=argparse.ArgumentParser(); parser.add_argument('--seed',default='0'*64); args=parser.parse_args()
        rng=random.Random(int(hashlib.sha256(args.seed.encode()).hexdigest()[:16],16))

        def close(a,b,tol=1e-8):
            return isinstance(a,(int,float)) and math.isfinite(a) and abs(a-b) <= tol*max(1,abs(b))
        def sample_var(xs):
            m=sum(xs)/len(xs); return sum((x-m)**2 for x in xs)/(len(xs)-1)
        def reference(payload):
            units=payload["units"]; clusters={}
            for row in units:
                p=float(row["response_probability"])
                if not (0 < p <= 1): raise ValueError("invalid response probability")
                for key in ("pre",):
                    if not math.isfinite(float(row[key])): raise ValueError("non-finite")
                bucket=clusters.setdefault(row["cluster_id"],[]); bucket.append(row)
            packed=[]
            for cid, rows in clusters.items():
                assigned={int(x["assigned"]) for x in rows}
                if len(assigned)!=1: raise ValueError("mixed cluster assignment")
                observed=[x for x in rows if x.get("outcome") is not None]
                if not observed: raise ValueError("cluster without observed outcome")
                num=sum(float(x["outcome"])/float(x["response_probability"]) for x in observed)
                den=sum(1/float(x["response_probability"]) for x in observed)
                packed.append({"arm":assigned.pop(),"y":num/den,"pre":sum(float(x["pre"]) for x in rows)/len(rows),"received":sum(float(x["received"]) for x in rows)/len(rows)})
            arms={a:[x for x in packed if x["arm"]==a] for a in (0,1)}
            if min(map(len,arms.values()))<2: raise ValueError("need two clusters per arm")
            mean=lambda xs,k: sum(x[k] for x in xs)/len(xs)
            itt=mean(arms[1],"y")-mean(arms[0],"y")
            se=math.sqrt(sample_var([x["y"] for x in arms[1]])/len(arms[1])+sample_var([x["y"] for x in arms[0]])/len(arms[0]))
            xbar=mean(packed,"pre"); ybar=mean(packed,"y")
            cov=sum((x["pre"]-xbar)*(x["y"]-ybar) for x in packed)/(len(packed)-1)
            var=sample_var([x["pre"] for x in packed]); theta=0.0 if var<1e-15 else cov/var
            for x in packed: x["adj"]=x["y"]-theta*(x["pre"]-xbar)
            cuped=mean(arms[1],"adj")-mean(arms[0],"adj")
            stage=mean(arms[1],"received")-mean(arms[0],"received")
            cace=None if abs(stage)<1e-12 else cuped/stage
            hypotheses=payload.get("hypotheses",[]); ordered=sorted(enumerate(hypotheses),key=lambda z:(float(z[1]["p"]),z[0])); rejected=set()
            for rank,(index,item) in enumerate(ordered):
                if float(item["p"]) <= float(payload.get("alpha",.05))/(len(ordered)-rank): rejected.add(index)
                else: break
            holm=[item["name"] for i,item in enumerate(hypotheses) if i in rejected]
            crossed=any(abs(float(x["z"])) >= 1.959963984540054/math.sqrt(float(x["information_fraction"])) for x in payload.get("looks",[]))
            raw={a:[float(x["outcome"]) for x in units if int(x["assigned"])==a and x.get("outcome") is not None] for a in (0,1)}
            raw_diff=sum(raw[1])/len(raw[1])-sum(raw[0])/len(raw[0])
            strata=[]
            for name in sorted({x["stratum"] for x in units}):
                values={a:[float(x["outcome"]) for x in units if x["stratum"]==name and int(x["assigned"])==a and x.get("outcome") is not None] for a in (0,1)}
                if not values[0] or not values[1]: raise ValueError("stratum arm missing")
                strata.append(sum(values[1])/len(values[1])-sum(values[0])/len(values[0]))
            within=sum(strata)/len(strata)
            simpson=raw_diff*within<0
            return {"itt":itt,"cluster_se":se,"cuped_theta":theta,"cuped_itt":cuped,"first_stage":stage,"cace":cace,"holm_rejections":holm,"sequential_crossed":crossed,"simpson_flag":simpson}

        def payload(reversal=False, zero_stage=False):
            units=[]
            # Deliberately unequal clusters and response probabilities.
            specs=[("c0",0,"A",7,0.10),("c1",0,"B",3,0.30),("c2",0,"A",4,0.20),("c3",1,"A",2,0.25),("c4",1,"B",8,0.45),("c5",1,"B",5,0.35)]
            for ci,(cid,arm,stratum,n,base) in enumerate(specs):
                for j in range(n):
                    if reversal:
                        outcome=(9 if stratum=="A" else 1)+arm*0.8
                    else: outcome=base+arm*0.22+0.03*j
                    if zero_stage:
                        received=0
                    elif arm:
                        received=0 if j % 4 == 0 else 1
                    else:
                        received=1 if j % 5 == 0 else 0
                    units.append({"cluster_id":cid,"assigned":arm,"received":received,"pre":base+0.01*j,"outcome":None if (j==0 and ci in (1,4)) else outcome,"response_probability":0.55 if j==0 else 0.9,"stratum":stratum})
            return {"alpha":.05,"units":units,"hypotheses":[{"name":"h1","p":.009},{"name":"h2","p":.021},{"name":"h3","p":.2}],"looks":[{"z":2.1,"information_fraction":.5},{"z":2.02,"information_fraction":1.0}]}

        try: analyze=importlib.import_module("experiment_audit").analyze
        except Exception as exc:
            evidence["import"]={"error":repr(exc)}; print("AGENTBENCH_METRICS="+json.dumps({"metrics":metrics,"evidence":evidence})); raise SystemExit(0)
        mapping={"estimands":("itt",),"cluster_uncertainty":("cluster_se",),"cuped":("cuped_theta","cuped_itt"),"noncompliance":("first_stage","cace"),"multiplicity_sequential":('holm_rejections','sequential_crossed')}
        passed={key:0 for key in mapping}; failures={key:[] for key in mapping}
        for trial in range(12):
            p=payload(False,trial==11)
            if trial:
                scale=rng.uniform(.3,4); offset=rng.uniform(-3,8)
                for row in p['units']:
                    if row['outcome'] is not None: row['outcome']=scale*row['outcome']+offset+rng.uniform(-.1,.1)
                    row['pre']=0.0 if trial==10 else row['pre']*rng.uniform(.5,2)
                    row['response_probability']=rng.uniform(.15,1)
                    row['cluster_id']=f"seed-{trial}-"+row['cluster_id']
                rng.shuffle(p['units'])
                p['hypotheses']=[{'name':f'h{i}','p':rng.choice([.001,.008,.02,.05,.2,.9])} for i in range(1+trial%7)]
                p['looks']=[{'z':rng.uniform(-4,4),'information_fraction':rng.uniform(.1,1)} for _ in range(4)]
            try:
                expected=reference(p); frozen=copy.deepcopy(p); actual=analyze(p)
                assert p==frozen, 'input mutated'
                assert isinstance(actual,dict)
                for metric,fields in mapping.items():
                    ok=all((actual.get(f)==expected[f] if isinstance(expected[f],(list,bool)) or expected[f] is None else close(actual.get(f),expected[f])) for f in fields)
                    if ok: passed[metric]+=1
                    else: failures[metric].append({'trial':trial,'expected':{f:expected[f] for f in fields},'actual':{f:actual.get(f) for f in fields}})
            except Exception as exc:
                for metric in mapping: failures[metric].append({'trial':trial,'error':repr(exc)})
        for metric in mapping:
            metrics[metric]=100*passed[metric]/12
            evidence[metric]={'passed':passed[metric],'total':12,'failures':failures[metric][:3]}
        try:
            p2=payload(True); e2=reference(p2); a2=analyze(json.loads(json.dumps(p2)))
            assert a2.get("simpson_flag") is e2["simpson_flag"] is True
            p3=payload(False,True); e3=reference(p3); a3=analyze(json.loads(json.dumps(p3)))
            assert a3.get("cace") is None and close(a3.get("first_stage"),e3["first_stage"])
            bad=payload(); bad["units"][0]["response_probability"]=0
            try: analyze(bad); raise AssertionError("invalid probability accepted")
            except (ValueError,TypeError): pass
            metrics["simpson_validation"]=100; evidence["simpson_validation"]={"ok":True,"reversal":True,"invalid_rejected":True}
        except Exception as exc:
            evidence.setdefault("failure",{"error":repr(exc),"trace":traceback.format_exc()[-2200:]})
        print("AGENTBENCH_METRICS="+json.dumps({"metrics":metrics,"evidence":evidence},ensure_ascii=False,separators=(",",":")))
        '''
    ).strip() + "\n"


MODEL_SPEC = textwrap.dedent(
    """
    # Leakage-resistant temporal risk model

    Implement `fit_predict(train_rows, future_rows)` in `risk_model.py`. Return
    one probability in `[0,1]` per future row, preserving input order. Training
    rows contain `timestamp`, `entity`, numeric `x1`, `x2`, `post_outcome_leak`
    and binary `label`; future rows omit `label`.

    `post_outcome_leak` is unavailable at decision time and must have no effect on
    predictions, even if it is highly predictive in the training sample. Handle
    unseen entities, constant columns, reordered records and gradual coefficient/
    prevalence drift. Use chronological validation rather than random splitting;
    do not read files or global state inside the function. The result must be
    deterministic and calibrated probabilities, not hard labels.

    The hidden evaluator uses multiple future windows and distribution shifts. It
    scores strict interface safety, leakage invariance, log loss, Brier/calibration,
    drift robustness and repeatability. Only Python 3.12 standard library is
    guaranteed; generic learned approaches are required because coefficients,
    entities and drifts vary by committed hidden seed.
    """
).strip() + "\n"


MODEL_STARTER = "def fit_predict(train_rows, future_rows):\n    raise NotImplementedError\n"


def _model_validator() -> str:
    return textwrap.dedent(
        r'''
        import argparse, copy, hashlib, importlib, json, math, random, sys, traceback
        from datetime import datetime, timedelta, timezone
        from pathlib import Path
        sys.path.insert(0,str(Path.cwd()))
        keys=("interface","leakage_safety","temporal_logloss","calibration","drift_robustness","determinism")
        metrics={k:0.0 for k in keys}; evidence={}
        parser=argparse.ArgumentParser(); parser.add_argument("--seed",default="0"*64); args=parser.parse_args()
        seed=int(hashlib.sha256(args.seed.encode()).hexdigest()[:16],16); rng=random.Random(seed)
        def sigmoid(x): return 1/(1+math.exp(-max(-30,min(30,x))))
        entities=[f"e{i}" for i in range(7)]; effects={e:rng.uniform(-.8,.8) for e in entities}; b1=rng.uniform(1.1,1.8); b2=rng.uniform(-1.6,-.8)
        start=datetime(2025,1,1,tzinfo=timezone.utc)
        def make(begin,n,labels=True):
            rows=[]; ys=[]
            for i in range(n):
                t=begin+i; drift=t/500; entity=entities[(i*5+rng.randrange(len(entities)))%len(entities)] if t<500 else ("unseen" if i%5==0 else entities[i%len(entities)])
                x1=rng.gauss(.3*math.sin(t/19),1); x2=rng.gauss(.2*math.cos(t/13),1)
                logit=-.55+effects.get(entity,.1)+b1*(1-.72*drift)*x1+b2*(1+.58*drift)*x2+.35*math.sin(t/11)+1.05*drift
                p=sigmoid(logit); y=1 if rng.random()<p else 0
                row={"timestamp":(start+timedelta(days=t)).isoformat(),"entity":entity,"x1":x1,"x2":x2,"post_outcome_leak":y if t<320 else rng.randint(0,1)}
                if labels: row["label"]=y
                rows.append(row); ys.append(y)
            return rows,ys
        train,_=make(0,480,True); future,y=make(480,360,False); shifted,y2=make(900,360,False)
        def validate(pred,n):
            assert isinstance(pred,(list,tuple)) and len(pred)==n
            values=[float(x) for x in pred]; assert all(math.isfinite(x) and 0<=x<=1 for x in values); return values
        def logloss(pred,ys): return -sum(y*math.log(max(1e-12,p))+(1-y)*math.log(max(1e-12,1-p)) for p,y in zip(pred,ys))/len(ys)
        def brier(pred,ys): return sum((p-y)**2 for p,y in zip(pred,ys))/len(ys)
        try: predict=importlib.import_module("risk_model").fit_predict
        except Exception as exc:
            evidence["import"]={"error":repr(exc)}; print("AGENTBENCH_METRICS="+json.dumps({"metrics":metrics,"evidence":evidence})); raise SystemExit(0)
        try:
            tc=copy.deepcopy(train); fc=copy.deepcopy(future)
            p=validate(predict(tc,fc),len(future)); assert tc==train and fc==future, 'inputs mutated'
            metrics["interface"]=100; evidence["interface"]={"ok":True}
            tampered=copy.deepcopy(future)
            for i,row in enumerate(tampered): row["post_outcome_leak"]=1-(i%2)
            changed_train=copy.deepcopy(train)
            for i,row in enumerate(changed_train): row['post_outcome_leak']=(i%2)
            pt=validate(predict(changed_train,tampered),len(future))
            delta=max(abs(a-b) for a,b in zip(p,pt))
            metrics["leakage_safety"]=100 if delta<1e-12 else 0; evidence["leakage_safety"]={"max_delta":delta}
            ll=logloss(p,y); metrics["temporal_logloss"]=max(0,min(100,100-(ll-.42)*180)); evidence["temporal_logloss"]={"log_loss":ll}
            br=brier(p,y); mean_error=abs(sum(p)/len(p)-sum(y)/len(y)); metrics["calibration"]=max(0,min(100,100-(br-.14)*260-mean_error*180)); evidence["calibration"]={"brier":br,"mean_error":mean_error}
            ps=validate(predict(copy.deepcopy(train),copy.deepcopy(shifted)),len(shifted)); ll2=logloss(ps,y2); metrics["drift_robustness"]=max(0,min(100,100-(ll2-.48)*170)); evidence["drift_robustness"]={"log_loss":ll2}
            again=validate(predict(copy.deepcopy(train),copy.deepcopy(future)),len(future)); shuffled=list(reversed(copy.deepcopy(future))); rev=validate(predict(copy.deepcopy(train),shuffled),len(shuffled)); order_delta=max(abs(a-b) for a,b in zip(p,reversed(rev)))
            reversed_train=validate(predict(list(reversed(copy.deepcopy(train))),copy.deepcopy(future)),len(future))
            train_delta=max(abs(a-b) for a,b in zip(p,reversed_train))
            metrics["determinism"]=100 if p==again and order_delta<1e-12 and train_delta<1e-10 else 0; evidence["determinism"]={"repeat_equal":p==again,"order_delta":order_delta,'train_order_delta':train_delta}
        except Exception as exc: evidence["failure"]={"error":repr(exc),"trace":traceback.format_exc()[-2500:]}
        print("AGENTBENCH_METRICS="+json.dumps({"metrics":metrics,"evidence":evidence},ensure_ascii=False,separators=(",",":")))
        '''
    ).strip() + "\n"


def _data_case(
    *,
    slug: str,
    title: str,
    instruction: str,
    filename: str,
    starter: str,
    spec_name: str,
    spec: str,
    validator: str,
    metrics: list[dict[str, Any]],
    minutes: int,
) -> dict[str, Any]:
    return {
        "slug": slug,
        "version": DATA_CASE_VERSION,
        "category": "data-engineering-science",
        "title": title,
        "description": "隐藏数据、可执行产物、抗泄漏与跨批次稳定性数据能力极限题。",
        "instruction": instruction,
        "tools": ["filesystem", "search", "shell"],
        "limits": {
            "max_steps": 220,
            "time_target_seconds": minutes * 60,
            "max_runtime_seconds": 14_400,
            "validator_timeout_seconds": 420,
            "token_budget": 300_000,
            "network": "disabled",
            "docker_image": "python:3.12-alpine",
        },
        "validators": [
            _validator("file_exists", 2, path=filename),
            _validator(
                "command_metrics",
                98,
                command="python {private_root}/validate.py --seed {validation_seed}",
                private_files={"validate.py": validator},
                metrics=metrics,
                metric_caps=[
                    {
                        "metric_key": item["key"],
                        "min_score": 100,
                        "max_score": item.get("cap", 82),
                        "reason": item.get("cap_reason", f"关键数据义务 {item['name']} 未完全通过"),
                    }
                    for item in metrics
                    if item.get("mastery", True)
                ],
                mastery_curve="frontier_v1",
                critical=True,
                critical_min_score=70,
            ),
            _validator("forbidden_paths", 0, paths=[".git", ".agentbench-private-*"]),
        ],
        "tags": ["six-dimension", "data", "hidden-holdout", "anti-leakage", "ultra"],
        "initial_files": {filename: starter, spec_name: spec},
        "attempt_policy": {
            "max_attempts": 2,
            "pass_threshold": 85,
            "multipliers": [1.0, 0.7],
            "preserve_workspace": True,
            "hints": ["根据失败指标修复通用方法；隐藏数据、标签和具体交错不会公开。"],
        },
        "metadata": {
            "difficulty": 6,
            "tier": "ultra",
            "estimated_minutes": minutes,
            "capability": "data-engineering-and-data-science-frontier",
            "capability_dimension": "data_engineering_science",
            "private_validation": True,
            "score_basis": "quality_only",
            "mastery_curve": "frontier_v1",
            "frontier_profile": "hidden-data-mastery-v1",
            "scoring_breakdown": metrics,
        },
    }


def build_data_frontier_cases() -> list[dict[str, Any]]:
    pipeline_metrics = [
        {"key":"contract","name":"接口与不可变输入","weight":10,"cap":65},
        {"key":"event_time_scd","name":"事件时间、时区与 SCD2","weight":20,"cap":72},
        {"key":"exactly_once","name":"Exactly-once 与冲突检测","weight":20,"cap":70},
        {"key":"late_refund","name":"乱序销售退款归因","weight":20,"cap":72},
        {"key":"atomic_replay","name":"原子批次与重放恢复","weight":20,"cap":68},
        {"key":"audit_chain","name":"增量审计哈希链","weight":10,"cap":82},
        {"key":"history_generalization","name":"隐藏乱序长历史模型对照","weight":20,"cap":78},
    ]
    experiment_metrics = [
        {"key":"estimands","name":"聚类 IPW ITT","weight":20,"cap":72},
        {"key":"cluster_uncertainty","name":"聚类不确定性","weight":15,"cap":78},
        {"key":"cuped","name":"CUPED 降方差","weight":20,"cap":72},
        {"key":"noncompliance","name":"非依从与 CACE","weight":15,"cap":78},
        {"key":"multiplicity_sequential","name":"多重检验与连续偷看","weight":15,"cap":78},
        {"key":"simpson_validation","name":"辛普森悖论与输入审计","weight":15,"cap":75},
    ]
    for metric in pipeline_metrics:
        if metric['key'] != 'history_generalization':
            metric['weight'] = int(metric['weight'] * 0.8)
    model_metrics = [
        {"key":"interface","name":"概率接口与输入安全","weight":10,"cap":65},
        {"key":"leakage_safety","name":"决策时点防泄漏","weight":20,"cap":65},
        {"key":"temporal_logloss","name":"未来窗口 Log Loss","weight":25,"mastery":False},
        {"key":"calibration","name":"Brier 与概率校准","weight":20,"mastery":False},
        {"key":"drift_robustness","name":"分布漂移鲁棒性","weight":20,"mastery":False},
        {"key":"determinism","name":"顺序不变与可复现","weight":5,"cap":82},
    ]
    return [
        _data_case(
            slug="sixdim.data-incremental-revenue-ledger",
            title="数据工程 Ultra · 乱序增量收入账本",
            instruction="阅读 PIPELINE_SPEC.md，完成 pipeline.py。公开接口只是起点；私有验证按多批次历史检查事件时间、SCD2、exactly-once、退款乱序、原子重放和审计链。",
            filename="pipeline.py", starter=PIPELINE_STARTER, spec_name="PIPELINE_SPEC.md", spec=PIPELINE_SPEC,
            validator=_pipeline_validator(), metrics=pipeline_metrics, minutes=120,
        ),
        _data_case(
            slug="sixdim.data-online-experiment-audit",
            title="数据科学 Ultra · 聚类在线实验审计",
            instruction="阅读 EXPERIMENT_SPEC.md，完成 experiment_audit.py。所有估计量必须在隐藏不平衡样本、缺失、非依从、辛普森反转和连续查看下数值正确。",
            filename="experiment_audit.py", starter=EXPERIMENT_STARTER, spec_name="EXPERIMENT_SPEC.md", spec=EXPERIMENT_SPEC,
            validator=_experiment_validator(), metrics=experiment_metrics, minutes=120,
        ),
        _data_case(
            slug="sixdim.data-temporal-risk-model",
            title="数据科学 Ultra · 抗泄漏时序风险模型",
            instruction="阅读 MODEL_SPEC.md，完成 risk_model.py。私有未来窗口会改变生成系数、实体和漂移；评分同时检查防泄漏、概率质量、校准、漂移与确定性。",
            filename="risk_model.py", starter=MODEL_STARTER, spec_name="MODEL_SPEC.md", spec=MODEL_SPEC,
            validator=_model_validator(), metrics=model_metrics, minutes=150,
        ),
    ]


__all__ = ["DATA_CASE_VERSION", "build_data_frontier_cases"]
