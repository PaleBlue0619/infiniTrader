import pandas as pd
from copy import copy
from pythongo.MyPosition import MyPosition
from pythongo.MyOrder import MyOrder
from typing import Dict, List

# Event 类重构
# Event(父类): 包括品种基本信息+方向+时间 symbol direction multi marginRate createTime minTimestamp maxTimestamp
# Event的子类-
#   OrderOpenEvent: amount vol volume minPosTimestamp maxPosTimestamp staticHigh staticLow
#   OrderCloseEvent: vol

class Event:  # 基本事件类
    def __init__(self, symbol: str, direction: str, marginRate: float = None, multi: int = None,
                 minTimestamp: pd.Timestamp = None, maxTimestamp: pd.Timestamp = None, memo: str = ""):
        self.state: str = ""
        self.symbol: str = symbol
        self.direction: str = direction
        self.marginRate: float = marginRate
        self.multi: int = multi
        self.createTimestamp: pd.Timestamp = pd.Timestamp.now()
        self.minTimestamp: pd.Timestamp = minTimestamp
        self.maxTimestamp: pd.Timestamp = maxTimestamp
        self.memo: str = memo   # 事件备注
        self.delete: bool = False   # 该事件是否应该被删除(部分成交/其他未执行完的事件-> False)
        self.orderId: int = None    # 订单编号

    def copy(self) -> "Event":
        """浅拷贝自身"""
        return copy(self)

class OrderOpenEvent(Event):    # 开仓订单事件类
    def __init__(self, symbol: str, direction: str, marginRate: float, multi: int,
                 amount: float, vol: int, volume: int,
                 minTimestamp: pd.Timestamp = None, maxTimestamp: pd.Timestamp = None,
                 minPosTimestamp: pd.Timestamp = None, maxPosTimestamp: pd.Timestamp = None,
                 upLimit: float = None, downLimit: float = None, memo: str = ""):
        super(OrderOpenEvent, self).__init__(symbol=symbol, direction=direction, marginRate=marginRate, multi=multi,
                                             minTimestamp=minTimestamp, maxTimestamp=maxTimestamp, memo=memo)
        self.state: str = "open"
        self.amount: float = amount
        self.vol: int = vol
        self.volume: int = volume
        self.minPosTimestamp: pd.Timestamp = minPosTimestamp
        self.maxPosTimestamp: pd.Timestamp = maxPosTimestamp
        self.upLimit: float = upLimit
        self.downLimit: float = downLimit

class OrderCloseEvent(Event):   # 平仓订单事件类
    def __init__(self, symbol: str, direction: str, vol: int, marginRate: float = None, multi: int = None,
                 minTimestamp: pd.Timestamp = None, maxTimestamp: pd.Timestamp = None, memo: str = ""):
        super(OrderCloseEvent, self).__init__(symbol=symbol, direction=direction, marginRate=marginRate, multi=multi,
                                             minTimestamp=minTimestamp, maxTimestamp=maxTimestamp, memo=memo)
        self.state = "close"
        self.vol: int = vol
