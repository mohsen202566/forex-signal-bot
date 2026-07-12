from __future__ import annotations
from dataclasses import dataclass, field
from market_engine import MarketAnalysis
from setup_engine import SetupCandidate
from watch_engine import WatchEvaluation
import config

@dataclass
class TradeDecision:
    action:str; final_score:float; confidence:float; allowed:bool; primary_reason:str; module_scores:dict[str,float]=field(default_factory=dict); contradictions:list[str]=field(default_factory=list)

class DecisionEngine:
    def decide(self,m:MarketAnalysis,s:SetupCandidate,w:WatchEvaluation):
        safety=max(0.0,100.0-m.fragility_score*.45-m.exhaustion_risk*.35)
        scores={'direction':m.direction_score,'strength':m.strength_score,'freshness':m.freshness_score,'setup':s.score,'trigger':w.trigger_score,'safety':safety}
        final=.20*scores['direction']+.15*scores['strength']+.15*scores['freshness']+.20*scores['setup']+.20*scores['trigger']+.10*scores['safety']
        conflict_penalty=min(18.0,4.0*len(m.contradictions))
        final=max(0.0,final-conflict_penalty)
        hard=m.hard_veto or w.state in {'INVALIDATED','EXPIRED'}
        minimums=(
            m.direction_score >= config.DIRECTION_MIN
            and m.strength_score >= config.STRENGTH_MIN
            and m.freshness_score >= config.FRESHNESS_MIN
            and s.score >= config.SETUP_MIN
            and w.trigger_score >= config.TRIGGER_MIN
            and safety >= config.SAFETY_MIN
        )
        allowed=not hard and minimums and final>=config.FINAL_MIN and w.confirmed
        action=f'SIGNAL_{s.side}' if allowed else ('KEEP_WATCHING' if not hard else 'REJECT')
        reason='هم‌گرایی جهت، قدرت، ستاپ و تریگر' if allowed else ('تریگر یا امتیازها هنوز کافی نیست' if not hard else w.reason)
        confidence=max(0.0,min(m.confidence,final,100.0-conflict_penalty))
        return TradeDecision(action,round(final,2),round(confidence,2),allowed,reason,scores,m.contradictions)
