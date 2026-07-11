"""موتور یکپارچه استراتژی ۱۵ دقیقه‌ای.

تصمیم نهایی از یک سناریوی واحد ساخته می‌شود؛ جهت، قدرت، تازگی، ورود و ایمنی
فقط شواهد هستند و هیچ‌کدام مستقل معامله صادر نمی‌کنند. واچ خرد OKX صرفاً
برای revalidation اجرای زنده است و معماری کندلی را بازنویسی نمی‌کند.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Any
import math
import time

import config


@dataclass
class StrategySignal:
    symbol_id: str
    okx_symbol: str
    toobit_symbol: str
    side: str
    entry: float
    strength: str
    strength_score: float
    compression_score: float
    flow_bias: float
    absorption_score: float
    reason: str
    diagnostic_context: dict[str, Any] = field(default_factory=dict)


@dataclass
class WatchCandidate:
    side: str
    trigger: str
    start_price: float
    early_flow: float
    compression_score: float
    volume_ratio: float
    range_ratio: float
    expected_move_pct: float
    late_limit_pct: float
    details: dict[str, float | str] = field(default_factory=dict)


@dataclass
class WatchState:
    symbol_id: str
    okx_symbol: str
    toobit_symbol: str
    side: str
    trigger: str
    start_price: float
    created_at: float
    expected_move_pct: float
    late_limit_pct: float
    early_flow: float
    compression_score: float
    direction_locked: bool = False
    side_changes: int = 0
    confirm_count: int = 0
    bad_count: int = 0
    data_error_count: int = 0
    last_price: float = 0.0
    last_update: float = 0.0
    trade_history: list[float] = field(default_factory=list)
    book_history: list[float] = field(default_factory=list)
    response_history: list[float] = field(default_factory=list)
    intensity_history: list[float] = field(default_factory=list)
    last_snapshot_trade_ts: int = 0
    evidence_score: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class WatchEvaluation:
    action: str
    reason_fa: str
    side: str
    signal: StrategySignal | None
    metrics: dict[str, float | str]


@dataclass
class StrategyAnalysisResult:
    signal: StrategySignal | None
    reject_reason: str
    details: dict[str, float | str]


def _safe_median(xs: list[float], default: float = 0.0) -> float:
    return median(xs) if xs else default


def pct_range(c: dict[str, float]) -> float:
    close = float(c.get("close") or 0.0)
    return (float(c["high"]) - float(c["low"])) / close * 100.0 if close > 0 else 0.0


def _volume(c: dict[str, float]) -> float:
    return max(float(c.get("vol_quote") or c.get("volume") or 0.0), 0.0)


def _closed(candles: list[dict[str, float]]) -> list[dict[str, float]]:
    return [c for c in candles if int(c.get("confirm", 1)) == 1]


def _ema(values: list[float], period: int) -> list[float]:
    if not values: return []
    alpha = 2.0 / (period + 1.0)
    out = [values[0]]
    for v in values[1:]: out.append(alpha * v + (1 - alpha) * out[-1])
    return out


def _atr(candles: list[dict[str, float]], period: int = 14) -> list[float]:
    if not candles: return []
    trs: list[float] = []
    prev = float(candles[0]["close"])
    for c in candles:
        h,l = float(c["high"]), float(c["low"])
        trs.append(max(h-l, abs(h-prev), abs(l-prev)))
        prev = float(c["close"])
    return _ema(trs, period)


def _resample_1h(candles: list[dict[str, float]]) -> list[dict[str, float]]:
    out=[]; bucket=[]; key=None
    for c in candles:
        ts=int(c["ts"]); k=ts//3_600_000
        if key is None: key=k
        if k != key:
            if len(bucket)==4:
                out.append({"ts":bucket[0]["ts"],"open":bucket[0]["open"],"high":max(x["high"] for x in bucket),
                            "low":min(x["low"] for x in bucket),"close":bucket[-1]["close"],"volume":sum(_volume(x) for x in bucket),"confirm":1})
            bucket=[]; key=k
        bucket.append(c)
    if len(bucket)==4:
        out.append({"ts":bucket[0]["ts"],"open":bucket[0]["open"],"high":max(x["high"] for x in bucket),
                    "low":min(x["low"] for x in bucket),"close":bucket[-1]["close"],"volume":sum(_volume(x) for x in bucket),"confirm":1})
    return out


def _swing_points(candles: list[dict[str,float]], atrs: list[float]) -> tuple[list[tuple[int,float]], list[tuple[int,float]]]:
    highs=[]; lows=[]
    for i in range(2, len(candles)-2):
        h=float(candles[i]["high"]); l=float(candles[i]["low"])
        if h>float(candles[i-1]["high"]) and h>float(candles[i-2]["high"]) and h>=float(candles[i+1]["high"]) and h>=float(candles[i+2]["high"]):
            follow=min(float(x["low"]) for x in candles[i+1:min(len(candles),i+6)])
            if h-follow >= max(h*0.003, atrs[i]*float(config.SWING_VALIDATION_ATR)): highs.append((i,h))
        if l<float(candles[i-1]["low"]) and l<float(candles[i-2]["low"]) and l<=float(candles[i+1]["low"]) and l<=float(candles[i+2]["low"]):
            follow=max(float(x["high"]) for x in candles[i+1:min(len(candles),i+6)])
            if follow-l >= max(l*0.003, atrs[i]*float(config.SWING_VALIDATION_ATR)): lows.append((i,l))
    return highs,lows


def _pressure(candles: list[dict[str,float]], lookback: int) -> tuple[float,float,float]:
    xs=candles[-lookback:]
    ranges=[max(float(c["high"])-float(c["low"]),1e-12) for c in xs]
    cap=2.0*(_safe_median(ranges,1e-9) or 1e-9)
    bull=bear=path=0.0
    for c,r in zip(xs,ranges):
        eff=min(r,cap)/r
        body=(float(c["close"])-float(c["open"]))/r
        close_loc=((float(c["close"])-float(c["low"]))/r-0.5)*2.0
        val=(0.65*body+0.35*close_loc)*eff
        if val>=0: bull+=val
        else: bear+=-val
        path += abs(float(c["close"])-float(c["open"]))
    delta=(bull-bear)/max(bull+bear,1e-9)
    net=abs(float(xs[-1]["close"])-float(xs[0]["open"])) if xs else 0.0
    efficiency=net/max(path,1e-9)
    return delta,bull/max(bull+bear,1e-9),efficiency


def _obstacle_distance(
    highs: list[tuple[int, float]], lows: list[tuple[int, float]], side: str, price: float
) -> float:
    """فاصله تا نزدیک‌ترین مانع ساختاری تأییدشده، نه هر High/Low تصادفی کندل.

    استفاده از تمام سقف‌ها و کف‌های ۸۰ کندل تقریباً همیشه یک مانع بسیار نزدیک
    می‌ساخت و براکت ۰.۹٪ را به‌اشتباه نامعتبر می‌کرد.
    """
    if side == "LONG":
        levels = sorted({float(level) for _, level in highs if float(level) > price})
        return ((levels[0] - price) / price * 100.0) if levels else 99.0
    levels = sorted({float(level) for _, level in lows if float(level) < price}, reverse=True)
    return ((price - levels[0]) / price * 100.0) if levels else 99.0


def _build_scenario(candles: list[dict[str,float]], side: str) -> dict[str,Any]:
    closes=[float(c["close"]) for c in candles]
    atrs=_atr(candles, config.ATR_PERIOD); atr=max(atrs[-1],1e-12); price=closes[-1]
    ema20=_ema(closes,config.EMA_FAST); ema50=_ema(closes,config.EMA_SLOW)
    highs,lows=_swing_points(candles,atrs)
    last_h=highs[-2:] if len(highs)>=2 else highs
    last_l=lows[-2:] if len(lows)>=2 else lows
    delta,bull_share,eff=_pressure(candles,config.PRESSURE_LOOKBACK)
    sign=1 if side=="LONG" else -1

    structure=0.0; structural="MIXED"
    if len(last_h)>=2 and len(last_l)>=2:
        hh=last_h[-1][1]>last_h[-2][1]; hl=last_l[-1][1]>last_l[-2][1]
        lh=last_h[-1][1]<last_h[-2][1]; ll=last_l[-1][1]<last_l[-2][1]
        if hh and hl: structural="LONG"
        elif lh and ll: structural="SHORT"
        elif (hh and ll) or (lh and hl): structural="MIXED"
        if side=="LONG": structure=45.0 if structural=="LONG" else (25.0 if hh or hl else 5.0)
        else: structure=45.0 if structural=="SHORT" else (25.0 if lh or ll else 5.0)

    level=(last_h[-1][1] if side=="LONG" and last_h else last_l[-1][1] if side=="SHORT" and last_l else price)
    buffer=max(price*0.0005, atr*float(config.BREAK_BUFFER_ATR))
    close_break=(price>level+buffer) if side=="LONG" else (price<level-buffer)
    prev_close=float(candles[-2]["close"])
    accepted=close_break and ((prev_close>level) if side=="LONG" else (prev_close<level))
    pressure_aligned=max(0.0, sign*delta)
    acceptance=30.0*(0.45*(1 if close_break else 0)+0.35*(1 if accepted else 0)+0.20*pressure_aligned)

    oneh=_resample_1h(candles)
    htf=10.0
    wind="NEUTRAL"
    if len(oneh)>=55:
        hc=[float(c["close"]) for c in oneh]; hema=_ema(hc,50)
        slope=(hema[-1]-hema[-6])/max(hema[-6],1e-12)
        aligned=(hc[-1]>hema[-1] and slope>0) if side=="LONG" else (hc[-1]<hema[-1] and slope<0)
        opposite=(hc[-1]<hema[-1] and slope<0) if side=="LONG" else (hc[-1]>hema[-1] and slope>0)
        if aligned: htf=20.0; wind="TAILWIND"
        elif opposite: htf=3.0; wind="HEADWIND"

    ema_aligned=(ema20[-1]>ema50[-1] and price>ema20[-1]) if side=="LONG" else (ema20[-1]<ema50[-1] and price<ema20[-1])
    ema_score=5.0 if ema_aligned else 1.0
    direction_score=structure+acceptance+htf+ema_score

    # قدرت: impulse, acceptance, persistence, efficiency
    recent=candles[-4:]
    impulse_range=(max(float(c["high"]) for c in recent)-min(float(c["low"]) for c in recent))/atr
    impulse=min(100.0, max(0.0, 35+impulse_range*28+pressure_aligned*30))
    acceptance_score=min(100.0, max(0.0, (70 if accepted else 42 if close_break else 18)+pressure_aligned*25))
    persistence=min(100.0,max(0.0,50+sign*delta*42))
    efficiency_score=min(100.0,max(0.0,eff*125))
    strength=0.25*impulse+0.30*acceptance_score+0.25*persistence+0.20*efficiency_score

    # تازگی از مبدأ آخرین swing مخالف
    origin_idx=(last_l[-1][0] if side=="LONG" and last_l else last_h[-1][0] if side=="SHORT" and last_h else len(candles)-2)
    origin_price=(last_l[-1][1] if side=="LONG" and last_l else last_h[-1][1] if side=="SHORT" and last_h else prev_close)
    age=max(0,len(candles)-1-origin_idx)
    distance=abs(price-origin_price)/atr
    time_score=max(0.0,100-age*16)
    dist_score=max(0.0,100-distance*58)
    structural_score=max(0.0,100-max(0,age-1)*13)
    obstacle=_obstacle_distance(highs,lows,side,price)
    opportunity_score=min(100.0,max(0.0,obstacle/max(config.MIN_CLEAR_PATH_PCT,1e-9)*75))
    freshness=0.20*time_score+0.25*dist_score+0.25*structural_score+0.30*opportunity_score

    # ورود: شکست مستقیم یا اولین پولبک ساده
    current=candles[-1]; rng=max(float(current["high"])-float(current["low"]),1e-12)
    body_ratio=abs(float(current["close"])-float(current["open"]))/rng
    close_loc=(float(current["close"])-float(current["low"]))/rng
    close_good=close_loc>=0.70 if side=="LONG" else close_loc<=0.30
    range_atr=rng/atr
    direct=accepted and 0.55<=body_ratio and 0.55<=range_atr<=1.35 and close_good
    # pullback پایان‌یافته: کندل قبل خلاف جهت و کندل فعلی trigger را شکسته
    prev=candles[-2]
    prev_opposite=(float(prev["close"])<float(prev["open"])) if side=="LONG" else (float(prev["close"])>float(prev["open"]))
    trigger=(float(current["close"])>float(prev["high"])) if side=="LONG" else (float(current["close"])<float(prev["low"]))
    pullback=prev_opposite and trigger and body_ratio>=0.45 and close_good
    entry_type="DIRECT_BREAKOUT" if direct else "FIRST_PULLBACK" if pullback else "WAIT"
    location=max(0.0,min(100.0,100-distance*55))
    trigger_score=90.0 if direct or pullback else 35.0
    # ابطال ورود باید به ساختار محلی همان ورود متصل باشد، نه لزوماً مبدأ کامل موج.
    # استفاده از origin قدیمی تقریباً همه ستاپ‌ها را با SL ثابت ناسازگار نشان می‌داد.
    recent_window=candles[-4:]
    if side=="LONG":
        micro_invalidation=min(float(c["low"]) for c in recent_window)
        breakout_invalidation=level-buffer
        invalidation_level=breakout_invalidation if direct else micro_invalidation if pullback else max(micro_invalidation, breakout_invalidation)
        invalidation_distance=max(0.0,(price-invalidation_level)/price*100.0)
    else:
        micro_invalidation=max(float(c["high"]) for c in recent_window)
        breakout_invalidation=level+buffer
        invalidation_level=breakout_invalidation if direct else micro_invalidation if pullback else min(micro_invalidation, breakout_invalidation)
        invalidation_distance=max(0.0,(invalidation_level-price)/price*100.0)
    invalidation=90.0 if invalidation_distance<=config.FIXED_SL_PCT_15M else max(0.0,70-(invalidation_distance-config.FIXED_SL_PCT_15M)*100)
    atr_pct=atr/price*100.0
    atr_eligible=config.MIN_FIXED_BRACKET_ATR_PCT<=atr_pct<=config.MAX_FIXED_BRACKET_ATR_PCT
    obstacle_ok=obstacle>=config.MIN_CLEAR_PATH_PCT
    bracket_ok=atr_eligible and obstacle_ok
    execution=85.0 if bracket_ok else 50.0 if atr_eligible else 25.0
    entry_score=0.30*location+0.30*trigger_score+0.25*invalidation+0.15*execution

    # ایمنی محیط مستقل: کارایی، نویز سایه، رنج و براکت
    wick_ratios=[]
    for c in candles[-8:]:
        rr=max(float(c["high"])-float(c["low"]),1e-12)
        wick=(rr-abs(float(c["close"])-float(c["open"])))/rr
        wick_ratios.append(wick)
    wick_noise=_safe_median(wick_ratios,0.5)
    safety=max(0.0,min(100.0,45+eff*45-wick_noise*20+(15 if bracket_ok else -20)))

    # جهت تأییدشده یا یک شکست نوظهورِ همسو می‌تواند وارد WATCH شود.
    emerging_direction=close_break and wind!="HEADWIND" and pressure_aligned>=0.20
    direction_integrity=(structural==side or emerging_direction) and not (wind=="HEADWIND" and not accepted)
    trigger_valid=entry_type!="WAIT"
    invalidation_ok=invalidation_distance<=config.FIXED_SL_PCT_15M*1.05
    feasibility=bracket_ok
    coherence=1.0
    if not accepted: coherence-=0.08
    if wind=="HEADWIND": coherence-=0.10
    if pressure_aligned<0.15: coherence-=0.07
    coherence=max(0.70,coherence)
    # امتیاز ستاپ عمداً Entry Trigger را شامل نمی‌کند؛ تریگر در WATCH زنده تکمیل می‌شود.
    setup_base=0.30*direction_score+0.25*strength+0.25*freshness+0.20*safety
    setup_score=setup_base*coherence
    base=0.25*direction_score+0.20*strength+0.20*freshness+0.25*entry_score+0.10*safety
    final=base*coherence

    return {
        "side":side,"structural_direction":structural,"direction_score":round(direction_score,2),"strength_score":round(strength,2),
        "freshness_score":round(freshness,2),"entry_score":round(entry_score,2),"safety_score":round(safety,2),
        "setup_score":round(setup_score,2),"final_score":round(final,2),"coherence":round(coherence,3),"accepted":accepted,"close_break":close_break,
        "entry_type":entry_type,"direction_integrity":direction_integrity,"trigger_valid":trigger_valid,
        "invalidation_ok":invalidation_ok,"feasibility":feasibility,"obstacle_pct":round(obstacle,4),
        "obstacle_ok":obstacle_ok,"atr_eligible":atr_eligible,"invalidation_level":round(invalidation_level,10),
        "invalidation_distance_pct":round(invalidation_distance,4),
        "atr_pct":round(atr_pct,4),"age_bars":age,"distance_atr":round(distance,4),"one_hour_wind":wind,
        "origin_price":origin_price,"breakout_level":level,"flow":round(delta,4),"efficiency":round(eff,4),
        "bracket_ok":bracket_ok,
    }


def detect_watch_candidate(candles: list[dict[str,float]]) -> tuple[WatchCandidate|None,str,dict[str,float|str]]:
    """ستاپ کندلی را برای ورود به WATCH انتخاب می‌کند.

    نکته معماری: WATCH مرحله قبل از تریگر ورود است. بنابراین نبود تریگر کندلی
    نباید ستاپ را حذف کند؛ تریگر و اجرای نهایی در evaluate_watch با داده زنده
    دوباره اعتبارسنجی می‌شود.
    """
    closed=_closed(candles)
    if len(closed)<80:
        return None,"داده کندلی بسته‌شده کافی نیست",{"تعداد_کندل":len(closed)}
    long_s=_build_scenario(closed,"LONG"); short_s=_build_scenario(closed,"SHORT")
    winner=long_s if long_s["setup_score"]>=short_s["setup_score"] else short_s
    loser=short_s if winner is long_s else long_s
    edge=winner["setup_score"]-loser["setup_score"]
    details={
        "امتیاز_لانگ":long_s["setup_score"],"امتیاز_شورت":short_s["setup_score"],"اختلاف":round(edge,2),
        "امتیاز_ستاپ":winner["setup_score"],"امتیاز_نهایی_فعلی":winner["final_score"],
        "جهت":winner["direction_score"],"قدرت":winner["strength_score"],"تازگی":winner["freshness_score"],
        "ورود":winner["entry_score"],"ایمنی":winner["safety_score"],"نوع_ورود":winner["entry_type"],
        "فاصله_مانع":winner["obstacle_pct"],"ATR_درصد":winner["atr_pct"],
        "فاصله_ابطال":winner["invalidation_distance_pct"],
    }
    if not winner["direction_integrity"]:
        return None,"یکپارچگی جهت معتبر نبود",details
    if winner["direction_score"]<config.WATCH_DIRECTION_MIN_SCORE:
        return None,"جهت هنوز برای ورود به واچ به‌اندازه کافی روشن نیست",details
    if winner["strength_score"]<config.WATCH_STRENGTH_MIN_SCORE:
        return None,"قدرت حرکت برای ورود به واچ کافی نیست",details
    if winner["freshness_score"]<config.WATCH_FRESHNESS_MIN_SCORE:
        return None,"حرکت برای ورود به واچ بیش‌ازحد مصرف شده است",details
    if winner["setup_score"]<config.WATCH_SETUP_MIN_SCORE or edge<config.WATCH_SETUP_MIN_EDGE:
        return None,"ستاپ برنده یا برتری آن برای واچ کافی نیست",details
    # ATR نامناسب از ابتدا قابل اصلاح نیست؛ مانع و ابطال در لحظه اجرای نهایی هم بازبینی می‌شوند.
    if not winner["atr_eligible"]:
        return None,"نوسان بازار با براکت ثابت سازگار نیست",details
    current=float(closed[-1]["close"])
    late=max(config.WATCH_LATE_MIN_PCT,min(config.WATCH_LATE_MAX_PCT,config.FIXED_TP_PCT_15M*config.WATCH_LATE_EXPECTED_FRACTION))
    trigger_text=(f"سناریوی یکپارچه {winner['entry_type']}" if winner["trigger_valid"]
                  else "ستاپ معتبر؛ انتظار تریگر اجرای زنده")
    return WatchCandidate(winner["side"],trigger_text,current,winner["flow"],
                          max(0.0,min(1.0,1-winner["efficiency"])),1.0,1.0,config.FIXED_TP_PCT_15M,late,
                          {**details,"scenario":winner}),"ورود به واچ اجرای زنده",details


def _trim_append(xs:list[float],v:float,limit:int)->None:
    xs.append(float(v));
    if len(xs)>limit: del xs[:-limit]


def evaluate_watch(state:WatchState,snapshot:dict[str,Any],now:float|None=None)->WatchEvaluation:
    """واچ فقط revalidation اجرای زنده است؛ حق تغییر جهت کندلی را ندارد."""
    now=now or time.time(); age=now-state.created_at
    price=float(snapshot.get("mid_price") or snapshot.get("last_price") or 0.0)
    if price<=0: return WatchEvaluation("KEEP","قیمت معتبر دریافت نشد",state.side,None,{"سن_واچ":round(age,1)})
    newest=int(float(snapshot.get("newest_trade_ts") or 0.0))
    if newest and newest<=state.last_snapshot_trade_ts:
        return WatchEvaluation("KEEP","نمونه خرد تازه نرسیده",state.side,None,{"سن_واچ":round(age,1)})
    state.last_snapshot_trade_ts=newest
    trade=float(snapshot.get("trade_imbalance") or 0.0); book=float(snapshot.get("book_imbalance") or 0.0)
    accel=float(snapshot.get("intensity_acceleration") or 0.0)
    response=(price-state.start_price)/max(state.start_price,1e-9)*100.0
    aligned_trade=trade if state.side=="LONG" else -trade
    aligned_book=book if state.side=="LONG" else -book
    aligned_response=response if state.side=="LONG" else -response
    _trim_append(state.trade_history,aligned_trade,config.WATCH_DIRECTION_HISTORY)
    _trim_append(state.book_history,aligned_book,config.WATCH_DIRECTION_HISTORY)
    _trim_append(state.response_history,aligned_response,config.WATCH_DIRECTION_HISTORY)
    _trim_append(state.intensity_history,accel,config.WATCH_DIRECTION_HISTORY)
    metrics={"سن_واچ_ثانیه":round(age,1),"فشار_همجهت":round(aligned_trade,4),"دفتر_همجهت":round(aligned_book,4),
             "پاسخ_قیمت":round(aligned_response,4),"شتاب":round(accel,4)}
    if age>config.WATCH_TTL_SECONDS: return WatchEvaluation("REMOVE","واچ منقضی شد",state.side,None,metrics)
    if abs(response)>state.late_limit_pct: return WatchEvaluation("REMOVE","قیمت پیش از اجرا بیش‌ازحد جابه‌جا شد",state.side,None,metrics)
    contradiction=aligned_trade<-config.WATCH_TRADE_IMBALANCE_MIN and aligned_response<-config.WATCH_MAX_ADVERSE_RESPONSE_PCT
    state.bad_count=state.bad_count+1 if contradiction else max(0,state.bad_count-1)
    if state.bad_count>=config.WATCH_BAD_OBSERVATIONS_TO_REMOVE:
        return WatchEvaluation("REMOVE","جهت کندلی با جریان و پاسخ زنده باطل شد",state.side,None,metrics)
    needed=config.WATCH_STRONG_CONFIRMATIONS_REQUIRED if (aligned_trade>=config.WATCH_STRONG_TRADE_IMBALANCE and accel>=config.WATCH_INTENSITY_ACCEL_MIN) else config.WATCH_CONFIRMATIONS_REQUIRED
    confirm=aligned_trade>=config.WATCH_TRADE_IMBALANCE_MIN and aligned_response>=-config.WATCH_MAX_ADVERSE_RESPONSE_PCT and (aligned_book>=-config.WATCH_STRONG_BOOK_IMBALANCE)
    state.confirm_count=state.confirm_count+1 if confirm else max(0,state.confirm_count-1)
    if state.confirm_count<needed:
        return WatchEvaluation("KEEP",f"تأیید اجرای زنده {state.confirm_count} از {needed}",state.side,None,metrics)
    scenario=state.details.get("scenario",{}) if isinstance(state.details,dict) else {}
    setup_score=float(scenario.get("setup_score") or 0.0)
    if setup_score<float(config.SIGNAL_SETUP_MIN_SCORE):
        return WatchEvaluation("REMOVE","کیفیت ستاپ در بازبینی نهایی کافی نبود",state.side,None,{**metrics,"امتیاز_ستاپ":round(setup_score,2)})
    if not bool(scenario.get("invalidation_ok",False)):
        return WatchEvaluation("REMOVE","استاپ ثابت با ابطال محلی سازگار نیست",state.side,None,metrics)
    if not bool(scenario.get("feasibility",False)):
        return WatchEvaluation("REMOVE","مسیر TP یا براکت در بازبینی نهایی معتبر نیست",state.side,None,metrics)
    score=float(scenario.get("final_score") or setup_score)
    strength_score=float(scenario.get("strength_score") or 0.0)
    strength="خیلی قوی" if strength_score>=82 else "قوی" if strength_score>=68 else "متوسط"
    sig=StrategySignal(state.symbol_id,state.okx_symbol,state.toobit_symbol,state.side,price,strength,strength_score,
                       state.compression_score,float(scenario.get("flow") or state.early_flow),float(scenario.get("direction_score") or 0.0),
                       f"سناریوی یکپارچه ۱۵m تأیید و اجرای زنده revalidate شد؛ امتیاز نهایی {score:.1f}",
                       {"timeframe":"15m","scenario":scenario,"watch_age_seconds":round(age,2),"side_changes":state.side_changes,
                        "pre_entry_displacement_pct":abs(response),"late_limit_pct":state.late_limit_pct,
                        "entry_revalidation":{"trade":aligned_trade,"book":aligned_book,"response":aligned_response,"accel":accel}})
    return WatchEvaluation("SIGNAL","تأیید اجرای زنده کامل شد",state.side,sig,metrics)


def analyze_symbol_detailed(symbol_id:str,okx_symbol:str,toobit_symbol:str,candles:list[dict[str,float]])->StrategyAnalysisResult:
    candidate,reason,details=detect_watch_candidate(candles)
    if not candidate: return StrategyAnalysisResult(None,reason,details)
    scenario=candidate.details.get("scenario",{})
    sig=StrategySignal(symbol_id,okx_symbol,toobit_symbol,candidate.side,candidate.start_price,
                       "خیلی قوی" if float(scenario.get("strength_score",0))>=82 else "قوی" if float(scenario.get("strength_score",0))>=68 else "متوسط",
                       float(scenario.get("strength_score",0)),candidate.compression_score,candidate.early_flow,
                       float(scenario.get("direction_score",0)),candidate.trigger,{"timeframe":"15m","scenario":scenario})
    return StrategyAnalysisResult(sig,"",details)

def analyze_symbol(symbol_id:str,okx_symbol:str,toobit_symbol:str,candles:list[dict[str,float]])->StrategySignal|None:
    return analyze_symbol_detailed(symbol_id,okx_symbol,toobit_symbol,candles).signal
