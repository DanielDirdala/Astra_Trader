"""Batched daily cache and timestamped current US-equity context.

No order writes or OpenAI requests in this module. All Alpaca account endpoints
are pinned to PAPER. This module deliberately does not overwrite legacy history.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

UTC = timezone.utc
NY = ZoneInfo('America/New_York')
PAPER_URL = 'https://paper-api.alpaca.markets'
DATA_URL = 'https://data.alpaca.markets'
VERSION = 'us-market-ops-v1'
ROOT = Path(__file__).resolve().parents[1]


def utcnow():
    return datetime.now(UTC)


def stamp(value):
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('Timezone-aware timestamp required.')
    return result.astimezone(UTC)


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (ValueError, TypeError):
        return None
    return value if math.isfinite(value) else None


def jsonable(value):
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return jsonable(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def canonical(value):
    return json.dumps(jsonable(value), allow_nan=False, sort_keys=True, separators=(',', ':'))


def write_local(name, value):
    folder = ROOT / 'reports' / 'market_ops'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(jsonable(value), indent=2, allow_nan=False), encoding='utf-8')
    os.replace(temp, path)
    return path


@dataclass(frozen=True)
class Settings:
    feed: str = 'iex'
    adjustment: str = 'raw'
    batch_size: int = 20
    backfill_sessions: int = 450
    full_refresh_days: int = 7
    quote_max_age: int = 60
    max_order_usd: float = 1000.0

    def __post_init__(self):
        if self.feed not in {'iex', 'sip'} or self.adjustment not in {'raw', 'split'}:
            raise ValueError('Use feed iex/sip and adjustment raw/split; no silent fallback.')
        if not 1 <= self.batch_size <= 50:
            raise ValueError('Batch size must be 1-50.')
        if not 1 <= self.full_refresh_days <= 90:
            raise ValueError('Full refresh cadence must be 1-90 days.')
        if not 250 <= self.backfill_sessions <= 600 or not 1 <= self.quote_max_age <= 300:
            raise ValueError('Require >=250 backfill sessions and a quote age of 1-300 seconds.')
        if not math.isfinite(self.max_order_usd) or self.max_order_usd <= 0:
            raise ValueError('Paper order notional cap must be positive.')

    @classmethod
    def load(cls):
        from dotenv import load_dotenv
        load_dotenv(ROOT / '.env')
        return cls(feed=os.getenv('OPS_FEED', 'iex'),
                   adjustment=os.getenv('OPS_ADJUSTMENT', 'raw'),
                   batch_size=int(os.getenv('OPS_BATCH_SIZE', '20')),
                   backfill_sessions=int(os.getenv('OPS_BACKFILL_SESSIONS', '450')),
                   full_refresh_days=int(os.getenv('OPS_FULL_REFRESH_DAYS', '7')),
                   quote_max_age=int(os.getenv('OPS_QUOTE_MAX_AGE_SECONDS', '60')),
                   max_order_usd=float(os.getenv('OPS_PAPER_MAX_ORDER_USD', '1000')))


class AlpacaReadError(RuntimeError):
    pass


class AlpacaHTTP:
    """Connection reuse, explicit feed, bounded GET-only retries. Never follows redirects."""
    def __init__(self, *, session=None, sleep=time.sleep, pace=0.55):
        from dotenv import load_dotenv
        load_dotenv(ROOT / '.env')
        self.session = session or requests.Session()
        self.session.headers.update({'APCA-API-KEY-ID': os.getenv('ALPACA_API_KEY', '').strip(),
                                     'APCA-API-SECRET-KEY': os.getenv('ALPACA_SECRET_KEY', '').strip()})
        self.sleep = sleep
        self.pace = pace
        self.last_call = 0.0
        self.requests_made = 0
        if session is None and not all(self.session.headers.get(k) for k in ['APCA-API-KEY-ID', 'APCA-API-SECRET-KEY']):
            raise ValueError('Missing Alpaca credentials; keep them in .env.')

    def close(self):
        self.session.close()

    def get(self, path, params=None, *, trading=False, allow_404=False):
        if not path.startswith('/') or path.startswith('//'):
            raise ValueError('An API path, not an external URL, is required.')
        base = PAPER_URL if trading else DATA_URL
        for attempt in range(4):
            self.sleep(max(0.0, self.pace - (time.monotonic() - self.last_call)))
            self.last_call = time.monotonic()
            self.requests_made += 1
            try:
                response = self.session.get(base + path, params=params, timeout=(10, 60), allow_redirects=False)
            except requests.RequestException as error:
                if attempt == 3:
                    raise AlpacaReadError(f'Network failure on GET {path}; {type(error).__name__}') from None
                self.sleep(2 ** attempt)
                continue
            if response.status_code == 404 and allow_404:
                return None
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                retry = number(response.headers.get('Retry-After'))
                self.sleep(min(120, max(1, retry if retry is not None else 2 ** attempt)))
                continue
            if response.status_code != 200:
                raise AlpacaReadError(f'GET {path}: HTTP {response.status_code}. Check permissions, feed and rate limits.')
            return response.json()
        raise AlpacaReadError('GET retry budget exhausted.')

    def bars(self, symbols, start_date, end_date, settings):
        output = {symbol: [] for symbol in symbols}
        params = {'symbols': ','.join(symbols), 'timeframe': '1Day',
                  'start': datetime.combine(start_date, datetime.min.time(), NY).isoformat(),
                  'end': (datetime.combine(end_date + timedelta(days=1), datetime.min.time(), NY)
                          - timedelta(microseconds=1)).isoformat(),
                  'feed': settings.feed, 'adjustment': settings.adjustment,
                  'sort': 'asc', 'limit': 10000}
        seen = set()
        while True:
            result = self.get('/v2/stocks/bars', params)
            if not isinstance(result.get('bars'), dict):
                raise AlpacaReadError('Malformed bars response; not treating this as empty history.')
            for symbol, bars in result['bars'].items():
                if symbol in output:
                    output[symbol].extend(bars)
            token = result.get('next_page_token')
            if not token:
                break
            if token in seen:
                raise AlpacaReadError('Repeated pagination token; stopping rather than losing data.')
            seen.add(token)
            params['page_token'] = token
        return output

    def calendar(self, start, end):
        return self.get('/v2/calendar', {'start': str(start), 'end': str(end)}, trading=True)

    def assets(self):
        return self.get('/v2/assets', {'status': 'active', 'asset_class': 'us_equity'}, trading=True)

    def account_context(self):
        account = self.get('/v2/account', trading=True)
        positions = self.get('/v2/positions', trading=True)
        orders = self.get('/v2/orders', {'status': 'open', 'limit': 500, 'nested': 'true'}, trading=True)
        if len(orders) >= 500:
            raise AlpacaReadError('Open-order response reached its limit; account context may be incomplete.')
        return account, positions, orders

    def news(self, symbol, now, *, max_articles=20):
        # Explicitly a capped latest-article sample, not a complete news/earnings feed.
        params = {'symbols': symbol, 'start': (now-timedelta(days=7)).isoformat(),
                  'end': now.isoformat(), 'limit': max_articles, 'sort': 'desc', 'include_content': 'false'}
        result = self.get('/v1beta1/news', params)
        if not isinstance(result, dict) or not isinstance(result.get('news'), list):
            raise AlpacaReadError('Malformed news response; not treating this as no news.')
        articles = []
        for item in result['news']:
            if symbol not in (item.get('symbols') or []):
                continue
            published = stamp(item['created_at'])
            if not now-timedelta(days=7) <= published <= now:
                continue
            articles.append({'source_id': f"NEWS:{symbol}:{item['id']}",
                             'headline': item.get('headline'), 'summary': item.get('summary'),
                             'published_at': item['created_at'], 'source': item.get('source'),
                             'url': item.get('url'), 'retrieved_at': now.isoformat()})
        return articles, bool(result.get('next_page_token'))


class OpsStore:
    def connect(self):
        import psycopg
        from psycopg.rows import dict_row
        from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
        return psycopg.connect(host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER,
                               password=DB_PASSWORD, row_factory=dict_row, connect_timeout=10,
                               application_name='astra_us_market_ops')

    def initialize(self):
        path = ROOT / 'database' / 'migrations' / '003_market_operations.sql'
        with self.connect() as conn:
            conn.execute(path.read_text(encoding='utf-8'))
            conn.execute('SELECT symbol,feed,adjustment,session_date,bar,provenance FROM public.astra_daily_cache LIMIT 0')
            conn.execute('SELECT id,payload FROM public.astra_market_contexts LIMIT 0')
            conn.execute('SELECT id,state,order_payload,order_sha256,submit_before FROM public.astra_paper_tickets LIMIT 0')

    def load_cache(self, symbols, settings):
        with self.connect() as conn:
            rows = conn.execute('''SELECT symbol,session_date,bar,provenance FROM public.astra_daily_cache
                WHERE symbol=ANY(%s) AND feed=%s AND adjustment=%s ORDER BY session_date''',
                (symbols, settings.feed, settings.adjustment)).fetchall()
            state = conn.execute('''SELECT * FROM public.astra_sync_state
                WHERE symbol=ANY(%s) AND feed=%s AND adjustment=%s''',
                (symbols, settings.feed, settings.adjustment)).fetchall()
        grouped = {symbol: {} for symbol in symbols}
        for row in rows:
            grouped[row['symbol']][row['session_date']] = {**row['bar'], '_provenance': row['provenance']}
        return grouped, {row['symbol']: row for row in state}

    def save_group(self, records, states, settings, provenance='alpaca_api'):
        from psycopg.types.json import Jsonb
        with self.connect() as conn, conn.cursor() as cur:
            cur.executemany('''INSERT INTO public.astra_daily_cache
                (symbol,feed,adjustment,session_date,bar_timestamp,bar,provenance)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(symbol,feed,adjustment,session_date) DO UPDATE SET
                bar_timestamp=EXCLUDED.bar_timestamp,bar=EXCLUDED.bar,
                provenance=EXCLUDED.provenance,received_at=now()
                WHERE astra_daily_cache.bar IS DISTINCT FROM EXCLUDED.bar
                   OR astra_daily_cache.bar_timestamp IS DISTINCT FROM EXCLUDED.bar_timestamp
                   OR astra_daily_cache.provenance IS DISTINCT FROM EXCLUDED.provenance''',
                [(s,settings.feed,settings.adjustment,d,stamp(bar['t']),Jsonb(bar),provenance)
                 for s,d,bar in records])
            cur.executemany('''INSERT INTO public.astra_sync_state
                (symbol,feed,adjustment,last_full_fetch,last_sync,row_count,newest_session)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(symbol,feed,adjustment) DO UPDATE SET
                last_full_fetch=EXCLUDED.last_full_fetch,last_sync=EXCLUDED.last_sync,
                row_count=EXCLUDED.row_count,newest_session=EXCLUDED.newest_session''',
                [(s,settings.feed,settings.adjustment,v['last_full_fetch'],v['last_sync'],v['row_count'],v['newest_session'])
                 for s,v in states.items()])

    def adopt_legacy(self, symbols, settings, cutoff):
        if settings.feed != 'iex' or settings.adjustment != 'raw':
            raise ValueError('Legacy adoption is only available for explicitly confirmed IEX/raw history.')
        from psycopg.types.json import Jsonb
        with self.connect() as conn:
            rows = conn.execute('''SELECT symbol,bar_timestamp,open,high,low,close,volume,trade_count,vwap
                FROM public.market_snapshots WHERE symbol=ANY(%s) AND timeframe='1Day'
                AND (bar_timestamp AT TIME ZONE 'America/New_York')::date <= %s''', (symbols,cutoff)).fetchall()
            out=[]
            for r in rows:
                bar={'t':r['bar_timestamp'].isoformat(), **{dst:number(r[src]) for src,dst in
                     [('open','o'),('high','h'),('low','l'),('close','c'),('volume','v'),('trade_count','n'),('vwap','vw')]}}
                validate_bar(bar)
                out.append((r['symbol'],'iex','raw',stamp(bar['t']).astimezone(NY).date(),stamp(bar['t']),
                            Jsonb(bar),'user_attested_legacy_iex_raw'))
            with conn.cursor() as cur:
                cur.executemany('''INSERT INTO public.astra_daily_cache
                    (symbol,feed,adjustment,session_date,bar_timestamp,bar,provenance)
                    VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''', out)
        return len(out)  # examined, not a count of newly inserted rows

    def save_context(self, payload):
        from psycopg.types.json import Jsonb
        with self.connect() as conn:
            conn.execute('INSERT INTO public.astra_market_contexts(id,payload) VALUES (%s,%s)',
                         (payload['context_id'],Jsonb(payload)))
        return payload['context_id']

    def context(self, identifier=None):
        with self.connect() as conn:
            if identifier:
                row=conn.execute('SELECT payload FROM public.astra_market_contexts WHERE id=%s',(identifier,)).fetchone()
            else:
                row=conn.execute('SELECT payload FROM public.astra_market_contexts ORDER BY created_at DESC LIMIT 1').fetchone()
        if not row:
            raise ValueError('Capture current context first.')
        return row['payload']


def completed_sessions(calendar, now):
    # A conservative DAILY-bar boundary: only prior New York calendar dates.
    # RTH close alone does not certify a provider daily aggregate is final.
    today=now.astimezone(NY).date()
    dates=sorted({date.fromisoformat(row['date']) for row in calendar if date.fromisoformat(row['date']) < today})
    if not dates:
        raise ValueError('No completed prior-day sessions in the market calendar.')
    return dates


def validate_bar(bar):
    stamp(bar['t'])
    vals=[number(bar.get(k)) for k in ('o','h','l','c')]
    if any(v is None or v <= 0 for v in vals):
        raise ValueError('Invalid or non-positive daily OHLC.')
    o,h,l,c=vals
    if l > min(o,c) or h < max(o,c) or h < l:
        raise ValueError('Inconsistent OHLC range.')
    volume=number(bar.get('v'))
    if volume is None or volume < 0:
        raise ValueError('Invalid daily volume.')


def plan_sync(cache, states, sessions, now, settings, full=False):
    start_full=sessions[-min(len(sessions), settings.backfill_sessions)]
    target=sessions[-1]
    plans=[]
    for symbol,bars in cache.items():
        state=states.get(symbol,{})
        last_full=state.get('last_full_fetch')
        last_sync=state.get('last_sync')
        is_full=full or not bars or (len(bars)<250 and last_full is None)
        if (last_full and now-stamp(last_full)>timedelta(days=settings.full_refresh_days)) or (not last_full and state.get('first_managed_sync') and now-stamp(state['first_managed_sync'])>timedelta(days=settings.full_refresh_days)):
            is_full=True
        newest=max(bars) if bars else None
        recent = sessions[-min(250, len(sessions)):]
        missing = [d for d in recent if d not in bars]
        gap_retry_due = bool(missing and (not last_sync or now-stamp(last_sync) >= timedelta(days=1)))
        if not is_full and newest==target and last_sync and now-stamp(last_sync)<timedelta(hours=6) and not gap_retry_due:
            continue
        if is_full:
            start=start_full
        else:
            earlier=[d for d in sessions if newest is not None and d<=newest]
            start=earlier[-min(len(earlier),5)] if earlier else start_full
            # Cover recent holes, not just the last date. Delisted/newly listed
            # series can remain short; their last full fetch is tracked.
            recent=sessions[-min(250,len(sessions)):]
            missing=[d for d in recent if d not in bars]
            if missing and (last_full is None or gap_retry_due):
                start=min(start, missing[0])
        plans.append({'symbol':symbol,'start':start,'end':target,'full':is_full})
    return plans


def sync_history(api, store, symbols, settings, *, force_full=False):
    started=time.perf_counter()
    now=utcnow()
    calendar=api.calendar(now.astimezone(NY).date()-timedelta(days=1200),now.astimezone(NY).date())
    sessions=completed_sessions(calendar,now)
    cache,states=store.load_cache(symbols,settings)
    plans=plan_sync(cache,states,sessions,now,settings,force_full)
    plans.sort(key=lambda p: (p['start'], p['symbol']))
    print(f'Universe: {len(symbols)}; due: {len(plans)}; unchanged/skipped: {len(symbols)-len(plans)}; target: {sessions[-1]}')
    saved=0
    failed=[]
    from itertools import groupby
    groups = []
    for _, same_start in groupby(plans, key=lambda p: p['start']):
        same_start = list(same_start)
        groups.extend(same_start[i:i+settings.batch_size]
                      for i in range(0, len(same_start), settings.batch_size))
    for batch_index, group in enumerate(groups, start=1):
        group_symbols=[p['symbol'] for p in group]
        try:
            data=api.bars(group_symbols,min(p['start'] for p in group),sessions[-1],settings)
            records=[]
            state_updates={}
            for p in group:
                symbol=p['symbol']; merged=dict(cache[symbol]); local_records=[]; did_full=p['full']
                try:
                    incoming=data[symbol]
                    # Split-adjusted history can be revised after a corporate action.
                    # Any revised overlap triggers a complete rolling-window refetch.
                    if settings.adjustment=='split' and not did_full:
                        changed=False
                        for b in incoming:
                            d=stamp(b['t']).astimezone(NY).date()
                            if d in merged and any(number(merged[d].get(k))!=number(b.get(k)) for k in ('o','h','l','c','v')):
                                changed=True; break
                        if changed:
                            start_full=sessions[-min(len(sessions),settings.backfill_sessions)]
                            incoming=api.bars([symbol],start_full,sessions[-1],settings)[symbol]
                            p['start']=start_full; did_full=True
                    for bar in incoming:
                        d=stamp(bar['t']).astimezone(NY).date()
                        if not p['start']<=d<=p['end'] or d not in sessions:
                            continue
                        validate_bar(bar)
                        merged[d]=bar
                        local_records.append((symbol,d,bar))
                    if not local_records:
                        raise ValueError('No bars returned for requested window.')
                except (ValueError, KeyError, TypeError) as error:
                    failed.append(symbol)
                    print(f'{symbol}: not saved: {error}')
                    continue
                records.extend(local_records)
                previous=states.get(symbol,{})
                state_updates[symbol]={'last_full_fetch':now if did_full else previous.get('last_full_fetch'),
                                      'last_sync':now,'row_count':len(merged),'newest_session':max(merged)}
            if records:
                store.save_group(records,state_updates,settings)
            saved+=len(records)
            print(f'Batch {batch_index}: {len(state_updates)} symbols; {len(records)} bars upserted in one transaction.')
        except Exception as error:
            failed.extend(s for s in group_symbols if s not in failed)
            print(f'Batch failed ({type(error).__name__}: {error}). No partial batch committed; rerun resumes other completed batches.')
    print(f'Upserted bars: {saved}; failed symbols: {len(failed)}; HTTP reads: {api.requests_made}; elapsed: {time.perf_counter()-started:.1f}s')
    return failed


def wilder(series, period=14):
    """Explicit Wilder seed: first full period SMA, then recursive smoothing."""
    values=series.to_numpy(dtype=float); result=np.full(len(values),np.nan)
    valid=np.where(np.isfinite(values))[0]
    if len(valid)<period:
        return pd.Series(result,index=series.index)
    start=valid[0]
    if start+period>len(values) or not np.isfinite(values[start:start+period]).all():
        return pd.Series(result,index=series.index)
    seed=start+period-1
    result[seed]=values[start:seed+1].mean()
    for i in range(seed+1,len(values)):
        if np.isfinite(values[i]):
            result[i]=(result[i-1]*(period-1)+values[i])/period
    return pd.Series(result,index=series.index)


def features(bars, target, required_sessions):
    expected=required_sessions[-201:]
    if len(expected)<201 or any(d not in bars for d in expected) or max(bars)<target:
        raise ValueError('Need 201 aligned completed daily sessions; missing data is not forward-filled.')
    df=pd.DataFrame([{'date':d, **b} for d,b in sorted(bars.items()) if d<=target]).set_index('date').tail(450)
    for key in ('o','h','l','c','v'):
        df[key]=pd.to_numeric(df[key],errors='raise')
    close=df['c']; delta=close.diff()
    gain=wilder(delta.clip(lower=0)); loss=wilder(-delta.clip(upper=0))
    rsi=100-100/(1+gain/loss.replace(0,np.nan))
    rsi=rsi.mask((loss==0)&(gain>0),100).mask((gain==0)&(loss>0),0).mask((gain==0)&(loss==0),50)
    tr=pd.concat([df.h-df.l,(df.h-close.shift()).abs(),(df.l-close.shift()).abs()],axis=1).max(axis=1)
    atr=wilder(tr); macd=close.ewm(span=12,adjust=False).mean()-close.ewm(span=26,adjust=False).mean()
    signal=macd.ewm(span=9,adjust=False).mean()
    price=float(close.iloc[-1]); avgvol=float(df.v.tail(20).mean())
    result={'price':price,'return_1d':100*(price/close.iloc[-2]-1),
            'return_5d':100*(price/close.iloc[-6]-1),'return_20d':100*(price/close.iloc[-21]-1),
            'rsi_14':rsi.iloc[-1], 'atr_pct':100*atr.iloc[-1]/price,
            'volume_ratio':float(df.v.iloc[-1]/avgvol) if avgvol>0 else None,
            'avg_volume_20':avgvol,'atr_14':atr.iloc[-1], 'macd':macd.iloc[-1],
            'macd_histogram':macd.iloc[-1]-signal.iloc[-1],
            'sma_20':close.tail(20).mean(),'sma_50':close.tail(50).mean(),'sma_200':close.tail(200).mean(),
            'high_20':df.h.tail(20).max(),'low_20':df.l.tail(20).min(),
            'session_date':target.isoformat(),'bar_timestamp':df.iloc[-1]['t'],
            'max_abs_daily_return_20d_pct':float(close.pct_change().tail(20).abs().max()*100),
            'feature_window_bars':len(df),
            'history_provenance':sorted({b.get('_provenance','alpaca_api') for d,b in bars.items() if d<=target})}
    return jsonable(result)


def quote_context(snapshot, now, max_age, market_open):
    quote=snapshot.get('latestQuote') or {}; trade=snapshot.get('latestTrade') or {}
    bid=number(quote.get('bp')); ask=number(quote.get('ap'))
    def age(item):
        try:
            return (now-stamp(item['t'])).total_seconds()
        except (ValueError, KeyError, TypeError):
            return None
    quote_age=age(quote); trade_age=age(trade)
    valid=bid is not None and ask is not None and bid>0 and ask>=bid
    fresh=bool(valid and quote_age is not None and -2<=quote_age<=max_age)
    mid=(bid+ask)/2 if valid else None
    daily=snapshot.get('dailyBar') or {}; previous=snapshot.get('prevDailyBar') or {}
    previous_close=number(previous.get('c')); opening=number(daily.get('o'))
    try:
        daily_date=stamp(daily['t']).astimezone(NY).date()
    except (KeyError,ValueError,TypeError):
        daily_date=None
    is_current_daily=daily_date==now.astimezone(NY).date()
    return {'received_at':now.isoformat(),'quote_timestamp':quote.get('t'),'trade_timestamp':trade.get('t'),
            'quote_age_seconds':quote_age,'trade_age_seconds':trade_age,
            'bid':bid,'ask':ask,'midpoint':mid,'last_trade':number(trade.get('p')),
            'spread_bps':(ask-bid)/mid*10000 if mid else None,
            'quote_fresh':fresh,'regular_market_open':bool(market_open),
            'executable_quote_check':bool(fresh and market_open),
            'change_from_previous_daily_close_pct':100*(mid/previous_close-1) if mid and previous_close else None,
            'change_from_daily_open_pct':100*(mid/opening-1) if mid and opening and is_current_daily else None,
            'daily_bar_session_date':daily_date.isoformat() if daily_date else None,
            'daily_bar_is_current_day':is_current_daily,
            'daily_bar_may_be_partial':is_current_daily,
            'snapshot':snapshot,
            'note':'Intraday bars are separate from completed daily indicators. No full-day relative-volume inference.'}


def capture_context(api,store,settings,universe,*,per_sector=3,extra=5):
    """Fresh numerical screen; old scanner output is NOT silently reused."""
    now=utcnow(); entries=universe['stocks']
    symbols=sorted({s['symbol'] for s in entries}|{'SPY','QQQ'})
    sessions=completed_sessions(api.calendar(now.date()-timedelta(days=400),now.astimezone(NY).date()),now)
    target=sessions[-1]; cache,_=store.load_cache(symbols,settings)
    bench={s:features(cache[s],target,sessions) for s in ('SPY','QQQ')}
    assets={a['symbol']:a for a in api.assets()}
    metadata={item['symbol']:item for item in entries}
    candidates=[]; excluded={}
    for symbol in sorted(metadata):
        asset=assets.get(symbol,{})
        if symbol in {'SPY','QQQ'}:
            continue
        if asset.get('status')!='active' or not asset.get('tradable') or asset.get('class')!='us_equity':
            excluded[symbol]='Not confirmed active/tradable US equity'; continue
        try:
            q=features(cache[symbol],target,sessions)
        except ValueError as error:
            excluded[symbol]=str(error); continue
        q['relative_strength_spy']=q['return_20d']-bench['SPY']['return_20d']
        q['relative_strength_qqq']=q['return_20d']-bench['QQQ']['return_20d']
        q['momentum_score']=q['return_5d']*.35+q['return_20d']*.45+q['relative_strength_spy']*.1+q['relative_strength_qqq']*.1
        q['technical_score']=q['momentum_score']+sum(2 for p in (20,50,200) if q['price']>q[f'sma_{p}'])+min(q['volume_ratio'] or 0,3)
        candidates.append({'symbol':symbol,'sector':metadata[symbol].get('sector','Unknown'),
                           'industry':metadata[symbol].get('industry'), 'quantitative':q})
    candidates.sort(key=lambda c:(-c['quantitative']['technical_score'],c['symbol']))
    selected=[]; counts={}
    for c in candidates:
        if counts.get(c['sector'],0)<per_sector:
            selected.append(c); counts[c['sector']]=counts.get(c['sector'],0)+1
    chosen={c['symbol'] for c in selected}
    selected += [c for c in candidates if c['symbol'] not in chosen][:extra]
    selected.sort(key=lambda c:(-c['quantitative']['technical_score'],c['symbol']))
    if not selected:
        raise ValueError('No eligible current candidates. Sync missing history; do not treat this as NO TRADES advice.')
    news_errors={}
    for c in selected:
        try:
            c['recent_news'],c['news_sample_truncated']=api.news(c['symbol'],utcnow())
            c['news_fetch_status']='ok'
        except AlpacaReadError as error:
            c['recent_news']=[]; c['news_fetch_status']='failed'
            news_errors[c['symbol']]=str(error)
    account,positions,orders=api.account_context()
    # Snapshot fetch is last so news-request latency does not unnecessarily age quotes.
    current=api.get('/v2/stocks/snapshots',{'symbols':','.join(sorted({c['symbol'] for c in selected}|{'SPY','QQQ'})),'feed':settings.feed})
    clock=api.get('/v2/clock',trading=True); received=utcnow()
    if abs((received-stamp(clock['timestamp'])).total_seconds())>60:
        raise ValueError('Local and Alpaca clock differ by over one minute.')
    for c in selected:
        c['live_market']=quote_context(current.get(c['symbol'],{}),received,settings.quote_max_age,clock['is_open'])
        c['market_context']={s:{'daily':bench[s], 'live':quote_context(current.get(s,{}),received,settings.quote_max_age,clock['is_open'])} for s in ('SPY','QQQ')}
        c['earnings_calendar']={'status':'not_connected'}
        c['social_signals']={'status':'not_connected','source':'Blossom'}
    safe_account={k:account.get(k) for k in ('status','currency','cash','equity','buying_power',
                                         'trading_blocked','account_blocked','trade_suspended_by_user')}
    safe_positions=[{k:p.get(k) for k in ('symbol','qty','side','market_value','unrealized_pl','current_price')} for p in positions]
    safe_orders=[{k:o.get(k) for k in ('symbol','qty','filled_qty','side','type','status','limit_price','stop_price')} for o in orders]
    payload={'context_id':str(uuid4()),'version':VERSION,'captured_at':received.isoformat(),
             'daily_target_session':target.isoformat(),'daily_cutoff_rule':'prior New York calendar dates only',
             'feed':settings.feed,'adjustment':settings.adjustment,'market_clock':clock,
             'account':safe_account,'positions':safe_positions,'open_orders':safe_orders,
             'universe_count':len(metadata),'screened_count':len(candidates),'excluded':excluded,
             'sector_counts':counts,'candidates':selected,'news_errors':news_errors,
             'limitations':['Only the sector shortlist receives model review, not every screened symbol.',
                            'News is a capped provider sample; earnings calendar and Blossom are not connected.',
                            'No learned trading model, independent validation of signals, or proven profitability.',
                            'Quote timestamps can be stale even when a snapshot HTTP request just succeeded.',
                            'Raw series can contain corporate-action discontinuities; split series need periodic rebasing.',
                            'Paper simulation does not establish real-market execution quality.']}
    payload=jsonable(payload); store.save_context(payload)
    return payload
