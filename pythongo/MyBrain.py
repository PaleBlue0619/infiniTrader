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
整体原则: 先确定eventWait eventDoing中的编号, 再输出执行
开仓From: 历史未下单的开仓Order + 外部开仓信号csv 
平仓From: 历史未下单的平仓Order + 监控(止盈止损+最长持仓时间)
"""

# Event 类重构
# Event(父类): 包括品种基本信息+方向+时间 symbol direction multi marginRate createTime minTimestamp maxTimestamp
# Event的子类-
#   OrderOpenEvent: amount vol volume minPosTimestamp maxPosTimestamp staticHigh staticLow
#   OrderCloseEvent: vol

class Event:  # 基本事件类
    def __init__(self, symbol: str, direction: str, marginRate: float = None, multi: int = None,
                 minTimestamp: pd.Timestamp = None, maxTimestamp: pd.Timestamp = None, memo: str = ""):
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

class MyBrain(MyPosition, MyOrder):
    def __init__(self):
        super(MyBrain, self).__init__()
        # Python中的字典是有序的
        self.eventIdx: int = 0  # 策略重启后eventIdx重新从0开始
        self.eventWait: Dict[int, Event] = {}    # 待执行event -> infiniTrader的onTick中直接调用执行
        self.eventDoing: Dict[int, Event] = {}    # 已执行event -> infiniTrader的onTick中调用执行后自动化为eventDoing
        # 初始化MyOrder & MyPosition 对象
        self.Order: MyOrder = MyOrder()             # JUST FOR RECORD
        self.Position: MyPosition = MyPosition()    # JUST FOR RECORD
        self.lastMinute: int = pd.Timestamp.now().minute
        self.longMarginRateDict: Dict[str, float] = {}
        self.shortMarginRateDict: Dict[str, float] = {}
        self.multiDict: Dict[str, float] = {}

    def init(self, pathStr: str, longPosFile: str, shortPosFile: str, orderFile: str) -> None:
        """MyBrain实例中的Order & Position实例初始化"""
        self.Position.inputPos(direction="long", savePath=pathStr, fileName=longPosFile)
        self.Position.inputPos(direction="short", savePath=pathStr, fileName=shortPosFile)
        self.Order.inputOrder(savePath=pathStr, fileName=orderFile)

    def save(self, pathStr: str, longPosFile: str, shortPosFile: str, orderFile: str) -> None:
        """MyBrain实例中的Order & Position实例保存至本地"""
        self.Position.outputPos(direction="long", savePath=pathStr, fileName=longPosFile)
        self.Position.inputPos(direction="short", savePath=pathStr, fileName=shortPosFile)
        self.Order.outputOrder(savePath=pathStr, fileName=orderFile)

    def linkOrderId(self, idDict: Dict[int, int]) -> None:
        """批量给Event附上orderID属性(send_order返回orderID)"""
        for memo, orderId in idDict.items():
            if int(memo) in self.eventDoing:
                self.eventDoing[int(memo)].orderId = int(orderId)
                if int(orderId) == -1:  # 说明该event失败了
                    del self.eventDoing[int(memo)]
                    # TODO: 接后续处理 -> 继续报单还是就此了结?

    def addInfoData(self, info: pd.DataFrame) -> None:
        """加载info信息"""
        # 先补全信息
        info = info[["contract", "product", "multi", "longMarginRate", "shortMarginRate"]]
        self.longMarginRateDict: Dict[str, float] = dict(zip(info["contract"], info["longMarginRate"]))
        self.shortMarginRateDict: Dict[str, float] = dict(zip(info["contract"], info["shortMarginRate"]))
        self.multiDict: Dict[str, int] = dict(zip(info["contract"], info["multi"]))

    def addHistEvents(self) -> None:
        """Step1. 加载历史未完成订单"""
        # Step1. 历史未完成订单 -> eventWait(orderOpenEvent)
        orderDict = self.Order.getOrder()
        deleteIdx: List[int] = []
        if len(orderDict) > 0:
            for idx, order in self.orderDict.items():
                symbol = order["symbol"]
                if order["state"] == "open":  # 开仓 + 多单
                    if order["direction"] == "long":
                        if symbol not in self.longMarginRateDict:  # 说明不是主力合约/没有该合约的信息
                            deleteIdx.append(idx)
                            continue
                        marginRate = self.longMarginRateDict[symbol]
                    else:
                        if symbol not in self.shortMarginRateDict:
                            deleteIdx.append(idx)
                            continue
                        marginRate = self.shortMarginRateDict[symbol]
                    multi = self.multiDict[symbol]
                    vol = int(order["vol"])
                    volume = vol * multi
                    self.eventIdx += 1
                    E = OrderOpenEvent(  # 初始化对象
                        symbol=symbol,
                        direction=order["direction"],
                        amount=int(order["vol"] * order["price"]),
                        vol=vol,
                        volume=volume,
                        multi=multi,
                        marginRate=marginRate,
                        minTimestamp=order["minOrderTime"],
                        maxTimestamp=order["maxOrderTime"],
                        minPosTimestamp=order["minPosTime"],
                        maxPosTimestamp=order["maxPosTime"],
                        upLimit=order["upLimit"],
                        downLimit=order["downLimit"],
                        memo=str(self.eventIdx)
                    )
                    self.eventWait[self.eventIdx] = E
                else:  # 平仓
                    self.eventIdx += 1
                    E = OrderCloseEvent(
                        symbol=symbol,
                        direction=order["direction"],
                        vol=int(order["vol"]),
                        minTimestamp=order["minOrderTime"],
                        maxTimestamp=order["maxOrderTime"],
                        memo=str(self.eventIdx)
                    )
                    self.eventWait[self.eventIdx] = E
        if deleteIdx:
            for idx in self.deleteIdx:
                self.Order.cancelOrder(idx=idx)

    def addOpenEvents(self, data: pd.DataFrame, info: pd.DataFrame) -> None:
        """
        Step2. 加入本次开仓信息
        [非常重要!!!] -> 从这里之后本次策略的交易计划就定下来了, 这里一定要处理正确!
        data: 开仓计划(from PyBackTest + 已经formatter了之后)
        info: 合约信息(from DolphinDB流表)
        """
        # Step2. 今日开仓计划
        info = info[["contract", "product", "multi", "longMarginRate", "shortMarginRate",
                     "hasNightTrade", "openTime", "closeTime"]].rename(
            columns={"contract": "symbol"}
        )
        data = data[["symbol","direction","product", "minOrderTimestamp", "maxOrderTimestamp",
                     "minPosTimestamp", "maxPosTimestamp", "amount","price","upLimit","downLimit"]]   # 这里的price是最新价 -> 用于计算vol&volume
        data = pd.merge(data, info, how="left", on=["symbol","product"])
        for _, row in data.iterrows():         # 每一行->开仓事件
            marginRate = row["longMarginRate"] if row["direction"] == "long" else row["shortMarginRate"]
            # 计算vol(手数)以及volume(交易乘数)
            volume = int((row["amount"] / marginRate) / row["price"])
            vol = volume - volume % row["multi"]    # 向下取整
            self.eventIdx += 1
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
                minPosTimestamp=pd.Timestamp.now(),
                maxPosTimestamp=row["openTime"] + pd.offsets.BusinessDay(3) - pd.offsets.Minute(180),  # 保证3天开盘后自动平仓
                upLimit=row["upLimit"],
                downLimit=row["downLimit"],
                memo=str(self.eventIdx))   # 初始化对象
            self.eventWait[self.eventIdx] = E

    def onCancel(self, orderId: int) -> None:
        """撤单回调函数
        删除eventId中orderId为上述orderId的标的
        """
        eventIdList = list(self.eventDoing.keys())
        orderIdList = [order.orderId for order in self.eventDoing.values()]
        idxList = [i for i in range(0, len(orderIdList)) if orderIdList[i] == orderId]
        for idx in idxList:
            eventId = eventIdList[idx]
            del self.eventDoing[eventId]

    def onOrder(self, currentTime: pd.Timestamp, status: str, symbol: str, direction: str, offset: int,
                totalVol: int, tradedVol: int, cancelVol: int, memo: str) -> None:
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
            self.eventDoing[oriEventIdx].delete = True
            pass
        elif status == "部分成交":
            self.eventDoing[oriEventIdx].vol = totalVol - tradedVol   # 剩余的单量
        # TODO: 这里真的是OrderData而不是TradeDate的属性嘛, 我的理解怎么都应该是部分成交之后剩下的未成交量呢
        else:
            self.eventDoing[oriEventIdx].delete = True
        # 总之无事发生->仍在eventDoing队列中
        return

    def onTrade(self, currentTime: pd.Timestamp, symbol: str, direction: str, offset: int, vol: int, price: float, memo: str) -> None:
        """infiniTrader回调触发内部回调, myPosition只需要修改MyPosition的状态, 并删除eventDoing中的事件
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
        else:   # 平仓成交: 1-平仓; 2-强平; 3-平今; 4-平昨
            self.Position.closePos(direction=direction, symbol=symbol, vol=vol)
        if event.delete:    # 说明这个Event的量都完成了
            del self.eventDoing[oriEventIdx]    # 删除OpenOrderEvent/closeOrderEvent
            self.Order.cancelOrder(idx=oriEventIdx)

    def onBar(self, currentTime: pd.Timestamp, symbol: str, price: float) -> Dict[int, OrderOpenEvent | OrderCloseEvent]:
        """Bar回调函数 -> 向self.eventWait塞入Event -> 返回eventDict(有序)
        0. 监控eventWait & eventDoing中的事件是否超时 -> 超时则删除
        开仓任务
        1. 将eventWait的任务先塞进eventDoing中, 并输出信号
        监控任务（onBar中实现）:
        2. 监控持仓时间(时间优先, minPosTime之前直接break)
        3. 监控止盈止损
        """
        toDoDict = {}
        if self.lastMinute != currentTime.minute:   # 说明Bar发生了变动 -> eventWait需要塞进eventDoing
            self.lastMinute = currentTime.minute    # 更新lastMinute
            todoDict = self.eventWait.copy()
            for idx, event in self.eventWait.items():   # eventWait 塞进 eventDoing
                self.eventDoing[idx] = event
            self.eventWait = {}

        # 监控任务
        if symbol in self.Position.longPos:
            posList: List[Dict[str, any]] = self.Position.longPos[symbol]   # 持仓List
            # 止盈止损是FIFO触发的
            totalVol: int = 0   # 需要平仓的数量
            for pos in posList:
                if pos["minPosTimestamp"]:
                    if currentTime <= pos["minPosTimestamp"]:
                        break   # 不需要平仓 + 后面的仓位也不需要检测
                if pos["maxPosTimestamp"]:
                    if currentTime >= pos["maxPosTimestamp"]:
                        totalVol += pos.vol
                        continue
                if pos["staticHigh"]:
                    if pos["staticHigh"] <= price:  # 静态最高价
                        totalVol += pos.vol
                        continue
                if pos["staticLow"]:
                    if pos["staticLow"] >= price:  # 静态最低价
                        totalVol += pos.vol
                        continue
            if totalVol > 0:
                self.eventIdx += 1
                E = OrderCloseEvent(symbol=symbol, direction="long", vol=totalVol, memo=str(self.eventIdx))
                self.eventDoing[self.eventIdx] = E  # 这里跳过eventWait, 直接加入eventDoing
                toDoDict[str(self.eventIdx)] = E

        if symbol in self.Position.shortPos:
            posList: List[Dict[str, any]] = self.Position.shortPos[symbol]  # 持仓list
            # 止盈止损也是FIFO触发的
            totalVol: int = 0  # 需要平仓的数量
            for pos in posList:
                if pos["minPosTimestamp"]:
                    if currentTime <= pos["minPosTimestamp"]:
                        break  # 不需要平仓 + 后面的仓位也不需要检测
                if pos["maxPosTimestamp"]:
                    if currentTime >= pos["maxPosTimestamp"]:
                        totalVol += pos.vol
                        continue
                if pos["staticHigh"]:
                    if pos["staticHigh"] <= price:  # 静态最高价
                        totalVol += pos.vol
                        continue
                if pos["staticLow"]:
                    if pos["staticLow"] >= price:  # 静态最低价
                        totalVol += pos.vol
                        continue
            if totalVol > 0:
                self.eventIdx += 1
                E = OrderCloseEvent(symbol=symbol, direction="short", vol=totalVol, memo=str(self.eventIdx))
                self.eventDoing[self.eventIdx] = E  # 这里跳过eventWait, 直接加入eventDoing
                toDoDict[str(self.eventIdx)] = E

        return toDoDict
