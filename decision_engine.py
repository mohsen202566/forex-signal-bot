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
    @staticmethod
    def _thresholds(setup_type: str) -> dict[str, float]:
        if setup_type == 'COMPRESSION_BREAKOUT':
            return {
                'direction': 60.0, 'strength': 58.0, 'freshness': 55.0,
                'setup': config.BREAKOUT_SETUP_MIN, 'trigger': config.BREAKOUT_TRIGGER_MIN,
                'safety': 55.0, 'final': config.BREAKOUT_FINAL_MIN,
            }
        if setup_type == 'STRUCTURE_BREAK_RETEST':
            return {
                'direction': 62.0, 'strength': 55.0, 'freshness': 54.0,
                'setup': config.STRUCTURE_SETUP_MIN, 'trigger': config.STRUCTURE_TRIGGER_MIN,
                'safety': 57.0, 'final': config.STRUCTURE_FINAL_MIN,
            }
        return {
            'direction': config.DIRECTION_MIN, 'strength': config.STRENGTH_MIN,
            'freshness': config.FRESHNESS_MIN, 'setup': config.PULLBACK_SETUP_MIN,
            'trigger': config.PULLBACK_TRIGGER_MIN, 'safety': config.SAFETY_MIN,
            'final': config.PULLBACK_FINAL_MIN,
        }

    def decide(self,m:MarketAnalysis,s:SetupCandidate,w:WatchEvaluation):
        safety=max(0.0,100.0-m.fragility_score*.45-m.exhaustion_risk*.35)
        scores={'direction':m.direction_score,'strength':m.strength_score,'freshness':m.freshness_score,'setup':s.score,'trigger':w.trigger_score,'safety':safety}
        # Trigger remains important, but setup and direction are not allowed to be drowned by one weak sub-score.
        final=.20*scores['direction']+.15*scores['strength']+.14*scores['freshness']+.22*scores['setup']+.19*scores['trigger']+.10*scores['safety']
        conflict_penalty=min(14.0,3.0*len(m.contradictions))
        final=max(0.0,final-conflict_penalty)
        hard=m.hard_veto or w.state in {'INVALIDATED','EXPIRED'}
        t=self._thresholds(s.setup_type)
        failed=[]
        for key in ('direction','strength','freshness','setup','trigger','safety'):
            if scores[key] < t[key]:
                failed.append(f"{key}={scores[key]:.1f}<{t[key]:.1f}")
        if final < t['final']:
            failed.append(f"final={final:.1f}<{t['final']:.1f}")
        minimums=not failed
        allowed=not hard and minimums and w.confirmed
        action=f'SIGNAL_{s.side}' if allowed else ('KEEP_WATCHING' if not hard else 'REJECT')
        if allowed:
            reason='هم‌گرایی جهت، قدرت، ستاپ و تریگر'
        elif hard:
            reason=w.reason if w.state in {'INVALIDATED','EXPIRED'} else 'Hard Veto بازار فعال است'
        elif failed:
            reason='شرط‌های باقی‌مانده: ' + '، '.join(failed)
        else:
            reason='تریگر هنوز تأیید نشده است'
        confidence=max(0.0,min(m.confidence,final,100.0-conflict_penalty))
        return TradeDecision(action,round(final,2),round(confidence,2),allowed,reason,scores,m.contradictions)
