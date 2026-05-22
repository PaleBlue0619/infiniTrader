import pandas as pd
from MyPosition import MyPosition
from MyOrder import MyOrder
from typing import Dict, List

"""
这里必须抽象出MyBrain -> 作为缓冲层[用户层-MyBrain-回调层]
Function1: 管理开仓/平仓的行为
MyBrain->待发送Event
MyBrain->已发送待收到回报Event
已完成Event自动销毁

Function2: 自动补全Event中的属性, 避免回调函数中的重复计算
"""

class Event:    # 基本动作 -> 开/平 * 多/空 * 手数 * * 最短/最长订单 * 最短/最长持仓 * 保证金率 * 止盈比例 * 止损比例
    def __init__(self):
        """
        开仓动作: direction + margin_rate + amount + multi + volume + vol + minOrderTimeStamp & maxOrderTimeStamp + minPosTimeStamp + maxPosTimeStamp
        平仓动作: direction + volume + vol + multi+ minOrderTimeStamp + maxOrderTimeStamp
        """
        self.symbol: str = None
        self.direction: str = None    # long/short
        self.amount: float = None
        self.volume: int = None # 总数量
        self.vol: int = None    # 下单数量(总数量 = 下单数量 * 交易乘数)
        self.multi: int = None  # 交易乘数
        self.marginRate: float = None   # 保证金率
        self.minOrderTimestamp: pd.Timestamp = None # 最短订单时间
        self.maxOrderTimestamp: pd.Timestamp = None # 最长订单时间
        self.minPosTimestamp: pd.Timestamp = None   # 最短平仓时间(不得早于该时间平仓)
        self.maxPosTimestamp: pd.Timestamp = None   # 最长持仓时间(到达该时间必须强制平仓)
        self.upLimit: float = None  # 止盈比例
        self.downLimit: float = None    # 止损比例

    def openInit(self, symbol: str, direction: str, amount: float, volume: int, vol: int, multi: int, marginRate: float,
                 minOrderTimestamp: pd.Timestamp, maxOrderTimestamp: pd.Timestamp,
                 minPosTimestamp: pd.Timestamp = None, maxPosTimestamp: pd.Timestamp = None,
                 upLimit: float = None, downLimit: float = None):
        """开仓行为初始化"""
        self.symbol = symbol
        self.direction = direction
        self.amount = amount
        self.volume = volume
        self.vol = vol
        self.multi = multi
        self.marginRate = marginRate
        self.minOrderTimestamp = minOrderTimestamp
        self.maxOrderTimestamp = maxOrderTimestamp
        self.minPosTimestamp = minPosTimestamp
        self.maxPosTimestamp = maxPosTimestamp
        self.upLimit = upLimit
        self.downLimit = downLimit

    def closeInit(self, symbol: str, direction: str, volume: int, vol: int, multi: int,
                  minOrderTimeStamp: pd.Timestamp, maxOrderTimeStamp: pd.Timestamp):
        """平仓行为初始化"""
        self.symbol = symbol
        self.direction = direction
        self.volume = volume
        self.vol = vol
        self.multi = multi
        self.minOrderTimestamp = minOrderTimeStamp
        self.maxOrderTimestamp = maxOrderTimeStamp

class MyBrain(MyPosition, MyOrder):
    def __init__(self, longPosPath: str, longPosFile: str, shortPosPath: str, shortPosFile: str,
                 longOrderPath: str, longOrderFile: str, shortOrderPath: str, shortOrderFile: str):
        super(MyBrain, self).__init__()
        # Python中的字典是有序的
        self.eventIdx: int = 0  # 策略重启后eventIdx重新从0开始
        self.eventWait: Dict[Event] = []    # 待执行event
        self.eventDoing: Dict[Event] = []    # 已执行event
        # 初始化MyOrder & MyPosition 对象
        self.Order: Myorder = MyOrder()
        self.Position: MyPosition = MyPosition()
        self.Position.inputPos(direction="long", savePath=longPosPath, fileName=longPosFile)
        self.Position.inputPos(direction="short", savePath=shortPosPath, fileName=shortPosFile)
        self.Order.inputOrder(direction="long", savePath=longOrderPath, fileName=longOrderFile)
        self.Order.inputOrder(direction="short", savePath=shortOrderPath, fileName=shortOrderFile)

    def addOpenEvent(self, data: pd.DataFrame, info: pd.DataFrame):
        """
        [非常重要!!!] -> 从这里之后本次策略的交易计划就定下来了, 这里一定要处理正确!
        data: 开仓计划(from PyBackTest + 已经formatter了之后)
        info: 合约信息(from DolphinDB流表)
        """
        # 先补全信息
        data = data[["symbol","direction","product","minOrderTimestamp","maxOrderTimestamp",
                     "amount","profitLimit","lossLimit"]]
        info.rename(columns={"contract":"symbol"}, inplace=True)
        info = info[["symbol","product","multi","longMarginRate","shortMarginRate"]]
        data = pd.merge(data, info, how="left", on=["symbol","product"])
        # 每一行->开仓事件
        for _, row in data.iterrows():
            E = Event()  # 初始化对象
            marginRate = row["longMarginRate"] if row["direction"] == "long" else row["shortMarginRate"]
            E.openInit(
                symbol=row["symbol"],
                direction=row["direction"],
                amount=row["amount"],
                vol=int(row["vol"]),
                volume=int(row["volume"]),
                multi=int(row["multi"]),
                marginRate=marginRate,
                minOrderTimestamp=pd.Timestamp(row["minOrderTimestamp"]),
                maxOrderTimestamp=pd.Timestamp(row["maxOrderTimestamp"]),
                minPosTimestamp=pd.Timestamp(row["minPosTimestamp"]),
                maxPosTimestamp=pd.Timestamp(row["maxPosTimestamp"]),
                upLimit=row["upLimit"],
                downLimit=row["downLimit"])   # 初始化对象
            self.eventWait[self.eventIdx] = E
            self.eventIdx += 1

