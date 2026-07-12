from __future__ import annotations
from dataclasses import dataclass
import config
from setup_engine import SetupCandidate
from decision_engine import TradeDecision

@dataclass
class RiskPlan:
    entry:float; tp:float; sl:float; sl_pct:float; tp_pct:float; gross_rr:float; net_rr:float; trade_usdt:float; leverage:int; notional_usdt:float; estimated_net_profit:float; estimated_net_loss:float; estimated_cost_win:float; estimated_cost_loss:float; valid:bool; reason:str

class RiskEngine:
    def build(self,s:SetupCandidate,d:TradeDecision,entry:float,trade_usdt:float,leverage:int):
        if entry<=0 or not (config.TRADE_USDT_MIN<=trade_usdt<=config.TRADE_USDT_MAX) or not (config.LEVERAGE_MIN<=leverage<=config.LEVERAGE_MAX):
            return RiskPlan(entry,0,0,0,0,0,0,trade_usdt,leverage,max(0,trade_usdt*leverage),0,0,0,0,False,'ورودی ریسک نامعتبر است')
        atr=float(s.meta.get('atr',0)); structural=abs(entry-s.invalidation_price)/entry*100; buffer=(atr/entry*100*.12) if atr>0 else 0
        sl_pct=max(config.MIN_SL_PCT,structural+buffer)
        max_sl=config.ADAPTIVE_MAX_SL_PCT if d.final_score>=88 else config.NORMAL_MAX_SL_PCT
        if sl_pct>max_sl:
            return RiskPlan(entry,0,0,sl_pct,0,0,0,trade_usdt,leverage,trade_usdt*leverage,0,0,0,0,False,'استاپ برای اسکالپ بیش از حد دور است')
        fee=2*config.TOOBIT_FUTURES_TAKER_FEE_PCT
        win_cost_pct=fee+config.ENTRY_SLIPPAGE_PCT+config.TP_SLIPPAGE_PCT
        loss_cost_pct=fee+config.ENTRY_SLIPPAGE_PCT+config.SL_SLIPPAGE_PCT
        if s.setup_type=='COMPRESSION_BREAKOUT':
            target=1.45 if d.final_score<88 else 1.60
        elif s.setup_type=='STRUCTURE_BREAK_RETEST':
            target=1.40 if d.final_score<88 else 1.50
        else:
            target=config.STRONG_NET_RR if d.final_score>=84 else config.TARGET_NET_RR
        tp_pct=target*(sl_pct+loss_cost_pct)+win_cost_pct
        tp=entry*(1+tp_pct/100) if s.side=='LONG' else entry*(1-tp_pct/100)
        sl=entry*(1-sl_pct/100) if s.side=='LONG' else entry*(1+sl_pct/100)
        obstacle=s.meta.get('obstacle_price')
        if obstacle:
            obstacle_pct=((float(obstacle)-entry)/entry*100) if s.side=='LONG' else ((entry-float(obstacle))/entry*100)
            safety_buffer=(atr/entry*100*.15) if atr>0 else 0
            if obstacle_pct>0 and obstacle_pct < tp_pct+safety_buffer:
                return RiskPlan(entry,tp,sl,sl_pct,tp_pct,tp_pct/sl_pct if sl_pct else 0,0,trade_usdt,leverage,trade_usdt*leverage,0,0,0,0,False,'فضای واقعی تا تارگت کافی نیست')
        notional=trade_usdt*leverage
        win_cost=notional*win_cost_pct/100; loss_cost=notional*loss_cost_pct/100
        net_profit=notional*tp_pct/100-win_cost; net_loss=notional*sl_pct/100+loss_cost
        net_rr=net_profit/net_loss if net_loss else 0
        min_profit=max(config.MIN_NET_PROFIT_USDT,trade_usdt*config.MIN_NET_RETURN_ON_MARGIN_PCT/100)
        valid=net_profit>=min_profit and net_rr>=config.MIN_NET_RR_ABSOLUTE and tp>0 and sl>0
        return RiskPlan(entry,tp,sl,sl_pct,tp_pct,tp_pct/sl_pct if sl_pct else 0,net_rr,trade_usdt,leverage,notional,net_profit,net_loss,win_cost,loss_cost,valid,'معتبر' if valid else 'سود خالص یا RR خالص کافی نیست')
