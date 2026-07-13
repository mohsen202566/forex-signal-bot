from __future__ import annotations

import json
import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import config

# این فایل تمام منطق ربات را یکجا نگه می‌دارد:
# اندیکاتورها، تشخیص حرکت/جهت/ورود، ریسک، اجرا، مانیتورینگ و لاگ رد سیگنال.


# ==================== INDICATORS ====================

def closes(candles):
    return [float(x["close"]) for x in candles]


def ema(values, period):
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    out = [float(values[0])]
    for value in values[1:]:
        out.append(alpha * float(value) + (1.0 - alpha) * out[-1])
    return out


def sma(values, period):
    if not values:
        return 0.0
    window = values[-max(1, int(period)):]
    return sum(window) / len(window)


def atr(candles, period=14):
    if not candles:
        return []
    true_ranges = []
    for index, candle in enumerate(candles):
        high = float(candle["high"])
        low = float(candle["low"])
        previous_close = float(candles[index - 1]["close"]) if index else float(candle["close"])
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    return ema(true_ranges, period)


def rsi(values, period=14):
    if len(values) < 2:
        return [50.0] * len(values)
    gains = [0.0]
    losses = [0.0]
    for previous, current in zip(values, values[1:]):
        change = float(current) - float(previous)
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    average_gain = ema(gains, period)
    average_loss = ema(losses, period)
    out = []
    for gain, loss in zip(average_gain, average_loss):
        if loss == 0 and gain == 0:
            out.append(50.0)
        elif loss == 0:
            out.append(100.0)
        else:
            out.append(100.0 - 100.0 / (1.0 + gain / loss))
    return out


def macd(values, fast=12, slow=26, signal=9):
    fast_ema = ema(values, fast)
    slow_ema = ema(values, slow)
    line = [a - b for a, b in zip(fast_ema, slow_ema)]
    signal_line = ema(line, signal)
    histogram = [a - b for a, b in zip(line, signal_line)]
    return line, signal_line, histogram


def dmi_adx(candles, period=14):
    if not candles:
        return [], [], []
    plus_dm = [0.0]
    minus_dm = [0.0]
    true_ranges = [float(candles[0]["high"]) - float(candles[0]["low"])]
    for previous, current in zip(candles, candles[1:]):
        up = float(current["high"]) - float(previous["high"])
        down = float(previous["low"]) - float(current["low"])
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        high = float(current["high"])
        low = float(current["low"])
        previous_close = float(previous["close"])
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    smoothed_tr = ema(true_ranges, period)
    smoothed_plus = ema(plus_dm, period)
    smoothed_minus = ema(minus_dm, period)
    plus_di = [100.0 * p / tr if tr else 0.0 for p, tr in zip(smoothed_plus, smoothed_tr)]
    minus_di = [100.0 * m / tr if tr else 0.0 for m, tr in zip(smoothed_minus, smoothed_tr)]
    dx = [100.0 * abs(p - m) / (p + m) if p + m else 0.0 for p, m in zip(plus_di, minus_di)]
    return plus_di, minus_di, ema(dx, period)


def efficiency(values, lookback=12):
    if len(values) < 2:
        return 0.0
    window = values[-max(2, int(lookback)):]
    denominator = sum(abs(float(b) - float(a)) for a, b in zip(window, window[1:]))
    return abs(float(window[-1]) - float(window[0])) / denominator if denominator else 0.0


def candle_features(candle):
    open_, high, low, close = map(float, (candle["open"], candle["high"], candle["low"], candle["close"]))
    candle_range = max(high - low, 1e-12)
    return {
        "body_ratio": abs(close - open_) / candle_range,
        "close_location": (close - low) / candle_range,
        "upper_wick": (high - max(open_, close)) / candle_range,
        "lower_wick": (min(open_, close) - low) / candle_range,
        "direction": 1 if close > open_ else -1 if close < open_ else 0,
    }


def swing_points(candles, window=2):
    highs, lows = [], []
    window = max(1, int(window))
    for index in range(window, len(candles) - window):
        high = float(candles[index]["high"])
        low = float(candles[index]["low"])
        neighborhood = candles[index - window:index + window + 1]
        if high >= max(float(x["high"]) for x in neighborhood):
            highs.append((index, high))
        if low <= min(float(x["low"]) for x in neighborhood):
            lows.append((index, low))
    return highs, lows


def normalized_atr(candles, period=14):
    values = atr(candles, period)
    price = float(candles[-1]["close"]) if candles else 0.0
    return values[-1] / price * 100.0 if values and price else 0.0


def volume_ratio(candles, lookback=20):
    if len(candles) < 2:
        return 1.0
    volumes = [float(x.get("volume", 0.0)) for x in candles]
    baseline = sma(volumes[:-1], lookback)
    return volumes[-1] / baseline if baseline else 1.0


def session_vwap(candles, lookback=96):
    window = candles[-max(1, int(lookback)):]
    weighted = 0.0
    volume = 0.0
    for candle in window:
        vol = float(candle.get("volume", 0.0))
        typical = (float(candle["high"]) + float(candle["low"]) + float(candle["close"])) / 3.0
        weighted += typical * vol
        volume += vol
    return weighted / volume if volume else (float(window[-1]["close"]) if window else 0.0)


def overlap_ratio(candles, lookback=12):
    window = candles[-max(2, int(lookback)):]
    if len(window) < 2:
        return 0.0
    overlaps = []
    for previous, current in zip(window, window[1:]):
        intersection = max(0.0, min(float(previous["high"]), float(current["high"])) - max(float(previous["low"]), float(current["low"])))
        union = max(float(previous["high"]), float(current["high"])) - min(float(previous["low"]), float(current["low"]))
        overlaps.append(intersection / union if union else 0.0)
    return sum(overlaps) / len(overlaps)


# ==================== MARKET / SETUP / TRIGGER ====================

@dataclass
class MarketAnalysis:
    symbol_id: str; regime: str; primary_direction: str; direction_score: float; opposite_score: float
    strength_score: float; fragility_score: float; freshness_score: float; exhaustion_risk: float
    confidence: float; context_15m: str; movement_stage: str; value_distance_atr: float; atr_pct: float
    features: dict[str, Any]=field(default_factory=dict); reasons:list[str]=field(default_factory=list)
    contradictions:list[str]=field(default_factory=list); hard_veto:bool=False

class MarketEngine:
    """یک موتور واحد برای شروع حرکت، جهت و تازگی؛ اندیکاتورها رأی مستقل و تکراری نمی‌دهند."""
    @staticmethod
    def _clip(x: float) -> float: return max(0.0, min(100.0, x))

    def analyze(self, symbol_id, c5, c15):
        if len(c5)<90 or len(c15)<60:
            return MarketAnalysis(symbol_id,'UNKNOWN','NEUTRAL',0,0,0,100,0,100,0,'UNKNOWN','UNKNOWN',0,0,hard_veto=True,reasons=['داده کافی نیست'])
        v=closes(c5); v15=closes(c15); px=v[-1]
        e9,e21,e50=ema(v,9),ema(v,21),ema(v,50)
        h20,h50=ema(v15,20),ema(v15,50)
        atrs=atr(c5,14); atrv=atrs[-1]
        if px<=0 or atrv<=0:
            return MarketAnalysis(symbol_id,'UNKNOWN','NEUTRAL',0,0,0,100,0,100,0,'UNKNOWN','UNKNOWN',0,0,hard_veto=True,reasons=['قیمت یا ATR نامعتبر'])
        rs=rsi(v,14); _,_,hist=macd(v); pdi,mdi,adx=dmi_adx(c5,14)
        eff=efficiency(v,12); overlap=overlap_ratio(c5,12); vr=volume_ratio(c5)
        vwap=session_vwap(c5); atr_pct=atrv/px*100
        cf=[candle_features(x) for x in c5[-5:]]
        pressure=sum(x['direction']*x['body_ratio'] for x in cf)/5
        hs,ls=swing_points(c5[-70:],2)
        up_struct=len(hs)>=2 and len(ls)>=2 and hs[-1][1]>hs[-2][1] and ls[-1][1]>ls[-2][1]
        dn_struct=len(hs)>=2 and len(ls)>=2 and hs[-1][1]<hs[-2][1] and ls[-1][1]<ls[-2][1]
        context='BULLISH' if h20[-1]>h50[-1] and h20[-1]>h20[-3] else 'BEARISH' if h20[-1]<h50[-1] and h20[-1]<h20[-3] else 'NEUTRAL'

        # شروع حرکت: شتاب قبل از کراس کامل، افزایش دامنه/حجم و خروج از فشردگی.
        e9_slope=(e9[-1]-e9[-4])/atrv
        e21_slope=(e21[-1]-e21[-5])/atrv
        hist_acc=hist[-1]-hist[-2]
        hist_norm=hist_acc/atrv
        range_now=sum(float(x['high'])-float(x['low']) for x in c5[-3:])/3
        range_prev=sum(float(x['high'])-float(x['low']) for x in c5[-9:-3])/6
        expansion=range_now/range_prev if range_prev>0 else 1.0
        long_impulse=self._clip(50+18*e9_slope+12*e21_slope+20*hist_norm+12*(vr-1)+10*(expansion-1)+12*pressure)
        short_impulse=self._clip(50-18*e9_slope-12*e21_slope-20*hist_norm+12*(vr-1)+10*(expansion-1)-12*pressure)

        long_dir=(24*(1 if up_struct else .45 if e9[-1]>e21[-1] else .1)+20*self._clip(50+20*e21_slope)/100+16*(1 if context=='BULLISH' else .5 if context=='NEUTRAL' else 0)+14*self._clip(50+(pdi[-1]-mdi[-1]))/100+12*self._clip((rs[-1]-40)*4)/100+14*long_impulse/100)*100/100
        short_dir=(24*(1 if dn_struct else .45 if e9[-1]<e21[-1] else .1)+20*self._clip(50-20*e21_slope)/100+16*(1 if context=='BEARISH' else .5 if context=='NEUTRAL' else 0)+14*self._clip(50+(mdi[-1]-pdi[-1]))/100+12*self._clip((60-rs[-1])*4)/100+14*short_impulse/100)*100/100
        side='LONG' if long_dir-short_dir>=8 else 'SHORT' if short_dir-long_dir>=8 else 'NEUTRAL'
        direction=max(long_dir,short_dir); opposite=min(long_dir,short_dir)
        impulse=long_impulse if side=='LONG' else short_impulse if side=='SHORT' else max(long_impulse,short_impulse)
        dmi=self._clip(adx[-1]*2+(pdi[-1]-mdi[-1] if side=='LONG' else mdi[-1]-pdi[-1] if side=='SHORT' else 0))
        strength=self._clip(.30*impulse+.25*self._clip(eff*145)+.20*dmi+.15*self._clip(vr*60)+.10*self._clip(expansion*55))
        value_ref=(e21[-1]+vwap)/2; value_dist=abs(px-value_ref)/atrv
        displacement=abs(px-v[-7])/atrv
        decel=(hist[-1]<hist[-2]<hist[-3]) if side=='LONG' else (hist[-1]>hist[-2]>hist[-3]) if side=='SHORT' else True
        exhaustion=self._clip(18*value_dist+8*displacement+(15 if decel else 0))
        freshness=self._clip(100-exhaustion+8*max(0,expansion-1))
        fragility=self._clip((1-eff)*45+overlap*35+(18 if abs(pressure)<.10 else 0)+(12 if side=='NEUTRAL' else 0))
        contradictions=[]
        if side=='LONG' and context=='BEARISH': contradictions.append('تایم 15M مخالف لانگ است')
        if side=='SHORT' and context=='BULLISH': contradictions.append('تایم 15M مخالف شورت است')
        if side!='NEUTRAL' and impulse<48: contradictions.append('جهت هست اما شتاب شروع حرکت ضعیف است')
        if overlap>.82: contradictions.append('هم‌پوشانی کندل‌ها بسیار زیاد است')
        hard=overlap>.90 or (eff<.07 and expansion<1.05) or direction-opposite<5
        if side=='NEUTRAL' or hard: regime='RANGE_NOISY' if overlap>.72 else 'UNCERTAIN'
        elif strength>=70: regime='STRONG_TREND_UP' if side=='LONG' else 'STRONG_TREND_DOWN'
        else: regime='DEVELOPING_UP' if side=='LONG' else 'DEVELOPING_DOWN'
        stage='EARLY' if displacement<1.0 and impulse>=55 else 'DEVELOPING' if displacement<1.8 else 'LATE'
        confidence=self._clip(.42*direction+.28*strength+.18*freshness+.12*(100-fragility)-3*len(contradictions))
        features={'atr':atrv,'ema9':e9[-1],'ema21':e21[-1],'ema50':e50[-1],'rsi':rs[-1],'adx':adx[-1],
                  'volume_ratio':vr,'efficiency':eff,'overlap':overlap,'vwap':vwap,'pressure':pressure,
                  'impulse_score':impulse,'expansion':expansion,'ema9_slope_atr':e9_slope,'ema21_slope_atr':e21_slope,
                  'recent_swing_high':hs[-1][1] if hs else None,'recent_swing_low':ls[-1][1] if ls else None}
        reasons=[f'جهت={side} امتیاز={direction:.1f}',f'شروع‌حرکت={impulse:.1f}',f'قدرت={strength:.1f}',f'مرحله={stage}']
        return MarketAnalysis(symbol_id,regime,side,round(direction,2),round(opposite,2),round(strength,2),round(fragility,2),round(freshness,2),round(exhaustion,2),round(confidence,2),context,stage,round(value_dist,3),round(atr_pct,4),features,reasons,contradictions,hard)

@dataclass
class SetupCandidate:
    setup_id:str; symbol_id:str; side:str; setup_type:str; state:str; score:float; anchor_price:float
    invalidation_price:float; trigger_price:float; expires_at:int; reasons:list[str]=field(default_factory=list)
    risks:list[str]=field(default_factory=list); meta:dict[str,Any]=field(default_factory=dict)

class SetupEngine:
    def detect(self,m,c5): return self.detect_with_reason(m,c5)[0]
    def detect_with_reason(self,m:MarketAnalysis,c5:list[dict[str,Any]]):
        d={'direction':m.primary_direction,'regime':m.regime,'direction_score':m.direction_score,'strength_score':m.strength_score,'freshness_score':m.freshness_score,'movement_stage':m.movement_stage,'impulse_score':m.features.get('impulse_score')}
        if m.hard_veto:return None,'رد بازار: نویز/تضاد بحرانی فعال است',d
        if m.primary_direction=='NEUTRAL':return None,'رد جهت: برتری واضح LONG یا SHORT وجود ندارد',d
        if m.movement_stage=='LATE':return None,'رد تازگی: بخش زیادی از حرکت انجام شده و ورود دیر است',d
        if m.direction_score<config.DIRECTION_MIN:return None,f'رد جهت: امتیاز {m.direction_score:.1f} کمتر از {config.DIRECTION_MIN:.1f}',d
        if m.strength_score<config.STRENGTH_MIN:return None,f'رد شروع حرکت: قدرت {m.strength_score:.1f} کمتر از {config.STRENGTH_MIN:.1f}',d
        px=float(c5[-1]['close']); atr=float(m.features.get('atr') or 0); side=m.primary_direction
        if px<=0 or atr<=0:return None,'رد داده: قیمت یا ATR نامعتبر است',d
        prior=c5[-13:-1]; hi=max(float(x['high']) for x in prior); lo=min(float(x['low']) for x in prior)
        local_hi=max(float(x['high']) for x in c5[-4:-1]); local_lo=min(float(x['low']) for x in c5[-4:-1])
        e21=float(m.features.get('ema21') or px); vr=float(m.features.get('volume_ratio') or 1); impulse=float(m.features.get('impulse_score') or 0)
        breakout=(side=='LONG' and px>hi) or (side=='SHORT' and px<lo)
        near_value=abs(px-e21)/atr<=0.85
        if breakout and vr>=1.0:
            typ='EARLY_BREAKOUT'; trigger=hi if side=='LONG' else lo; invalid=local_lo if side=='LONG' else local_hi
            score=.32*m.direction_score+.28*m.strength_score+.18*m.freshness_score+.14*impulse+.08*min(100,vr*60)
            obstacle=None
        elif near_value:
            typ='FAST_PULLBACK'; trigger=local_hi if side=='LONG' else local_lo
            invalid=(m.features.get('recent_swing_low') or local_lo) if side=='LONG' else (m.features.get('recent_swing_high') or local_hi)
            score=.34*m.direction_score+.24*m.strength_score+.20*m.freshness_score+.14*impulse+.08*(100-min(100,abs(px-e21)/atr*100))
            obstacle=hi if side=='LONG' else lo
        else:
            return None,f'رد ورود: نه شکست اولیه معتبر است نه پولبک نزدیک ارزش؛ فاصله EMA21={abs(px-e21)/atr:.2f} ATR',d
        score=max(0,min(100,score)); d.update({'setup_type':typ,'setup_score':round(score,2),'price':px,'trigger':trigger,'invalidation':invalid})
        if score<config.SETUP_WATCH_MIN:return None,f'رد ستاپ: امتیاز {score:.1f} کمتر از {config.SETUP_WATCH_MIN:.1f}',d
        if (side=='LONG' and invalid>=px) or (side=='SHORT' and invalid<=px):return None,'رد ساختار: سطح ابطال در سمت نادرست است',d
        now=int(time.time())
        return SetupCandidate(f'{m.symbol_id}-{side}-{typ}-{now}',m.symbol_id,side,typ,'WATCH',round(score,2),px,float(invalid),float(trigger),now+config.WATCH_TTL_SECONDS,[f'{typ} با امتیاز {score:.1f}'],list(m.contradictions),{'atr':atr,'regime':m.regime,'obstacle_price':obstacle,'movement_stage':m.movement_stage}),f'ورود به واچ: {typ} امتیاز {score:.1f}',d

@dataclass
class WatchEvaluation:
    watch_id:str; state:str; trigger_score:float; confirmed:bool; entry_price:float; reason:str; meta:dict[str,Any]=field(default_factory=dict)

class WatchEngine:
    def evaluate(self,s:SetupCandidate,c1:list[dict[str,Any]]):
        now=int(time.time())
        if now>s.expires_at:return WatchEvaluation(s.setup_id,'EXPIRED',0,False,0,'پنجره 1 تا 3 کندل 5M تمام شد')
        confirmed=[x for x in c1 if int(x.get('confirm',1))==1]
        if len(confirmed)<25:return WatchEvaluation(s.setup_id,'WAITING',0,False,0,'داده تأییدشده 1M کافی نیست')
        px=float(confirmed[-1]['close']); atr=max(float(s.meta.get('atr') or 0),1e-12)
        if (s.side=='LONG' and px<=s.invalidation_price) or (s.side=='SHORT' and px>=s.invalidation_price):return WatchEvaluation(s.setup_id,'INVALIDATED',0,False,px,'سطح ابطال ساختاری شکسته شد')
        late=max(0,px-s.trigger_price) if s.side=='LONG' else max(0,s.trigger_price-px); late_atr=late/atr
        if late_atr>config.WATCH_LATE_LIMIT_ATR:return WatchEvaluation(s.setup_id,'INVALIDATED',0,False,px,'ورود دیر شده و قیمت تعقیب نمی‌شود',{'late_atr':late_atr})
        close_values=closes(confirmed); rs=rsi(close_values,7); _,_,hist=macd(close_values,6,13,4); cf=candle_features(confirmed[-1])
        price_ok=px>=s.trigger_price if s.side=='LONG' else px<=s.trigger_price
        momentum_ok=(hist[-1]>hist[-2] and rs[-1]>=50) if s.side=='LONG' else (hist[-1]<hist[-2] and rs[-1]<=50)
        candle_ok=(cf['direction']==1 and cf['close_location']>.58) if s.side=='LONG' else (cf['direction']==-1 and cf['close_location']<.42)
        not_stretched=late_atr<=.45
        # تریگر امتیازی است؛ عبور قیمت اجباری، دو تأیید دیگر قابل جبران‌اند.
        score=40*price_ok+25*momentum_ok+20*candle_ok+15*not_stretched
        ok=price_ok and score>=config.TRIGGER_MIN
        reason='تریگر سریع تأیید شد' if ok else 'تریگر هنوز کامل نشده'
        return WatchEvaluation(s.setup_id,'TRIGGER_CONFIRMED' if ok else 'WAITING',round(score,2),ok,px,reason,{'price_ok':price_ok,'momentum_ok':momentum_ok,'candle_ok':candle_ok,'not_stretched':not_stretched,'late_atr':late_atr,'rsi1m':rs[-1]})

@dataclass
class TradeDecision:
    action:str; final_score:float; confidence:float; allowed:bool; primary_reason:str; module_scores:dict[str,float]=field(default_factory=dict); contradictions:list[str]=field(default_factory=list)

class DecisionEngine:
    def decide(self,m:MarketAnalysis,s:SetupCandidate,w:WatchEvaluation):
        safety=max(0,100-.5*m.fragility_score-.3*m.exhaustion_risk)
        scores={'direction':m.direction_score,'movement':m.strength_score,'freshness':m.freshness_score,'setup':s.score,'trigger':w.trigger_score,'safety':safety}
        final=.24*scores['direction']+.22*scores['movement']+.12*scores['freshness']+.18*scores['setup']+.18*scores['trigger']+.06*scores['safety']
        final=max(0,final-2.5*len(m.contradictions))
        critical=[]
        if m.hard_veto:critical.append('Hard Veto بازار')
        if m.primary_direction!=s.side:critical.append('جهت بازار با ستاپ ناسازگار شد')
        if w.state in {'INVALIDATED','EXPIRED'}:critical.append(w.reason)
        if scores['direction']<config.DIRECTION_MIN:critical.append(f"direction={scores['direction']:.1f}")
        if scores['movement']<config.STRENGTH_MIN:critical.append(f"movement={scores['movement']:.1f}")
        if not w.confirmed:critical.append('تریگر قیمت تأیید نشده')
        if final<config.FINAL_MIN:critical.append(f'final={final:.1f}<{config.FINAL_MIN:.1f}')
        allowed=not critical
        reason='هماهنگی شروع حرکت، جهت و ورود تأیید شد' if allowed else '؛ '.join(critical)
        return TradeDecision(f'SIGNAL_{s.side}' if allowed else ('REJECT' if w.state in {'INVALIDATED','EXPIRED'} else 'KEEP_WATCHING'),round(final,2),round(min(m.confidence,final),2),allowed,reason,scores,list(m.contradictions))

@dataclass
class RiskPlan:
    entry:float; tp:float; sl:float; sl_pct:float; tp_pct:float; gross_rr:float; net_rr:float; trade_usdt:float; leverage:int; notional_usdt:float; estimated_net_profit:float; estimated_net_loss:float; estimated_cost_win:float; estimated_cost_loss:float; valid:bool; reason:str

class RiskEngine:
    def build(self,s:SetupCandidate,d:TradeDecision,entry:float,trade_usdt:float,leverage:int):
        notional=max(0,trade_usdt*leverage)
        bad=lambda reason: RiskPlan(entry,0,0,0,0,config.FIXED_GROSS_RR,0,trade_usdt,leverage,notional,0,0,0,0,False,reason)
        if entry<=0 or not(config.TRADE_USDT_MIN<=trade_usdt<=config.TRADE_USDT_MAX) or not(config.LEVERAGE_MIN<=leverage<=config.LEVERAGE_MAX):return bad('ورودی ریسک نامعتبر است')
        atr=float(s.meta.get('atr') or 0); structural=abs(entry-s.invalidation_price)/entry*100
        buffer=(atr/entry*100*config.ATR_STOP_BUFFER) if atr>0 else 0
        sl_pct=max(config.MIN_SL_PCT,structural+buffer)
        max_sl=config.ADAPTIVE_MAX_SL_PCT if d.final_score>=82 else config.NORMAL_MAX_SL_PCT
        if sl_pct>max_sl:return bad(f'استاپ ساختاری {sl_pct:.3f}% بیش از سقف {max_sl:.3f}% است')
        tp_pct=sl_pct*config.FIXED_GROSS_RR
        sl=entry*(1-sl_pct/100) if s.side=='LONG' else entry*(1+sl_pct/100)
        tp=entry*(1+tp_pct/100) if s.side=='LONG' else entry*(1-tp_pct/100)
        obstacle=s.meta.get('obstacle_price')
        if obstacle:
            space=((float(obstacle)-entry)/entry*100) if s.side=='LONG' else ((entry-float(obstacle))/entry*100)
            if space>0 and space<tp_pct:return bad(f'فضای واقعی تا مانع {space:.3f}% کمتر از TP ثابت {tp_pct:.3f}% است')
        fee_pct=2*config.TOOBIT_FUTURES_TAKER_FEE_PCT
        win_cost_pct=fee_pct+config.ENTRY_SLIPPAGE_PCT+config.TP_SLIPPAGE_PCT
        loss_cost_pct=fee_pct+config.ENTRY_SLIPPAGE_PCT+config.SL_SLIPPAGE_PCT
        win_cost=notional*win_cost_pct/100; loss_cost=notional*loss_cost_pct/100
        net_profit=notional*tp_pct/100-win_cost; net_loss=notional*sl_pct/100+loss_cost
        net_rr=net_profit/net_loss if net_loss>0 else 0
        valid=tp>0 and sl>0 and net_profit>=config.MIN_NET_PROFIT_USDT and net_rr>=config.MIN_NET_RR_AFTER_COSTS
        reason='معتبر؛ RR قیمتی دقیقاً 1.50 و سود خالص کافی است' if valid else f'رد هزینه: سودخالص={net_profit:.4f} (حداقل 0.05)، NetRR={net_rr:.2f}'
        return RiskPlan(entry,tp,sl,sl_pct,tp_pct,config.FIXED_GROSS_RR,net_rr,trade_usdt,leverage,notional,net_profit,net_loss,win_cost,loss_cost,valid,reason)


# ==================== SIGNAL REJECTION LOG ====================

log = logging.getLogger('signal_rejections')

class SignalLogger:
    """لاگ یک‌خطی و قابل grep برای VPS؛ هیچ خطای سیگنال را مخفی نمی‌کند."""
    @staticmethod
    def emit(stage: str, symbol: str, result: str, reason: str, **details: Any) -> None:
        payload = {
            'ts': int(time.time()), 'event': 'signal_evaluation', 'stage': stage,
            'symbol': symbol, 'result': result, 'reason': reason,
        }
        payload.update({k: v for k, v in details.items() if v is not None})
        if config.LOG_REJECTIONS_JSON:
            log.info('SIGNAL_LOG %s', json.dumps(payload, ensure_ascii=False, separators=(',', ':')))
        else:
            log.info('سیگنال | مرحله=%s | ارز=%s | نتیجه=%s | علت=%s | جزئیات=%s', stage, symbol, result, reason, details)


# ==================== HEALTH / LEARNING / EXPERIENCE ====================

@dataclass
class SymbolProfile:
    symbol_id:str; version:str='v1.0'; parameters:dict[str,Any]=field(default_factory=dict); confidence:str='LOW'; samples:int=0
class Profiles:
    def __init__(self,storage): self.storage=storage
    def get(self,symbol_id):
        raw=self.storage.get_profile(symbol_id) or {}; return SymbolProfile(symbol_id,raw.get('version','v1.0'),raw.get('parameters',{}),raw.get('confidence','LOW'),int(raw.get('samples',0)))
    def save(self,p): self.storage.save_profile(p.symbol_id,p.version,p.parameters,p.confidence,p.samples)

class HealthManager:
    EXPECTED_MAX_AGE = {
        "scan": 180,
        "watch": 30,
        "monitor": 30,
        "telegram": 30,
        "toobit": 60,
        "learning": 7200,
    }

    def __init__(self, storage):
        self.storage = storage

    def mark(self, component: str, symbol_id: str | None = None) -> None:
        self.storage.set(f"health_{component}_ts", int(time.time()))

    def report(self) -> str:
        events = self.storage.active_health_events()
        labels = (
            ("scan", "اسکن"),
            ("watch", "واچ"),
            ("monitor", "مانیتور"),
            ("telegram", "تلگرام"),
            ("toobit", "توبیت"),
            ("learning", "یادگیری"),
        )
        lines = ["🩺 پنل سلامت", ""]
        now = int(time.time())
        for component, label in labels:
            ts = int(self.storage.get(f"health_{component}_ts", 0) or 0)
            if not ts:
                lines.append(f"{label}: ⚠️ هنوز ثبت نشده")
                continue
            age = max(0, now - ts)
            max_age = self.EXPECTED_MAX_AGE.get(component, 120)
            icon = "✅" if age <= max_age else "⚠️"
            state = "فعال" if age <= max_age else "قدیمی/متوقف"
            lines.append(f"{label}: {icon} {state} | {age} ثانیه قبل")
        if not events:
            lines.extend(["", "✅ مشکل فعالی ثبت نشده."])
        else:
            lines.extend(["", "🚨 مشکلات فعال:"])
            for event in events[:10]:
                lines.append(f"{event['severity']} | {event['component']} | {event.get('symbol_id') or '-'} | {event['message']}")
        return "\n".join(lines)

class ExperienceEngine:
    def analyze(self, signal, result):
        mfe = float(result.get("mfe_r", 0) or 0)
        mae = float(result.get("mae_r", 0) or 0)
        outcome = result.get("outcome")
        adverse = abs(mae)
        if outcome == "TP":
            cause = "CLEAN_WIN" if adverse < 0.5 else "HIGH_MAE_WIN"
            direction = "DIRECTION_CORRECT"
        elif outcome == "EXPIRED":
            cause = "NO_RESOLUTION_WITHIN_TIME_LIMIT"
            direction = "DIRECTION_AMBIGUOUS"
        elif mfe < 0.2:
            cause = "DIRECTION_ERROR"
            direction = "DIRECTION_WRONG"
        elif result.get("post_sl_reached_tp"):
            cause = "ENTRY_TOO_EARLY_OR_STOP_TOO_TIGHT"
            direction = "DIRECTION_CORRECT"
        elif float(signal.get("freshness_score", 100) or 100) < 50:
            cause = "ENTRY_TOO_LATE"
            direction = "DIRECTION_CORRECT"
        else:
            cause = "NO_FOLLOW_THROUGH"
            direction = "DIRECTION_AMBIGUOUS"
        return {
            "signal_id": signal["id"],
            "outcome": outcome,
            "primary_cause": cause,
            "direction_label": direction,
            "mfe_r": mfe,
            "mae_r": mae,
            "net_pnl": result.get("net_pnl", 0),
            "model_version": signal.get("model_version", "v1.0"),
        }

class LearningEngine:
    def __init__(self,storage): self.storage=storage
    def run(self,symbol_id):
        rows=self.storage.list_experiences(symbol_id,500); n=len(rows)
        if n<config.LEARNING_MIN_SAMPLES:return {'action':'INSUFFICIENT_DATA','samples':n}
        wins=sum(1 for x in rows if x['outcome']=='TP'); net=sum(float(x.get('net_pnl',0)) for x in rows); causes={}
        non_errors={'CLEAN_WIN','HIGH_MAE_WIN','NO_RESOLUTION_WITHIN_TIME_LIMIT'}
        for x in rows:
            cause=x.get('primary_cause')
            if cause and cause not in non_errors:
                causes[cause]=causes.get(cause,0)+1
        top=max(causes,key=causes.get) if causes else None
        return {'action':'CREATE_HYPOTHESIS' if top else 'STORE_ONLY','samples':n,'win_rate':wins/n*100,'net_pnl':net,'top_error':top,'confidence':'HIGH' if n>=100 else 'MEDIUM'}

class AdaptiveEngine:
    def __init__(self,storage,profiles): self.storage=storage; self.profiles=profiles
    def create_candidate(self,symbol_id,learning):
        if learning.get('action')!='CREATE_HYPOTHESIS': return None
        p=self.profiles.get(symbol_id); err=learning.get('top_error')
        change={}
        if err=='ENTRY_TOO_LATE': change={'trigger_threshold_delta':-1}
        elif err=='DIRECTION_ERROR': change={'direction_threshold_delta':1}
        elif err=='NO_FOLLOW_THROUGH': change={'strength_threshold_delta':1}
        else:return None
        cid=f'{symbol_id}-{p.version}-candidate'; self.storage.save_model_change(cid,symbol_id,p.version,change,'SHADOW'); return {'candidate_id':cid,'change':change,'status':'SHADOW'}


# ==================== REAL EXECUTION / MONITOR ====================

class ExecutionEngine:
    def __init__(self, storage, toobit, okx, health, exchange_lock: threading.RLock | None = None):
        self.storage = storage
        self.toobit = toobit
        self.okx = okx
        self.health = health
        self.lock = exchange_lock or threading.RLock()

    @staticmethod
    def _deviation_pct(reference: float, current: float) -> float:
        return abs(current - reference) / reference * 100.0 if reference > 0 and current > 0 else float("inf")

    @staticmethod
    def _position_matches_side(position, side: str) -> bool:
        side_u = side.upper()
        position_side = str(position.get("positionSide") or position.get("side") or position.get("position_side") or "").upper()
        if position_side in {"LONG", "SHORT"}:
            return position_side == side_u
        try:
            amount = float(position.get("positionAmt") or position.get("size") or position.get("qty") or position.get("quantity") or 0)
        except (TypeError, ValueError):
            return False
        return amount > 0 if side_u == "LONG" else amount < 0

    def execute(self, symbol, signal_id, side, risk):
        if not self.storage.get("trading_enabled", False):
            return {"status": "VIRTUAL_ONLY", "reason": "ترید واقعی خاموش است"}
        if not self.toobit.has_credentials:
            return {"status": "VIRTUAL_ONLY", "reason": "کلیدهای API توبیت تنظیم نشده‌اند"}

        order_attempted = False
        with self.lock:
            try:
                db_open = self.storage.count_real_open()
                exchange_open = len(self.toobit.get_open_positions())
                max_positions = int(self.storage.get("max_positions", config.MAX_POSITIONS_DEFAULT))
                if max(db_open, exchange_open) >= max_positions:
                    return {"status": "VIRTUAL_ONLY", "reason": "اسلات واقعی خالی نیست"}

                balance = self.toobit.get_futures_balance()
                required_free = float(risk.trade_usdt) * (1.0 + config.MIN_FREE_MARGIN_BUFFER_PCT / 100.0)
                if float(balance.get("available") or 0.0) < required_free:
                    return {"status": "VIRTUAL_ONLY", "reason": "موجودی آزاد توبیت برای مارجین و حاشیه ایمنی کافی نیست"}

                # A last public-price check prevents sending a stale market entry after Telegram/network delay.
                current_price = float(self.okx.get_last_price(symbol.okx))
                allowed_deviation = min(
                    float(config.EXECUTION_MAX_DEVIATION_PCT),
                    max(0.05, float(risk.sl_pct) * float(config.EXECUTION_MAX_DEVIATION_SL_FRACTION)),
                )
                deviation = self._deviation_pct(float(risk.entry), current_price)
                if deviation > allowed_deviation:
                    return {
                        "status": "VIRTUAL_ONLY",
                        "reason": f"قیمت اجرای زنده {deviation:.3f}% از Entry فاصله گرفته و ورود دیر شده است",
                    }

                order_attempted = True
                result = self.toobit.open_futures_position_with_tpsl(
                    symbol.toobit,
                    side,
                    risk.trade_usdt,
                    risk.leverage,
                    risk.entry,
                    risk.tp,
                    risk.sl,
                    f"bot_{signal_id}_{int(time.time())}",
                )
                order_id = result.get("order_id")
                self.storage.update_signal(
                    signal_id,
                    is_real=1,
                    trade_mode="real",
                    status="pending",
                    order_id=order_id,
                )
                if not order_id:
                    self.storage.add_health_event(
                        "toobit_order",
                        "warning",
                        "سفارش پذیرفته شد اما Order ID از پاسخ توبیت استخراج نشد",
                        symbol.id,
                    )
                self.health.mark("toobit")
                return {"status": "REAL_PENDING", "order_id": order_id}
            except Exception as exc:
                # A POST timeout can be ambiguous. Check the exchange before falling back to virtual.
                try:
                    positions = self.toobit.get_open_positions(symbol.toobit) if order_attempted else []
                    if any(self._position_matches_side(position, side) for position in positions):
                        self.storage.update_signal(signal_id, is_real=1, trade_mode="real", status="pending")
                        self.storage.add_health_event(
                            "toobit_order",
                            "critical",
                            f"پاسخ سفارش نامشخص بود اما پوزیشن روی توبیت دیده شد: {exc}",
                            symbol.id,
                        )
                        return {"status": "REAL_PENDING", "reason": "پوزیشن روی صرافی دیده شد؛ پاسخ سفارش نامشخص است"}
                except Exception:
                    pass
                self.storage.add_health_event("toobit_order", "warning", str(exc), symbol.id)
                return {"status": "VIRTUAL_ONLY", "reason": str(exc)}

class Monitor:
    def __init__(self, okx, toobit, storage, telegram, experience, exchange_lock=None):
        self.okx = okx
        self.toobit = toobit
        self.storage = storage
        self.telegram = telegram
        self.experience = experience
        import threading
        self.exchange_lock = exchange_lock or threading.RLock()

    def run_once(self) -> None:
        for signal in self.storage.get_open_signals():
            try:
                if signal["is_real"]:
                    self._real(signal)
                else:
                    self._virtual(signal)
                self.storage.resolve_health("monitor", signal["symbol_id"])
            except Exception as exc:
                self.storage.add_health_event("monitor", "warning", str(exc), signal["symbol_id"])
        self._retry_unsent_results()
        self.storage.set("monitor_last_ts", int(time.time()))

    def _virtual_metrics(self, s: dict[str, Any], until_ts_ms: int | None = None) -> tuple[list[dict[str, float]], float, float]:
        candles = self.okx.get_candles(s["okx_symbol"], bar="1m", limit=300)
        start_ms = int(s["opened_at"] or s["created_at"]) * 1000
        reference_entry = float(s.get("real_entry") or s["entry"])
        mfe_pct, mae_pct = self.okx.max_favorable_adverse(candles, s["side"], reference_entry, start_ms, until_ts_ms)
        risk_pct = abs(reference_entry - float(s["sl"])) / reference_entry * 100.0 if reference_entry else 0.0
        mfe_r = mfe_pct / risk_pct if risk_pct else 0.0
        mae_r = mae_pct / risk_pct if risk_pct else 0.0
        return candles, mfe_r, mae_r

    def _virtual(self, s: dict[str, Any]) -> None:
        candles = self.okx.get_candles(s["okx_symbol"], bar="1m", limit=300)
        start_ms = int(s["opened_at"] or s["created_at"]) * 1000
        outcome, price, hit_ts = self.okx.reached_tp_or_sl(candles, s["side"], s["tp"], s["sl"], start_ms)
        _, mfe_r, mae_r = self._virtual_metrics(s, hit_ts)
        self.storage.update_signal(s["id"], mfe_r=mfe_r, mae_r=mae_r)
        if not outcome:
            max_age = int(config.VIRTUAL_MONITOR_MAX_MINUTES * 60)
            if int(time.time()) - int(s["opened_at"] or s["created_at"]) > max_age:
                last_price = float(candles[-1]["close"]) if candles else float(s["entry"])
                notional = float(s.get("notional_usdt") or 0)
                directional = ((last_price - float(s["entry"])) / float(s["entry"])) if s["side"] == "LONG" else ((float(s["entry"]) - last_price) / float(s["entry"]))
                estimated_cost = float(
                    (s.get("estimated_cost_win") if directional >= 0 else s.get("estimated_cost_loss"))
                    or s.get("estimated_cost")
                    or 0
                )
                net = directional * notional - estimated_cost
                self._close(s, "EXPIRED", last_price, net, estimated_cost, mfe_r, mae_r)
                self.storage.resolve_health("virtual_timeout", s["symbol_id"])
            return
        gross = abs(float(price) - float(s["entry"])) / float(s["entry"]) * float(s["notional_usdt"])
        if outcome == "SL":
            gross = -gross
            cost = float(s.get("estimated_cost_loss") or s.get("estimated_cost") or 0)
        else:
            cost = float(s.get("estimated_cost_win") or s.get("estimated_cost") or 0)
        self._close(s, outcome, float(price), gross - cost, cost, mfe_r, mae_r)

    @staticmethod
    def _position_matches_side(position: dict[str, Any], side: str) -> bool:
        side_u = side.upper()
        position_side = str(position.get("positionSide") or position.get("side") or position.get("position_side") or "").upper()
        if position_side in {"LONG", "SHORT"}:
            return position_side == side_u
        try:
            amount = float(position.get("positionAmt") or position.get("size") or position.get("qty") or position.get("quantity") or 0)
        except (TypeError, ValueError):
            amount = 0.0
        if amount == 0:
            return False
        return amount > 0 if side_u == "LONG" else amount < 0

    def _matching_open_position(self, s: dict[str, Any]) -> dict[str, Any] | None:
        with self.exchange_lock:
            positions = self.toobit.get_open_positions(s["toobit_symbol"])
        return next((position for position in positions if self._position_matches_side(position, s["side"])), None)

    @staticmethod
    def _position_entry_price(position: dict[str, Any]) -> float:
        for key in ("entryPrice", "avgEntryPrice", "averageOpenPrice", "openPrice", "avgPrice"):
            try:
                value = float(position.get(key) or 0)
            except (TypeError, ValueError):
                continue
            if value > 0:
                return value
        return 0.0

    def _real(self, s: dict[str, Any]) -> None:
        # Keep virtual MFE/MAE reference for diagnosis, but never use OKX to decide a real result.
        try:
            _, mfe_r, mae_r = self._virtual_metrics(s)
            self.storage.update_signal(s["id"], mfe_r=mfe_r, mae_r=mae_r)
        except Exception:
            mfe_r = float(s.get("mfe_r") or 0)
            mae_r = float(s.get("mae_r") or 0)

        position = self._matching_open_position(s)
        if position:
            real_entry = self._position_entry_price(position)
            updates = {"real_open_confirmed": 1}
            if s["status"] != "open":
                updates["status"] = "open"
            if real_entry > 0:
                updates["real_entry"] = real_entry
            self.storage.update_signal(s["id"], **updates)
            self.storage.resolve_health("real_pending", s["symbol_id"])
            return

        opened_ms = int(s["opened_at"] or s["created_at"]) * 1000
        # Do not inspect close history until the real position has been observed open at least once.
        # This prevents a filled opening order from being mistaken for a closing order.
        if not int(s.get("real_open_confirmed") or 0):
            age = int(time.time()) - int(s["opened_at"] or s["created_at"])
            if s["status"] == "pending" and age > config.REAL_PENDING_TIMEOUT_SECONDS:
                self.storage.add_health_event(
                    "real_pending",
                    "critical",
                    "وضعیت سفارش واقعی نامشخص است؛ برای ایمنی در حالت pending باقی ماند",
                    s["symbol_id"],
                )
            return

        with self.exchange_lock:
            result = self.toobit.get_closed_trade_result(s["toobit_symbol"], s["side"], opened_ms)
        if result:
            try:
                _, mfe_r, mae_r = self._virtual_metrics(s, int(result.get("time_ms") or 0) or None)
            except Exception:
                pass
            realized = result.get("realized_pnl")
            fee = abs(float(result.get("fee") or 0))
            reference_entry = float(s.get("real_entry") or s["entry"])
            favorable = (s["side"] == "LONG" and result["exit_price"] > reference_entry) or (
                s["side"] == "SHORT" and result["exit_price"] < reference_entry
            )
            if isinstance(realized, (int, float)) and not math.isnan(float(realized)):
                net = float(realized) if config.TOOBIT_REALIZED_PNL_INCLUDES_FEES else float(realized) - fee
            else:
                gross = abs(result["exit_price"] - reference_entry) / reference_entry * s["notional_usdt"]
                net = (gross - fee) if favorable else -(gross + fee)
            self._close(
                s,
                "TP" if favorable else "SL",
                float(result["exit_price"]),
                net,
                fee,
                mfe_r,
                mae_r,
            )
            return



    def _close(self, s: dict[str, Any], outcome: str, exit_price: float, net: float, fees: float, mfe_r: float, mae_r: float) -> None:
        if not self.storage.close_signal(
            s["id"],
            outcome=outcome,
            exit_price=exit_price,
            net_pnl=net,
            fees=fees,
            mfe_r=mfe_r,
            mae_r=mae_r,
        ):
            return
        fresh = self.storage.get_signal(s["id"])
        exp = self.experience.analyze(
            fresh,
            {"outcome": outcome, "mfe_r": mfe_r, "mae_r": mae_r, "net_pnl": net},
        )
        exp["symbol_id"] = s["symbol_id"]
        self.storage.add_experience(exp)
        self._send_result_message(fresh, exp)

    def _format_result_message(self, s: dict[str, Any], exp: dict[str, Any]) -> str:
        outcome = str(s.get("outcome") or "")
        icon = "✅" if outcome == "TP" else "❌" if outcome == "SL" else "⌛"
        title = "TP خورد" if outcome == "TP" else "SL خورد" if outcome == "SL" else "معامله منقضی شد"
        net = float(s.get("net_pnl") or 0)
        return (
            f"{icon} {title}\n\n"
            f"#{s['id']} | {s['symbol_id']} | {s['side']}\n"
            f"نوع: {'واقعی' if s['is_real'] else 'مجازی'}\n\n"
            f"Entry: {float(s.get('real_entry') or s['entry']):.8g}\nExit: {float(s.get('exit_price') or 0):.8g}\n"
            f"کارمزد/اسلیپیج: {float(s.get('fees') or 0):.4f} USDT\n"
            f"{'سود' if net >= 0 else 'زیان'} خالص: {net:.4f} USDT\n"
            f"MFE: {float(s.get('mfe_r') or 0):.2f}R | MAE: {float(s.get('mae_r') or 0):.2f}R\n\n"
            f"تحلیل: {self._cause_fa(exp.get('primary_cause'))}"
        )

    @staticmethod
    def _cause_fa(cause: str | None) -> str:
        labels = {
            "CLEAN_WIN": "برد تمیز؛ جهت و ورود مناسب بود",
            "HIGH_MAE_WIN": "برد با نوسان مخالف زیاد",
            "DIRECTION_ERROR": "احتمال خطای جهت",
            "ENTRY_TOO_EARLY_OR_STOP_TOO_TIGHT": "ورود زود یا استاپ نزدیک",
            "ENTRY_TOO_LATE": "ورود دیرهنگام",
            "NO_FOLLOW_THROUGH": "حرکت ادامه کافی نداشت",
            "NO_RESOLUTION_WITHIN_TIME_LIMIT": "معامله در زمان مجاز تعیین تکلیف نشد",
            "UNCLASSIFIED": "علت قطعی مشخص نشد",
        }
        return labels.get(str(cause or "UNCLASSIFIED"), str(cause or "UNCLASSIFIED"))

    def _send_result_message(self, s: dict[str, Any], exp: dict[str, Any]) -> bool:
        message_id = self.telegram.send_message(self._format_result_message(s, exp), reply_to_message_id=s.get("message_id"))
        if message_id:
            self.storage.update_signal(s["id"], result_message_sent=1, result_retry_at=0)
            return True
        retry_count = int(s.get("result_retry_count") or 0) + 1
        self.storage.schedule_result_retry(s["id"], retry_count)
        return False

    def _retry_unsent_results(self) -> None:
        for signal in self.storage.get_unsent_closed_signals(20):
            exp = self.storage.get_experience_for_signal(signal["id"]) or {"primary_cause": "UNCLASSIFIED"}
            self._send_result_message(signal, exp)
