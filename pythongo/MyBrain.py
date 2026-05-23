import pandas as pd
from copy import copy
from pythongo.MyPosition import MyPosition
from pythongo.MyOrder import MyOrder
from typing import Dict, List

"""
这里必须抽象出MyBrain -> 作为缓冲层[用户层-MyBrain-回调层]
Function1: 管理开仓/平仓的行为
MyBrain->待发送Event
MyBrain->已发送待收到回报Event
已完成Event自动销毁

Function2: 自动补全Event中的属性, 避免回调函数中的重复计算
"""

# Event 类重构
# Event(父类): 包括品种基本信息+方向+时间 symbol direction multi marginRate createTime minTimestamp maxTimestamp
# Event的子类-
#   OrderOpenEvent->关联MonitorEvent(若开仓自动创建MonitorEvent): amount vol volume minPosTimestamp maxPosTimestamp staticHigh staticLow
#   OrderCloseEvent->关联MonitorEvent(若平仓完了自动销毁MonitorEvent): vol
#   MonitorEvent: staticHigh staticLow

class Event: # 基本事件类
    def __init__(self, symbol: str, direction: str, marginRate: float, multi: int,
                 minTimestamp: pd.Timestamp = None, maxTimestamp: pd.Timestamp = None):
        self.symbol: str = symbol
        self.direction: str = direction
        self.marginRate: float = marginRate
        self.multi: int = multi
        self.createTimestamp: pd.Timestamp = pd.Timestamp.now()
        self.minTimestamp: pd.Timestamp = minTimestamp
        self.maxTimestamp: pd.Timestamp = maxTimestamp

    def copy(self) -> "Event":
        """浅拷贝自身"""
        return copy(self)

class OrderOpenEvent(Event):    # 开仓订单事件类
    def __init__(self, symbol: str, direction: str, marginRate: float, multi: int,
                 amount: float, vol: int, volume: int,
                 minTimestamp: pd.Timestamp = None, maxTimestamp: pd.Timestamp = None,
                 minPosTimestamp: pd.Timestamp = None, maxPosTimestamp: pd.Timestamp = None,
                 upLimit: float = None, downLimit: float = None):
        super(OrderOpenEvent, self).__init__(symbol=symbol, direction=direction, marginRate=marginRate, multi=multi,
                                             minTimestamp=minTimestamp, maxTimestamp=maxTimestamp)
        self.amount: float = amount
        self.vol: int = vol
        self.volume: int = volume
        self.minPosTimestamp: pd.Timestamp = minPosTimestamp
        self.maxPosTimestamp: pd.Timestamp = maxPosTimestamp
        self.upLimit: float = upLimit
        self.downLimit: float = downLimit

class OrderCloseEvent(Event):   # 平仓订单事件类
    def __init__(self, symbol: str, direction: str, marginRate: float, multi: int, vol: int,
                 minTimestamp: pd.Timestamp = None, maxTimestamp: pd.Timestamp = None):
        super(OrderCloseEvent, self).__init__(symbol=symbol, direction=direction, marginRate=marginRate, multi=multi,
                                             minTimestamp=minTimestamp, maxTimestamp=maxTimestamp)
        self.vol: int = vol

class MonitorEvent(Event):  # 仓位监控事件类
    def __init__(self, symbol: str, direction: str, marginRate: float, multi: int,
                 minTimestamp: pd.Timestamp = None, maxTimestamp: pd.Timestamp = None,
                 minPosTimestamp: pd.Timestamp = None, maxPosTimestamp: pd.Timestamp = None,
                 staticHigh: float = None, staticLow: float = None):
        super(MonitorEvent, self).__init__(symbol=symbol, direction=direction, marginRate=marginRate, multi=multi,
                                             minTimestamp=minTimestamp, maxTimestamp=maxTimestamp)
        self.minPosTimestamp: pd.Timestamp = minPosTimestamp
        self.maxPosTimestamp: pd.Timestamp = maxPosTimestamp
        self.staticHigh: float = staticHigh    # 静态最高价
        self.staticLow: float = staticLow   # 静态最低价

class MyBrain(MyPosition, MyOrder):
    def __init__(self):
        super(MyBrain, self).__init__()
        # Python中的字典是有序的
        self.eventIdx: int = 0  # 策略重启后eventIdx重新从0开始
        self.eventWait: Dict[int, Event] = {}    # 待执行event -> infiniTrader的onTick中直接调用执行
        self.eventDoing: Dict[int, Event] = {}    # 已执行event -> infiniTrader的onTick中调用执行后自动化为eventDoing
        # 初始化MyOrder & MyPosition 对象
        self.Order: MyOrder = MyOrder()
        self.Position: MyPosition = MyPosition()

    def init(self, pathStr: str, longPosFile: str, shortPosFile: str, longOrderFile: str, shortOrderFile: str) -> None:
        """MyBrain实例中的Order & Position实例初始化"""
        self.Position.inputPos(direction="long", savePath=pathStr, fileName=longPosFile)
        self.Position.inputPos(direction="short", savePath=pathStr, fileName=shortPosFile)
        self.Order.inputOrder(direction="long", savePath=pathStr, fileName=longOrderFile)
        self.Order.inputOrder(direction="short", savePath=pathStr, fileName=shortOrderFile)

    def save(self, pathStr: str, longPosFile: str, shortPosFile: str, longOrderFile: str, shortOrderFile: str) -> None:
        """MyBrain实例中的Order & Position实例保存至本地"""
        self.Position.inputPos(direction="long", savePath=pathStr, fileName=longPosFile)
        self.Position.inputPos(direction="short", savePath=pathStr, fileName=shortPosFile)
        self.Order.inputOrder(direction="long", savePath=pathStr, fileName=longOrderFile)
        self.Order.inputOrder(direction="short", savePath=pathStr, fileName=shortOrderFile)

    def addOpenEvents(self, data: pd.DataFrame, info: pd.DataFrame) -> None:
        """
        [非常重要!!!] -> 从这里之后本次策略的交易计划就定下来了, 这里一定要处理正确!
        data: 开仓计划(from PyBackTest + 已经formatter了之后)
        info: 合约信息(from DolphinDB流表)
        """
        # 先补全信息
        data = data[["symbol","direction","product","minOrderTimestamp","maxOrderTimestamp",
                     "amount","price","profitLimit","lossLimit"]]   # 这里的price是最新价 -> 用于计算vol&volume
        info.rename(columns={"contract":"symbol"}, inplace=True)
        info = info[["symbol","product","multi","longMarginRate","shortMarginRate"]]
        data = pd.merge(data, info, how="left", on=["symbol","product"])

        # 每一行->开仓事件
        for _, row in data.iterrows():
            marginRate = row["longMarginRate"] if row["direction"] == "long" else row["shortMarginRate"]
            # 计算vol(手数)以及volume(交易乘数)
            volume = int((row["amount"] / marginRate) / row["price"])
            vol = volume - volume % row["multi"]    # 向下取整
            E = OrderOpenEvent(  # 初始化对象
                symbol=row["symbol"],
                direction=row["direction"],
                amount=row["amount"],
                vol=vol,
                volume=volume,
                multi=int(row["multi"]),
                marginRate=marginRate,
                minTimestamp=pd.Timestamp(row["minOrderTimestamp"]),
                maxTimestamp=pd.Timestamp(row["maxOrderTimestamp"]),
                minPosTimestamp=pd.Timestamp(row["minPosTimestamp"]),
                maxPosTimestamp=pd.Timestamp(row["maxPosTimestamp"]),
                upLimit=row["upLimit"],
                downLimit=row["downLimit"])   # 初始化对象
            self.eventWait[self.eventIdx] = E
            self.eventIdx += 1

    def onOrder(self, status: str, symbol: str, direction: str, offset: int, totalVol: int, tradedVol: int, cancelVol: int, memo: str) -> None:
        """infiniTrader回调触发内部回调, myOrder只在乎订单完没完成, 仓位的事情交给onTrade判断
        status: Literal['未成交', '全部成交', '部分成交', '已撤销', ...] // 详见pythongo.types -> TypeOrderStatus
        symbol: str -> 合约名称
        direction: str -> 方向
        offset: int -> 开平标志
        totalVol: int -> 报单数量
        tradedVol: int -> 已经成交数量
        cancelVol: int -> 撤单数量
        memo: str -> 在MyStrategy中, 很巧妙的固定了MyBrain.eventIdx为报单memo, 这样就知道是对应哪一笔Order了

        注: 这里的onOrder其实没什么用, 只是为了向onTrader传递信息而已
        """
        oriEventIdx = int(memo)  # 原始订单事件标志
        if status == "全部成交":
            # del self.eventDoing[oriEventIdx]   # 这里要在onTrade中再删除! -> onTrade需要用到order中的信息创建Monitor
            pass
        elif status == "部分成交":
            self.eventDoing[self.eventIdx].vol = totalVol - tradedVol   # 剩余的单量
        # TODO: 这里真的是OrderData而不是TradeDate的属性嘛, 我的理解怎么都应该是部分成交之后剩下的未成交量呢
        # 总之无事发生->仍在eventDoing队列中
        return

    def onTrade(self, symbol: str, direction: str, offset: int, vol: int, price: float, memo: str) -> None:
        """infiniTrader回调触发内部回调, myPosition不仅在乎仓位开没开成功, 失败了重进队列, 成功了还需要再监控后续的仓位
        脑补:
        send_order: memo = 1(output) -> on_order: memo = 1(input) -> onOrder: memo = 1(input) ->
            on_trade: memo = 1(input) -> onTrade: memo = 1(input) + memo = 2(output) + del memo = 1 (删除已经成交的订单)
        """
        oriEventIdx = int(memo)     # 原始事件
        event = self.eventDoing[oriEventIdx]    # 原始报单Event
        if offset == 0:     # 开仓/加仓成交 -> 新建监控任务
            # 计算staticHigh & staticLow
            staticHigh: float = None
            if event.upLimit:
                if direction == "long":
                    staticHigh = (1 + event.upLimit) * price
                else:
                    staticHigh = (1 + event.downLimit) * price
            staticLow: float = None
            if event.downLimit:
                if direction == "long":
                    staticLow = (1 - event.downLimit) * price
                else:
                    staticLow = (1 - event.upLimit) * price
            self.Position.openPos(direction=direction, symbol=symbol, price=price, vol=vol,
                                  minPosTime=event.minPosTimestamp, maxPosTime=event.maxPosTimestamp,
                                  staticHigh=staticHigh, staticLow=staticLow)
            # 在本框架中, 监控任务的时间范围应最小包含持仓的时间范围(监控的优先级高于仓位, 宁愿监控不存在的仓位也不愿仓位没有被不监控)
            self.eventWait[self.eventIdx] = MonitorEvent(symbol=symbol, direction=direction,
                                                         marginRate=event.marginRate, multi=event.multi,
                                                         minTimestamp=event.minPosTimestamp, maxTimestamp=event.maxPosTimestamp,
                                                         staticHigh=staticHigh, staticLow=staticLow)
            self.eventIdx += 1
        else:   # 平仓成交: 1-平仓; 2-强平; 3-平今; 4-平昨
            self.Position.closePos(direction=direction, symbol=symbol, vol=vol)
        if vol == event.vol:    # 说明这个Event的量都完成了
            del self.eventDoing[oriEventIdx]    # 删除OpenOrderEvent/closeOrderEvent

    # TODO: onBar/run 二选一实现即可, 在相同功能实现下选取外部infiniTrader调用最简洁最易懂的方式之一
    def onBar(self, currentTime: pd.Timestamp, symbol: str, price: float) -> any:
        """Bar回调函数 -> 向self.eventWait塞入Event
        0. 监控eventWait & eventDoing中的事件是否超时 -> 超时则删除
        1. 将eventWait的任务先塞进eventDoing中, 并执行
        开仓任务: -> 输出信号
        监控任务:
        2. 监控持仓时间(时间优先, minPosTime之前直接return) -> 更新eventWait
        3. 监控止盈止损 -> 更新eventWait
        """
        return

    def run(self) -> None:
        """定期执行事件 -> 可重复触发"""
        return