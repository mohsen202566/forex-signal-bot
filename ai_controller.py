from __future__ import annotations

from dataclasses import dataclass

from adaptive_tp_sl_engine import AdaptiveTpSlEngine
from candle_hunter_engine import CandleHunterEngine
from config import SIGNAL_THRESHOLD, TIMEFRAME_15M, TIMEFRAME_1H, TIMEFRAME_4H, TIMEFRAME_5M, WATCH_THRESHOLD, WEIGHTS
from cost_engine import CostEngine
from direction_engine import DirectionEngine
from entry_quality import EntryQualityEngine
from entry_stage_engine import EntryStageEngine
from indicators import IndicatorSnapshot, calculate_indicators
from ignition_entry_engine import IgnitionEntryEngine
from indicator_range_ai import IndicatorRangeAI
from learning_engine import LearningEngine
from levels_engine import LevelsEngine
from market_context import MarketContextEngine
from okx_data import Candle
from order_block_engine import OrderBlockEngine
from pre_ignition_engine import PreIgnitionEngine
from scorer import Direction, ScoreBreakdown, SignalDecision
from session_engine import SessionEngine
from storage import Storage


@dataclass(frozen=True)
class AnalysisInput:
    symbol_name: str
    candles_by_tf: dict[str, list[Candle]]
    btc_1h: list[Candle] | None = None
    eth_1h: list[Candle] | None = None
    watch_mode: bool = False


class AIController:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage
        self.direction_engine = DirectionEngine()
        self.pre_ignition = PreIgnitionEngine()
        self.candle_hunter = CandleHunterEngine()
        self.entry_stage = EntryStageEngine()
        self.entry_quality_engine = EntryQualityEngine()
        self.ignition = IgnitionEntryEngine()
        self.levels_engine = LevelsEngine()
        self.tp_sl = AdaptiveTpSlEngine()
        self.cost_engine = CostEngine()
        self.market_engine = MarketContextEngine()
        self.order_block_engine = OrderBlockEngine()
        self.session_engine = SessionEngine()
        self.learning_engine = LearningEngine()
        self.indicator_ai = IndicatorRangeAI()

    def analyze(self, data: AnalysisInput) -> SignalDecision:
        snapshots = {tf: calculate_indicators(candles) for tf, candles in data.candles_by_tf.items()}
        s4h = snapshots[TIMEFRAME_4H]
        s1h = snapshots[TIMEFRAME_1H]
        s15 = snapshots[TIMEFRAME_15M]
        s5 = snapshots[TIMEFRAME_5M]
        entry = s5.close

        dir15 = self.direction_engine.analyze_15m_scalp(s15, s5)
        soft_direction_watch = False
        if dir15.state in ("LONG", "SHORT"):
            direction: Direction = "LONG" if dir15.state == "LONG" else "SHORT"
        elif abs(dir15.raw_strength) >= 4:
            # جهت هنوز برای Real کامل نیست، اما برای Watch/Ghost ارزش یادگیری دارد.
            direction = "LONG" if dir15.raw_strength > 0 else "SHORT"
            soft_direction_watch = True
        else:
            return self._reject(
                entry=entry,
                breakdown=ScoreBreakdown(score_direction=dir15.score),
                reason="15m/5m هنوز حتی جهت اولیه قابل یادگیری هم نداده؛ رد کامل.",
                code="SCALP_DIRECTION_NEUTRAL",
                setup_15m=dir15.state,
                notes=dir15.reasons,
                rsi_5m=s5.rsi,
                rsi_15m=s15.rsi,
                macd_hist_5m=s5.macd_hist,
                macd_hist_15m=s15.macd_hist,
                adx_15m=s15.adx,
                atr_pct_15m=s15.atr_pct,
                volume_ratio_5m=s5.volume_ratio,
                volume_ratio_15m=s15.volume_ratio,
            )
        context1h = self.direction_engine.analyze_1h_context(s1h, direction)
        bias4h = self.direction_engine.analyze_4h_bias(s4h, direction)
        pre = self.pre_ignition.analyze(s15, s5, direction)
        candle = self.candle_hunter.analyze(data.candles_by_tf[TIMEFRAME_5M], direction)
        stage = self.entry_stage.analyze(s5, direction)
        ignition = self.ignition.analyze(candle, stage)
        entry_quality = self.entry_quality_engine.analyze(direction=direction, snapshot_5m=s5, snapshot_15m=s15, candle=candle, stage=stage)
        levels = self.levels_engine.detect(data.candles_by_tf[TIMEFRAME_15M], entry)
        memory = self.learning_engine.analyze(self.storage, data.symbol_name, direction, candle.label, s5.rsi, s15.adx, s15.volume_ratio)
        indicator_ai = self.indicator_ai.analyze(self.storage, symbol_name=data.symbol_name, direction=direction, snapshot_5m=s5, snapshot_15m=s15, entry_quality=entry_quality.quality, candle_pattern=candle.label)
        learned_expected_pct = indicator_ai.expected_move_pct or memory.expected_move_pct
        risk = self.tp_sl.build(direction=direction, entry=entry, snapshot_15m=s15, levels=levels, learned_expected_pct=learned_expected_pct)
        cost = self.cost_engine.evaluate(direction=direction, entry=entry, tp=risk.tp, margin_usdt=self.storage.margin_usdt(), leverage=self.storage.leverage())
        btc_snapshot = self._safe_snapshot(data.btc_1h)
        eth_snapshot = self._safe_snapshot(data.eth_1h)
        market = self.market_engine.analyze(btc_snapshot, eth_snapshot, direction)
        ob = self.order_block_engine.analyze(data.candles_by_tf[TIMEFRAME_15M], direction, entry, s15.atr)
        session = self.session_engine.analyze(self.storage, data.symbol_name, direction)

        score_direction = min(WEIGHTS.direction, dir15.score)
        score_pre = min(WEIGHTS.pre_ignition, pre.score)
        score_entry = max(0, min(WEIGHTS.candle_entry, ignition.score + entry_quality.score_bonus))
        score_ai = max(0, min(WEIGHTS.ai_memory, max(memory.score, indicator_ai.score)))
        score_session = min(WEIGHTS.session, session.score)
        score_zone = max(0, min(WEIGHTS.order_block, context1h.score + bias4h.score + market.score + ob.score))
        breakdown = ScoreBreakdown(
            score_direction=score_direction,
            score_pre_ignition=score_pre,
            score_candle_entry=score_entry,
            score_ai_memory=score_ai,
            score_risk_net=0,
            score_session=score_session,
            score_order_block=score_zone,
        )
        total = max(0, min(100, breakdown.total))
        notes = (
            dir15.reasons + context1h.reasons + bias4h.reasons + pre.reasons + candle.reasons + stage.reasons +
            ignition.reasons + entry_quality.reasons + risk.reasons + cost.reasons + market.reasons + ob.reasons +
            session.reasons + memory.reasons + indicator_ai.reasons
        )
        common = dict(
            direction=direction,
            direction_state_1h=context1h.state,
            direction_confidence_1h=context1h.confidence,
            bias_4h=bias4h.state,
            setup_15m=dir15.state,
            entry_5m=ignition.state,
            candle_pattern=candle.label,
            entry_stage_pct=stage.stage_pct,
            entry_quality=entry_quality.quality,
            technical_zone=ob.state,
            indicator_profile=indicator_ai.profile,
            ai_confidence=max(memory.confidence, indicator_ai.confidence),
            ai_experience=max(memory.experience, indicator_ai.experience),
            ai_adjustment=memory.adjustment + indicator_ai.adjustment,
            ai_effect=indicator_ai.verdict,
            net_edge=cost.net_edge,
            estimated_profit_usdt=cost.estimated_profit_usdt,
            estimated_profit_pct=cost.estimated_profit_pct,
            risk_reward=risk.risk_reward,
            estimated_cost_pct=cost.estimated_cost_pct,
            market_bias=market.bias,
            session_state=session.state,
            order_block_state=ob.state,
            rsi_5m=s5.rsi,
            rsi_15m=s15.rsi,
            macd_hist_5m=s5.macd_hist,
            macd_hist_15m=s15.macd_hist,
            adx_15m=s15.adx,
            atr_pct_15m=s15.atr_pct,
            volume_ratio_5m=s5.volume_ratio,
            volume_ratio_15m=s15.volume_ratio,
            notes=notes,
        )

        if not risk.ok:
            return self._reject(entry=entry, tp=risk.tp, sl=risk.sl, breakdown=breakdown, reason="TP/SL اسکالپی برای این ورود قابل قبول نیست.", code="SCALP_RISK_REJECT", hard=True, **common)
        if not cost.ok:
            return self._reject(entry=entry, tp=risk.tp, sl=risk.sl, breakdown=breakdown, reason="سود خالص بعد از fee/slippage کمتر از حد ثابت 0.10 دلار است.", code="NET_PROFIT_BELOW_0_10", hard=True, **common)
        if indicator_ai.verdict == "NEGATIVE" and indicator_ai.experience >= 12:
            return SignalDecision(action="WATCH", accepted=False, direction=direction, entry=entry, tp=risk.tp, sl=risk.sl, score=total, threshold=SIGNAL_THRESHOLD, breakdown=breakdown, reason="AI این بازه ارز/جهت/اندیکاتور را برای Real منفی می‌داند؛ فقط Ghost/Watch.", ready_alert=False, hunter=True, signal_label="هوش مصنوعی منفی - فقط واچ", **common)

        if entry_quality.quality in {"LATE_ENTRY", "FAKE_MOVE_RISK"}:
            if total >= WATCH_THRESHOLD:
                return SignalDecision(
                    action="WATCH",
                    accepted=False,
                    direction=direction,
                    entry=entry,
                    tp=risk.tp,
                    sl=risk.sl,
                    score=total,
                    threshold=SIGNAL_THRESHOLD,
                    breakdown=breakdown,
                    reason="کیفیت نقطه ورود برای Real دیر/فیک است؛ برای Ghost/Watch ثبت شد تا AI یاد بگیرد.",
                    ready_alert=False,
                    hunter=True,
                    signal_label="فقط Ghost/Watch - ورود دیر یا فیک",
                    **common,
                )
            return self._reject(entry=entry, tp=risk.tp, sl=risk.sl, breakdown=breakdown, reason="کیفیت نقطه ورود دیر/فیک تشخیص داده شد و امتیاز برای Watch هم کافی نیست.", code="ENTRY_QUALITY_REJECT", hard=False, **common)

        if soft_direction_watch and total >= WATCH_THRESHOLD:
            return SignalDecision(
                action="WATCH",
                accepted=False,
                direction=direction,
                entry=entry,
                tp=risk.tp,
                sl=risk.sl,
                score=total,
                threshold=SIGNAL_THRESHOLD,
                breakdown=breakdown,
                reason="جهت 15m/5m هنوز برای Real کامل نیست؛ ولی جهت اولیه دارد و برای Ghost/Watch ثبت شد.",
                ready_alert=True,
                hunter=True,
                signal_label="واچ جهت اولیه اسکالپ",
                **common,
            )

        ready_alert = total >= WATCH_THRESHOLD and entry_quality.quality in {"WEAK_ENTRY", "NO_ENTRY"}
        if total >= WATCH_THRESHOLD and (entry_quality.quality in {"WEAK_ENTRY", "NO_ENTRY"} or ignition.state == "PRE_WATCH"):
            return SignalDecision(action="WATCH", accepted=False, direction=direction, entry=entry, tp=risk.tp, sl=risk.sl, score=total, threshold=SIGNAL_THRESHOLD, breakdown=breakdown, reason="شکارگاه اسکالپ آماده است ولی نقطه ورود هنوز برای Real کامل نیست.", ready_alert=ready_alert, hunter=True, signal_label="اسکالپ واچ", **common)

        accepted = (not soft_direction_watch) and total >= SIGNAL_THRESHOLD and entry_quality.quality in {"EARLY_IGNITION", "GOOD_ENTRY"}
        return SignalDecision(
            action="SIGNAL" if accepted else "REJECT",
            accepted=accepted,
            direction=direction,
            entry=entry,
            tp=risk.tp,
            sl=risk.sl,
            score=total,
            threshold=SIGNAL_THRESHOLD,
            breakdown=breakdown,
            reason="سیگنال اسکالپ معتبر است؛ شروع حرکت و نقطه ورود تایید شد." if accepted else "امتیاز یا کیفیت ورود به حد نهایی نرسید.",
            reject_code=None if accepted else "LOW_SCORE_OR_ENTRY_NOT_READY",
            hunter=entry_quality.quality in {"EARLY_IGNITION", "GOOD_ENTRY"},
            signal_label="شکار اسکالپ" if accepted else "رد اسکالپ",
            **common,
        )

    def _safe_snapshot(self, candles: list[Candle] | None) -> IndicatorSnapshot | None:
        if not candles:
            return None
        try:
            return calculate_indicators(candles)
        except Exception:
            return None

    def _reject(self, *, entry: float, breakdown: ScoreBreakdown, reason: str, code: str, direction: Direction | None = None, tp: float = 0.0, sl: float = 0.0, hard: bool = False, direction_state_1h="NEUTRAL", direction_confidence_1h: int = 0, bias_4h="NEUTRAL", setup_15m="NEUTRAL", entry_5m="NO_ENTRY", candle_pattern="NOISE", entry_stage_pct: float = 100.0, entry_quality: str = "NO_ENTRY", technical_zone: str = "NEUTRAL", indicator_profile: str = "", ai_confidence: int = 0, ai_experience: int = 0, ai_adjustment: int = 0, ai_effect: str = "neutral", net_edge: float = 0.0, estimated_profit_usdt: float = 0.0, estimated_profit_pct: float = 0.0, risk_reward: float = 0.0, estimated_cost_pct: float = 0.0, market_bias="NEUTRAL", session_state="NORMAL", order_block_state="NEUTRAL", rsi_5m: float = 0.0, rsi_15m: float = 0.0, macd_hist_5m: float = 0.0, macd_hist_15m: float = 0.0, adx_15m: float = 0.0, atr_pct_15m: float = 0.0, volume_ratio_5m: float = 0.0, volume_ratio_15m: float = 0.0, notes: tuple[str, ...] = ()) -> SignalDecision:
        return SignalDecision(action="REJECT", accepted=False, direction=direction, entry=entry, tp=tp, sl=sl, score=max(0, min(100, breakdown.total)), threshold=SIGNAL_THRESHOLD, breakdown=breakdown, reason=reason, hard_reject=hard, reject_code=code, direction_state_1h=direction_state_1h, direction_confidence_1h=direction_confidence_1h, bias_4h=bias_4h, setup_15m=setup_15m, entry_5m=entry_5m, candle_pattern=candle_pattern, entry_stage_pct=entry_stage_pct, entry_quality=entry_quality, technical_zone=technical_zone, indicator_profile=indicator_profile, ai_confidence=ai_confidence, ai_experience=ai_experience, ai_adjustment=ai_adjustment, ai_effect=ai_effect, net_edge=net_edge, estimated_profit_usdt=estimated_profit_usdt, estimated_profit_pct=estimated_profit_pct, risk_reward=risk_reward, estimated_cost_pct=estimated_cost_pct, market_bias=market_bias, session_state=session_state, order_block_state=order_block_state, rsi_5m=rsi_5m, rsi_15m=rsi_15m, macd_hist_5m=macd_hist_5m, macd_hist_15m=macd_hist_15m, adx_15m=adx_15m, atr_pct_15m=atr_pct_15m, volume_ratio_5m=volume_ratio_5m, volume_ratio_15m=volume_ratio_15m, notes=notes)
