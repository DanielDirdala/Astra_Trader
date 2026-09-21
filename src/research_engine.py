"""Small-finalist Astra review with a serialized, application-side cost guard.

No trade execution, no training, no profit targeting, no background scheduler.
Uses the previously installed US-market and research-review add-ons.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING
from uuid import uuid4

from src.us_market_ops import canonical, number, stamp, utcnow, write_local

POLICY_VERSION = 'astra-consolidated-v0.3-bgflex'
BUDGET_LOCK = 84392761
PRICE_SOURCE = 'https://developers.openai.com/api/docs/models/gpt-6-astra'
VERIFIED_DATE = '2026-09-18'


@dataclass(frozen=True)
class CostPolicy:
    finalists: int = 3
    max_picks: int = 2
    per_sector: int = 2
    news_per_symbol: int = 3
    max_input_tokens: int = 8000
    max_output_tokens: int = 3000
    per_call_usd: Decimal = Decimal('0.20')
    rolling_7d_usd: Decimal = Decimal('1.00')
    calls_per_7d: int = 2
    min_hours_between_calls: int = 6
    quote_max_age: int = 60

    def __post_init__(self):
        limits = {
            'finalists': (1, 5), 'max_picks': (1, 5), 'per_sector': (1, 5),
            'news_per_symbol': (1, 5), 'max_input_tokens': (1000, 20000),
            'max_output_tokens': (2000, 8000), 'calls_per_7d': (1, 20),
            'min_hours_between_calls': (1, 168), 'quote_max_age': (1, 300),
        }
        for key, (low, high) in limits.items():
            value = getattr(self, key)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f'{key} must be an integer from {low} to {high}.')
        if self.max_picks > self.finalists:
            raise ValueError('max_picks cannot exceed finalists.')
        for key in ('per_call_usd', 'rolling_7d_usd'):
            value = getattr(self, key)
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise ValueError(f'{key} must be a positive finite Decimal.')

    @classmethod
    def load(cls):
        from dotenv import load_dotenv
        from src.us_market_ops import ROOT
        load_dotenv(ROOT / '.env')
        ints = {
            'finalists': ('ASTRA_FINALISTS', 3),
            'max_picks': ('ASTRA_MAX_PICKS', 2),
            'per_sector': ('ASTRA_FINALISTS_PER_SECTOR', 2),
            'news_per_symbol': ('ASTRA_NEWS_PER_FINALIST', 3),
            'max_input_tokens': ('ASTRA_MAX_INPUT_TOKENS', 8000),
            'max_output_tokens': ('ASTRA_MAX_OUTPUT_TOKENS', 3000),
            'calls_per_7d': ('ASTRA_MAX_CALLS_7D', 2),
            'min_hours_between_calls': ('ASTRA_MIN_HOURS_BETWEEN_CALLS', 6),
            'quote_max_age': ('OPS_QUOTE_MAX_AGE_SECONDS', 60),
        }
        kwargs = {key: int(os.getenv(env, str(default)))
                  for key, (env, default) in ints.items()}
        kwargs['per_call_usd'] = Decimal(os.getenv('ASTRA_MAX_CALL_USD', '0.20'))
        kwargs['rolling_7d_usd'] = Decimal(os.getenv('ASTRA_BUDGET_7D_USD', '1.00'))
        return cls(**kwargs)


def _pick(mapping, keys):
    return {key: copy.deepcopy(mapping[key]) for key in keys if key in mapping}


def compact_live(live):
    """Preserve quote timestamps and flags; do not repeat the raw snapshot object."""
    result = {key: copy.deepcopy(value) for key, value in live.items() if key != 'snapshot'}
    snapshot = live.get('snapshot') or {}
    result['bars'] = {key: _pick(snapshot[key], ('t', 'o', 'h', 'l', 'c', 'v', 'n', 'vw'))
                      for key in ('minuteBar', 'dailyBar', 'prevDailyBar')
                      if isinstance(snapshot.get(key), dict)}
    return result


def compact_news(articles, limit, now):
    """Deterministic latest-article sample, not a sentiment model or full-news digest."""
    prepared = []
    for item in articles:
        try:
            published = stamp(item['published_at'])
        except (ValueError, KeyError, TypeError):
            continue
        if not now-timedelta(days=7) <= published <= now+timedelta(seconds=5):
            continue
        if not isinstance(item.get('source_id'), str) or not item['source_id']:
            continue
        prepared.append((published, item))
    prepared.sort(key=lambda pair: (pair[0], pair[1]['source_id']), reverse=True)
    output, seen = [], set()
    for _, item in prepared:
        # Deduplicate by normalized headline, otherwise URL, otherwise source ID.
        headline = str(item.get('headline') or '')
        key = re.sub(r'\W+', '', headline.casefold()) or str(item.get('url') or item['source_id'])
        if key in seen:
            continue
        seen.add(key)
        row = _pick(item, ('source_id', 'published_at', 'source', 'url', 'retrieved_at'))
        summary = str(item.get('summary') or '')
        row.update(headline=headline[:500], summary=summary[:450],
                   text_truncated=(len(headline) > 500 or len(summary) > 450))
        output.append(row)
        if len(output) == limit:
            break
    return output


def build_finalist_input(context, policy, now=None):
    from src.ops_review import payload_from_context
    now = now or utcnow()
    payload = copy.deepcopy(payload_from_context(context, min(policy.max_picks, policy.finalists), now))
    if type(context.get('market_clock', {}).get('is_open')) is not bool:
        raise ValueError('Broker market-open status is unavailable.')
    market_open = context['market_clock']['is_open']
    occupied = {p.get('symbol') for p in context.get('positions', [])}
    occupied |= {o.get('symbol') for o in context.get('open_orders', [])}
    pool, excluded = [], {}
    for candidate in payload['candidates']:
        symbol = candidate['symbol']
        q, live = candidate.get('quantitative', {}), candidate.get('live_market', {})
        reason = None
        if symbol in occupied:
            reason = 'Existing position/order: this final-entry review is not an exit manager.'
        elif candidate.get('news_fetch_status') != 'ok':
            reason = 'News request did not succeed; no paid new-entry review of this candidate.'
        elif q.get('session_date') != context.get('daily_target_session'):
            reason = 'Completed daily session does not match the capture target.'
        elif number(q.get('technical_score')) is None or (number(q.get('price')) or 0) <= 0:
            reason = 'Invalid price or numerical screening score.'
        elif market_open:
            try:
                age = (now-stamp(live['quote_timestamp'])).total_seconds()
            except (KeyError, ValueError, TypeError):
                age = None
            bid, ask = number(live.get('bid')), number(live.get('ask'))
            spread = number(live.get('spread_bps'))
            if age is None or not -2 <= age <= policy.quote_max_age:
                reason = 'Quote is missing or stale at review time.'
            elif bid is None or ask is None or bid <= 0 or ask < bid or spread is None or spread > 50:
                reason = 'Invalid quote or spread above the existing 50-bps paper guard.'
        if reason:
            excluded[symbol] = reason
        else:
            pool.append(candidate)
    pool.sort(key=lambda item: (-float(item['quantitative']['technical_score']), item['symbol']))
    finalists, sectors = [], {}
    for item in pool:
        sector = item.get('sector') or 'Unknown'
        if sectors.get(sector, 0) >= policy.per_sector:
            continue
        finalists.append(item)
        sectors[sector] = sectors.get(sector, 0)+1
        if len(finalists) == policy.finalists:
            break
    # Sector cap is never relaxed merely to fill a quota.
    selected = []
    common_market = None
    for candidate in finalists:
        item = copy.deepcopy(candidate)
        mc = item.pop('market_context', {})
        if common_market is None:
            common_market = mc
        elif canonical(mc) != canonical(common_market):
            raise ValueError('Benchmark contexts differ inside one capture; recapture rather than merge.')
        item['live_market'] = compact_live(item.get('live_market', {}))
        item['recent_news'] = compact_news(item.get('recent_news', []), policy.news_per_symbol, now)
        item['news_omitted_by_compaction'] = max(0, len(candidate.get('recent_news', []))-len(item['recent_news']))
        q = item.get('quantitative', {})
        item['quantitative'] = {k: v for k, v in q.items() if k != 'history_provenance'}
        item['history_provenance'] = q.get('history_provenance', [])
        selected.append(item)
    if common_market is not None:
        common_market = copy.deepcopy(common_market)
        for benchmark in common_market.values():
            if isinstance(benchmark, dict) and 'live' in benchmark:
                benchmark['live'] = compact_live(benchmark['live'])
    payload['candidates'] = selected
    payload['shared_market_context'] = common_market or {}
    payload['finalist_policy'] = {
        'version': POLICY_VERSION, 'source_shortlist_size': len(context['candidates']),
        'eligible_source_candidates': len(pool), 'reviewed_finalists': len(selected),
        'sector_cap': policy.per_sector, 'news_per_finalist': policy.news_per_symbol,
        'selection_rule': 'Existing Python technical_score descending, then symbol; sector cap applied.',
        'not_a_trained_predictor': True,
    }
    payload['application_warnings'] += [
        'Only Python-selected finalists receive Astra review. Omitted stocks may be better investments.',
        'News is a small latest-item sample. Omitted adverse facts may exist; no full-news analysis was performed.',
        'A fixed dollar profit target is NOT supplied to the model and must NOT influence order sizing.',
        'Shorter reasoning/output is a cost-quality tradeoff, not proof of equal decision quality.',
    ]
    # Do not send dozens of rejected records to the model; store them in the preview only.
    audit = {'excluded': excluded, 'source_symbols': [c['symbol'] for c in context['candidates']],
             'finalists': [c['symbol'] for c in selected],
             'note': 'This final-entry selector excludes existing holdings/orders; it does not monitor exits.'}
    canonical(payload)
    return payload, audit


def economical_spec(payload, model, policy):
    from src.astra_review import request_spec
    from src.ops_review import OPS_PROMPT
    if model != 'gpt-6-astra':
        raise ValueError('This rate table is only verified for gpt-6-astra; no silent model substitution.')
    spec = request_spec(payload, model, policy.max_output_tokens)
    spec['instructions'] = OPS_PROMPT + '''\nCost-controlled FINALIST review only. The shared_market_context applies to all candidates.
Python has already calculated indicators, returns and scores. Do not recalculate or narrate
those calculations. Evaluate only supplied finalists; do not fill the BUY quota.
Keep market_summary under 100 words; each thesis/bull_case/bear_case/invalidation under
35 words; risks and missing_information at most 3 short items each; additional_research
at most 2 items. Preserve material negative evidence. All prior data/approval restrictions apply.
'''
    spec['reasoning'] = {'effort': 'low'}
    spec['text']['verbosity'] = 'low'
    spec['service_tier'] = 'flex'
    spec['background'] = True
    spec['store'] = False
    return spec


def count_input_tokens(spec, key, session=None):
    """Counts the actual formatted input via OpenAI; no generation and no retries.

    This sends the same market/account information to OpenAI even if the later
    budget check prevents generation. Count-endpoint availability is required.
    """
    import requests
    request_body = {k: spec[k] for k in ('model', 'input', 'instructions', 'reasoning', 'text')}
    own = session is None
    session = session or requests.Session()
    try:
        response = session.post('https://api.openai.com/v1/responses/input_tokens',
            headers={'Authorization': 'Bearer '+key, 'Content-Type': 'application/json'},
            json=request_body, timeout=(10, 60), allow_redirects=False)
        if response.status_code != 200:
            raise RuntimeError(f'Input count failed: HTTP {response.status_code}; no generation requested.')
        count = response.json().get('input_tokens')
        if type(count) is not int or count <= 0:
            raise ValueError('Invalid input-token count; no generation requested.')
        return count
    finally:
        if own:
            session.close()


def call_allowance(input_tokens, policy):
    if type(input_tokens) is not int or not 0 < input_tokens <= policy.max_input_tokens:
        raise ValueError(f'Input must be 1-{policy.max_input_tokens} tokens; compact further before sending.')
    # Flex rates: conservatively assume every input token incurs the higher
    # cache-write price, plus max output and 10% planning headroom.
    # This is an application allowance, not an invoice guarantee.
    value = (Decimal(input_tokens)*Decimal('6.25') +
             Decimal(policy.max_output_tokens)*Decimal('25'))/Decimal(1000000)
    value = (value*Decimal('1.10')).quantize(Decimal('.000001'), rounding=ROUND_CEILING)
    if value > policy.per_call_usd:
        raise ValueError(f'Conservative call allowance ${value:.4f} exceeds ${policy.per_call_usd}.')
    return value


def budget_snapshot(rows):
    """Unknown legacy costs are UNKNOWN, never silently zero dollars."""
    total, unknown = Decimal(0), []
    for row in rows:
        estimate = row.get('cost_high_usd')
        if estimate is None:
            estimate = (row.get('input_payload') or {}).get('budget_guard', {}).get('reservation_usd')
        try:
            value = Decimal(str(estimate))
            if not value.is_finite() or value < 0:
                raise ValueError('invalid cost')
        except Exception:
            unknown.append(str(row['id']))
            continue
        total += value
    return {'attempts': len(rows), 'committed_usd': total, 'unknown_ids': unknown}


def enforce_budget(rows, policy, allowance, now):
    """Block unresolved/unknown prior requests, but do not enforce rolling spend/call cooldowns.

    Per-request cost control remains in call_allowance(). Usage is still logged and
    reported, but a successful older review does not prevent a new deliberate review.
    """
    del allowance, now
    state = budget_snapshot(rows)
    if state['unknown_ids']:
        raise ValueError('Prior usage has no reliable estimate. Reconcile these review IDs first: '+
                         ', '.join(state['unknown_ids']))
    if any(row.get('status') in ('STARTED', 'UNKNOWN', 'SAVE_ERROR') for row in rows):
        raise ValueError('An unresolved prior request exists. Inspect/reconcile it; do not create a replacement paid request.')
    return state


def validate_send_freshness(payload, policy, now):
    age = (now-stamp(payload['context_captured_at'])).total_seconds()
    if not -5 <= age <= 300:
        raise ValueError('Context expired; capture again before a paid review.')
    if payload['market_clock'].get('is_open'):
        for candidate in payload['candidates']:
            try:
                quote_age = (now-stamp(candidate['live_market']['quote_timestamp'])).total_seconds()
            except (KeyError, ValueError, TypeError):
                raise ValueError('A finalist quote lost its timestamp.') from None
            if not -2 <= quote_age <= policy.quote_max_age:
                raise ValueError('A finalist quote aged out before sending; capture again. No generation requested.')


class BudgetStore:
    """Budgeted claim on EXISTING review tables; other unpatched callers bypass it."""
    def __init__(self, reviews):
        self.reviews = reviews

    @staticmethod
    def _rows(conn):
        # The v0.3 rolling budget applies to v0.3 attempts. Recent unresolved
        # legacy attempts still block new sends until they are reconciled.
        return conn.execute('''SELECT r.id,r.status,r.started_at,r.input_payload,u.cost_high_usd,
                   u.input_tokens,u.output_tokens,u.reasoning_tokens,r.prompt_version
            FROM public.astra_review_runs r
            LEFT JOIN public.astra_api_usage u ON u.review_id=r.id
            WHERE (r.prompt_version=%s AND r.started_at >= now()-interval '7 days')
               OR r.status IN ('STARTED','UNKNOWN','SAVE_ERROR')
                  AND r.started_at >= now()-interval '24 hours'
            ORDER BY r.started_at DESC''', (POLICY_VERSION,)).fetchall()

    def recent(self):
        with self.reviews.connect() as conn:
            return self._rows(conn)

    def claim(self, payload, spec, fingerprint, policy, allowance):
        from psycopg.types.json import Jsonb
        record = copy.deepcopy(payload)
        record['budget_guard'] = {
            'version': POLICY_VERSION, 'reservation_usd': str(allowance),
            'rate_verified': VERIFIED_DATE, 'pricing_source': PRICE_SOURCE,
            'rolling_7d_usd': str(policy.rolling_7d_usd),
            'max_calls_7d': policy.calls_per_7d,
            'note': 'Application-side planning allowance; not an invoice or account-wide cap.'}
        identifier = uuid4()
        with self.reviews.connect() as conn:
            conn.execute("SET LOCAL lock_timeout = '15s'")
            conn.execute('SELECT pg_advisory_xact_lock(%s)', (BUDGET_LOCK,))
            prior = conn.execute('SELECT id,status FROM public.astra_review_runs WHERE request_fingerprint=%s',
                                 (fingerprint,)).fetchone()
            if prior:
                return prior, False
            now = conn.execute('SELECT clock_timestamp() AS now').fetchone()['now']
            # Freshness must still hold AFTER waiting for the transaction lock.
            validate_send_freshness(payload, policy, now)
            enforce_budget(self._rows(conn), policy, allowance, now)
            event = conn.execute('''INSERT INTO public.system_events(event_type,message,metadata)
                VALUES ('LOW_COST_ASTRA_REVIEW','Python finalists only; no orders authorized.',%s) RETURNING id''',
                (Jsonb({'context_id': payload['context_id'], 'reservation_usd': str(allowance)}),)).fetchone()['id']
            row = conn.execute('''INSERT INTO public.astra_review_runs
                (id,source_event_id,selection_id,request_fingerprint,attempt,model_requested,
                 prompt_version,request_spec,input_payload,status)
                VALUES (%s,%s,%s,%s,1,%s,%s,%s,%s,'STARTED') RETURNING id,status''',
                (identifier,event,payload['selection_id'],fingerprint,spec['model'],POLICY_VERSION,
                 Jsonb(spec),Jsonb(record))).fetchone()
        # Reserved before generation. A crash leaves STARTED for manual reconciliation.
        return row, True


def run_review(store, context, model='gpt-6-astra', send=False, max_picks=None,
               policy=None, now=None, counter=None, requester=None, reviews=None):
    from src.ops_review import make_review_store
    from src.astra_review import request_fingerprint
    from scripts.run_astra_review import process_response, safe_fail
    from dataclasses import replace
    policy = policy or CostPolicy.load()
    if max_picks is not None:
        policy = replace(policy, max_picks=min(int(max_picks), policy.max_picks, policy.finalists))
    payload, audit = build_finalist_input(context, policy, now)
    print(f'Python source shortlist: {len(context["candidates"])}; Astra finalists: {len(payload["candidates"])}')
    print('Finalists:', ', '.join(audit['finalists']) or 'NONE')
    print('Maximum output tokens including reasoning:', policy.max_output_tokens)
    if not payload['candidates']:
        print('No eligible finalists. No model call. This is not a guarantee that no good trade exists.')
        write_local(context['context_id']+'.finalist-audit.json', audit)
        return 0
    spec = economical_spec(payload, model, policy)
    fingerprint = request_fingerprint(spec)
    preview = write_local(fingerprint+'.low-cost-input.json', {'request': spec, 'payload': payload, 'audit': audit})
    print('Input preview:', preview)
    print(f'Per-call allowance cap=${policy.per_call_usd}; no rolling budget/cooldown is enforced; usage is still logged.')
    if not send:
        print('PREVIEW ONLY. No OpenAI token-count or generation request. Add --send deliberately.')
        return 0
    key = os.getenv('OPENAI_API_KEY', '').strip()
    if not key:
        raise ValueError('OPENAI_API_KEY is missing.')
    reviews = reviews or make_review_store()
    reviews.check_tables()
    budget = BudgetStore(reviews)
    # Avoid even sending payloads to the count endpoint when already out of budget.
    # A prior identical request should be returned, not counted again.
    with reviews.connect() as conn:
        prior = conn.execute('SELECT id,status FROM public.astra_review_runs WHERE request_fingerprint=%s',
                             (fingerprint,)).fetchone()
    if prior:
        print(f'Identical request already recorded: {prior["id"]} ({prior["status"]}); not sending.')
        return 0 if prior['status'] == 'COMPLETED' else 1
    enforce_budget(budget.recent(), policy, Decimal(0), utcnow())
    print('Counting formatted input through OpenAI; no generation yet.')
    count = (counter or count_input_tokens)(spec, key)
    allowance = call_allowance(count, policy)
    print(f'Counted input tokens={count}; planned maximum token-cost allowance=${allowance:.4f}')
    # Recheck age/eligibility after the count operation without changing approved input.
    validate_send_freshness(payload, policy, utcnow())
    row, created = budget.claim(payload, spec, fingerprint, policy, allowance)
    if not created:
        print('Concurrent identical request already claimed:', row['id'])
        return 0 if row['status'] == 'COMPLETED' else 1
    identifier = row['id']
    print('Review ID:', identifier)
    # Tests may inject a one-shot requester; production uses background mode.
    if requester is not None:
        try:
            response = requester(spec)
        except Exception as error:
            safe_fail(reviews, identifier, 'UNKNOWN', f'Generation outcome unresolved: {type(error).__name__}')
            print('Request outcome UNKNOWN. No automatic retry. Inspect billing and this review before another attempt.')
            return 1
    else:
        from src.background_review import BackgroundResponses, TERMINAL_STATUSES
        client = BackgroundResponses(key)
        try:
            try:
                response = client.create(spec)
            except Exception as error:
                safe_fail(reviews, identifier, 'UNKNOWN', f'Background create outcome unresolved: {type(error).__name__}')
                print('Background create outcome UNKNOWN before a response ID was recorded. Check billing before another send.')
                return 1
            response_id = response['id']
            reviews.attach_response_id(identifier, response_id)
            print('OpenAI response ID saved:', response_id)
            if response.get('status') not in TERMINAL_STATUSES:
                try:
                    polled = client.poll(response_id, max_wait_seconds=int(os.getenv('ASTRA_POLL_SECONDS', '120')),
                                         interval_seconds=int(os.getenv('ASTRA_POLL_INTERVAL_SECONDS', '5')))
                    response = polled.response
                    if not polled.terminal:
                        print('Response is still running. No second generation was sent.')
                        print(f'Resume later: python -m scripts.trader resume --review {identifier}')
                        return 0
                except Exception as error:
                    print(f'Polling interrupted ({type(error).__name__}). The saved response ID can be resumed without another generation.')
                    print(f'Resume: python -m scripts.trader resume --review {identifier}')
                    return 1
        finally:
            client.close()
    try:
        write_local(str(identifier)+'.response.json', response)
    except Exception as error:
        print(f'Local response backup failed ({type(error).__name__}); attempting database persistence.')
    try:
        status, report, usage, ids = process_response(reviews, identifier, response, payload)
    except Exception as error:
        safe_fail(reviews, identifier, 'SAVE_ERROR', f'Persistence failed: {type(error).__name__}')
        print('Response persistence failed. Keep local response; do not pay again to fix database storage.')
        return 1
    print(f'Status: {status}; input={usage.get("input_tokens")}; output={usage.get("output_tokens")}; '
          f'reasoning subset={usage.get("reasoning_tokens")}')
    if usage.get('cost_high_usd') is not None:
        print(f'Token-cost estimate: ${usage["cost_low_usd"]:.4f}-${usage["cost_high_usd"]:.4f}; not an invoice.')
    if report:
        print(report.market_summary)
        print('Hypothetical BUY proposals:', ', '.join(report.selected_symbols) or 'NONE')
        print('Pending record IDs:', ids)
    print('No positions sized, no orders submitted, no profit target chased.')
    return 0 if status == 'COMPLETED' else 1


def usage_rows(reviews):
    """All recent/unresolved review attempts for reporting, independent of v0.3 budget scope."""
    with reviews.connect() as conn:
        return conn.execute('''SELECT r.id,r.status,r.started_at,r.input_payload,r.prompt_version,
                   r.response_id,u.cost_low_usd,u.cost_high_usd,u.input_tokens,
                   u.output_tokens,u.reasoning_tokens,u.service_tier
            FROM public.astra_review_runs r
            LEFT JOIN public.astra_api_usage u ON u.review_id=r.id
            WHERE r.started_at >= now()-interval '7 days'
               OR r.status IN ('STARTED','UNKNOWN','SAVE_ERROR')
            ORDER BY r.started_at DESC''').fetchall()


def _finish_background_response(reviews, review_id, response, payload):
    from scripts.run_astra_review import process_response, safe_fail
    try:
        write_local(str(review_id)+'.response.json', response)
    except Exception as error:
        print(f'Local response backup failed ({type(error).__name__}); attempting database persistence.')
    try:
        status, report, usage, ids = process_response(reviews, review_id, response, payload)
    except Exception as error:
        safe_fail(reviews, review_id, 'SAVE_ERROR', f'Persistence failed: {type(error).__name__}')
        print('Response persistence failed. Do not create a replacement paid response merely to fix storage.')
        return 1
    print(f'Status: {status}; input={usage.get("input_tokens")}; output={usage.get("output_tokens")}; '
          f'reasoning subset={usage.get("reasoning_tokens")}; tier={usage.get("service_tier")}')
    if usage.get('cost_high_usd') is not None:
        print(f'Token-cost estimate: ${usage["cost_low_usd"]:.4f}-${usage["cost_high_usd"]:.4f}; not an invoice.')
    if report:
        print(report.market_summary)
        print('Hypothetical BUY proposals:', ', '.join(report.selected_symbols) or 'NONE')
        print('Pending record IDs:', ids)
    print('No positions sized, no orders submitted, no profit target chased.')
    return 0 if status == 'COMPLETED' else 1


def resume_review(review_id, *, reviews=None, api_key=None, wait_seconds=120):
    """Retrieve/poll an already-created background response. Never creates a generation."""
    from src.ops_review import make_review_store
    from src.background_review import BackgroundResponses, TERMINAL_STATUSES
    reviews = reviews or make_review_store()
    reviews.check_tables()
    row, _ = reviews.get_review(review_id)
    if row is None:
        raise ValueError('Review not found.')
    if row['status'] == 'COMPLETED':
        print('Review already completed; no API generation or retrieval needed.')
        return 0
    if row['status'] != 'STARTED':
        raise ValueError(f'Review status is {row["status"]}; it is not resumable.')
    response_id = row.get('response_id')
    if not response_id:
        raise ValueError('This review has no saved OpenAI response ID. Reconcile it instead of resending.')
    key = api_key or os.getenv('OPENAI_API_KEY', '').strip()
    if not key:
        raise ValueError('OPENAI_API_KEY is missing.')
    client = BackgroundResponses(key)
    try:
        polled = client.poll(response_id, max_wait_seconds=int(wait_seconds),
                             interval_seconds=int(os.getenv('ASTRA_POLL_INTERVAL_SECONDS', '5')))
        response = polled.response
        if not polled.terminal:
            print(f'OpenAI response {response_id} is still {response.get("status")}.')
            print('No new generation was created. Run the same resume command later.')
            return 0
        return _finish_background_response(reviews, review_id, response, row['input_payload'])
    finally:
        client.close()


def cancel_review(review_id, *, reviews=None, api_key=None):
    """Cancel one saved background response; never creates a new response."""
    from src.ops_review import make_review_store
    from src.background_review import BackgroundResponses
    reviews = reviews or make_review_store()
    row, _ = reviews.get_review(review_id)
    if row is None:
        raise ValueError('Review not found.')
    if row['status'] != 'STARTED' or not row.get('response_id'):
        raise ValueError('Only a STARTED review with a saved response ID can be cancelled.')
    key = api_key or os.getenv('OPENAI_API_KEY', '').strip()
    if not key:
        raise ValueError('OPENAI_API_KEY is missing.')
    client = BackgroundResponses(key)
    try:
        response = client.cancel(row['response_id'])
    finally:
        client.close()
    return _finish_background_response(reviews, review_id, response, row['input_payload'])


def reconcile_review(review_id, cost_low, cost_high, reason, *, reviews=None):
    """Record a manual dashboard-derived estimate for an old uncertain request."""
    from src.ops_review import make_review_store
    reviews = reviews or make_review_store()
    reviews.reconcile_unknown_cost(review_id, cost_low, cost_high, reason)
    print(f'Reconciled {review_id}: ${Decimal(str(cost_low)):.4f}-${Decimal(str(cost_high)):.4f}')
    print('No OpenAI request was made. Token counts remain unknown.')
    return 0
