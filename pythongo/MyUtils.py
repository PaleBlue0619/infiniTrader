import pandas as pd
import dolphindb as ddb
from typing import List, Dict

def product_formatter(productList: List[str], infoDict: Dict[str, Dict[str, any]]) -> List[str]:
    """把品种代码映射为无限易的代码"""
    lower_product_list = [str(i).lower() for i in infoDict.keys()]
    format_product_list = list(infoDict.keys())
    resultList: List[str] = []
    for i in productList:
        formatted_product = str(i).lower()
        if formatted_product in lower_product_list:
            idx = lower_product_list.index(formatted_product)
            resultList.append(format_product_list[idx])
        else:
            resultList.append(i)    # 原来啥样就是啥样
    return resultList

def contract_formatter(contractList: List[str], infoDict: Dict[str, Dict[str, any]]) -> List[str]:
    """把合约代码映射为无限易的代码"""
    contractList = [str(i).split(".")[0] for i in contractList]  # AU2601.SHF -> AU2601
    productList = ["".join([j for j in str(i) if str(j).isalpha()]) for i in contractList]
    timeList = ["".join([j for j in str(i) if str(j).isdigit()]) for i in contractList]
    productList_format = product_formatter(productList=productList, infoDict=infoDict)
    integerList = [infoDict[product]["format"] for product in productList_format]
    resultList = []
    for i in range(0, len(productList_format)):
        product = productList_format[i]
        if len(timeList[i]) == 4 and integerList[i] == 3:
            year = timeList[i][1:]
        elif len(timeList[i]) == 3 and integerList[i] == 4:
            year = "2"+timeList[i]
        else:
            year = timeList[i]  # len = 4 + i = 4; len = 3 + i = 3
        resultList.append(str(product) + str(year))
    return resultList

def createInfoTable(session: ddb.session, tableName: str, dropTB: bool = False):
    """DolphinDB 合约信息流表"""
    colNames = ["product", "exchange", "contract", "multi", "longMarginRate", "shortMarginRate", "hasNightTrade",
                "openTime", "closeTime", "nightOpenTime", "nightCloseTime", "dayOpenTime", "dayCloseTime", "isMainContract"]
    colTypes = ["SYMBOL", "SYMBOL", "SYMBOL", "INT", "DOUBLE", "DOUBLE", "INT",
                "TIMESTAMP", "TIMESTAMP", "TIMESTAMP", "TIMESTAMP", "TIMESTAMP", "TIMESTAMP", "INT"]
    # hasNightTrade: 是否有夜盘交易 -> openTime = iif(hasNightTrade == 1, nightOpenTime, dayOpenTime);  closeTime = dayCloseTime
    # xxxTime -> 全部以24小时制分钟计时
    session.upload({"colNames": colNames, "colTypes": colTypes})
    session.run(f"""
    if ({int(dropTB)} == 1){{
        try{{undef("{tableName}", SHARED)}}catch(ex){{}}; // 先删除共享表
    }};
    tab = table(1:0, colNames, colTypes);
    share(tab, "{tableName}"); // 创建共享内存表
    """)

def createOrderTable(session: ddb.session, tableName: str, dropTB: bool = False):
    """DolphinDB 订单流表"""
    colNames = ["exchange", "contract", "price", "orderId", "orderSysId",
                "orderPriceType", "direction", "offset", "cancelTime", "orderTime", "currentTime"]
    colTypes = ["SYMBOL", "SYMBOL", "DOUBLE", "INT", "STRING",
                "INT", "INT", "INT", "TIMESTAMP", "TIMESTAMP", "TIMESTAMP"]
    # orderPriceType 需要 string -> int
    # direction 需要 string -> int
    # cancelTime&orderTime 需要 string -> pd.Timestamp
    session.upload({"colNames": colNames, "colTypes": colTypes})
    session.run(f"""
    if ({int(dropTB)} == 1){{
        try{{undef("{tableName}", SHARED)}}catch(ex){{}}; // 先删除共享表
    }};
    tab = table(1:0, colNames, colTypes);
    share(tab, "{tableName}"); // 创建共享内存表
    """)

def createTradeTable(session: ddb.session, tableName: str, dropTB: bool = False):
    """"DolphinDB 交易流表"""
    colNames = ["exchange", "contract", "tradeId", "orderId", "orderSysId", "tradeTime",
                "direction", "offset", "price", "volume", "status", "memo", "currentTime"]
    colTypes = ["SYMBOL", "SYMBOL", "INT", "INT", "INT", "TIMESTAMP",
                "INT", "INT", "DOUBLE", "INT", "STRING", "STRING", "TIMESTAMP"]
    # direction 需要 string -> int
    session.upload({"colNames": colNames, "colTypes": colTypes})
    session.run(f"""
    if ({int(dropTB)} == 1){{
        try{{undef("{tableName}", SHARED)}}catch(ex){{}}; // 先删除共享表
    }};
    tab = table(1:0, colNames, colTypes);
    share(tab, "{tableName}"); // 创建共享内存表
    """)

def process_marginRate(filePath: str, infoDict: Dict[str, Dict[str, any]], savePath: str = None, fileName: str = None) -> pd.DataFrame:
    """
    FROM交易星球: https://www.jiaoyixingqiu.com/shouxufei/all -> 规整的DataFrame格式
    product contract openMarginRate closeMarginRate margin
    savePath为None时不保存
    """
    # 尝试用 HTML 读取
    tables = pd.read_html(filePath,header=2, index_col=None, encoding="utf-8")
    data = tables[0][["合约代码","买开%","卖开%","保证金/元","备注"]]
    data.columns = ["contract","longMarginRate","shortMarginRate","margin","isMainContract"]
    # 去除合约代码包含中文字符的行
    data = data[~data['contract'].str.contains(r'[\u4e00-\u9fff]', na=False)].reset_index(drop=True)
    # 去除合约代码以字母结尾的行
    data = data[~data['contract'].str[-1].str.isalpha()].reset_index(drop=True)
    data["contract"] = contract_formatter(contractList=list(data["contract"]), infoDict=infoDict)
    data["longMarginRate"] = data["longMarginRate"].apply(lambda x: float(str(x).replace("%",""))/100)    # %->float
    data["shortMarginRate"] = data["shortMarginRate"].apply(lambda x: float(str(x).replace("%",""))/100)    # %->float
    data["margin"] = pd.to_numeric(data["margin"])
    data["isMainContract"] = data["isMainContract"].apply(lambda x: 1 if x == "主力" else 0)  # 主力合约标志
    if savePath and fileName:
        data.to_csv(rf"{savePath}\{fileName}", index=None)
    return data

def get_info(self, monitorProduct: List[str] = None, deleteProduct: List[str] = None) -> pd.DataFrame:
    """获取品种基本信息
    TODO: 需要思考备用数据channel -> 万一这个交易星球网崩了/缺数据怎么办 -> 转tushare futSettle补全数据
    """
    # 处理外部输入的marginRate数据 + 市场合约数据
    infoDF = process_marginRate(filePath=rf"{self.pathStr}\{self.config['record']['marginFile']}", infoDict=self.infoDict,
                                savePath=self.pathStr, fileName="marginInfo.csv")
    # 交易星球数据不如infiniTrader自身给的主力合约质量高
    mainContDF = pd.read_excel(rf"{self.pathStr}\{self.config['record']['infiniFile']}",index_col=None, header=0)
    mainContDict = dict(zip(mainContDF["品种"], mainContDF["合约名称"]))
    infoDF = infoDF[infoDF["isMainContract"] == 1].reset_index(drop=True)
    infoDF["product"] = infoDF["contract"].apply(lambda x: "".join([str(i) for i in x if str(i).isalpha()]))
    infoDF["contract"] = infoDF["product"].map(mainContDict)    # 更新主力合约 -> 交易星球的大写字母合约real_html解析会吞掉前面的年份, 但年份无法确定, 保险起见全部用无限易的主力合约
    if monitorProduct:
        infoDF = infoDF[infoDF["product"].isin(monitorProduct)].reset_index(drop=True)
    if deleteProduct:
        infoDF = infoDF[~infoDF["product"].isin(deleteProduct)].reset_index(drop=True)
    infoDF["exchange"] = infoDF["product"].apply(lambda x: self.infoDict[x]["exchange"])
    infoDF["multi"] = infoDF["product"].apply(lambda x: self.infoDict[x]["multi"])
    infoDF["hasNightTrade"] = infoDF["product"].apply(lambda x: True if self.infoDict[x]["nightTime"] else False)
    currentTime = pd.Timestamp.now()
    currentMinute = int(currentTime.hour * 100 + currentTime.minute)
    """
    让我们来仔细想一下如何实现不同时间段启动策略都能看到正确的时间, 因为
    [0000, 0230] -> 这时候启动策略一定是上一个交易日的延续的夜盘 -> nightOpen: 昨天, nightClose: 今天, dayOpen: 今天, dayClose: 今天
    [0231, 1500] -> 这时候启动策略一定是今天日盘 -> nightOpen: 今天, nightClose: 今天/明天, dayOpen: 今天, dayClose: 今天 (因为我不做国债期货所以取1500为分界点)
    [1501, 2359] -> 这时候启动策略一定是今天夜盘 -> nightOpen: 今天, nightClose: 今天/明天, dayOpen: 明天, dayClose: 明天
    """
    lastDateStr = pd.Timestamp(pd.Timestamp.now().date() - pd.offsets.BusinessDay(1)).strftime("%Y-%m-%d")  # 2026-05-20
    currentDateStr = pd.Timestamp.now().date().strftime("%Y-%m-%d")   # 2026-05-21
    nextDateStr = pd.Timestamp(pd.Timestamp.now().date() + pd.offsets.BusinessDay(1)).strftime("%Y-%m-%d")  # 2026-05-22
    infoDF["nightOpenTime"] = infoDF["product"].apply(lambda x: str(self.infoDict[x]["nightTime"][0]).zfill(4) if self.infoDict[x]["nightTime"] else None)
    infoDF["nightCloseTime"] = infoDF["product"].apply(lambda x: str(self.infoDict[x]["nightTime"][1]).zfill(4) if self.infoDict[x]["nightTime"] else None)
    infoDF["dayOpenTime"] = infoDF["product"].apply(lambda x: str(self.infoDict[x]["dayTime"][0]).zfill(4) if self.infoDict[x]["dayTime"] else None)
    infoDF["dayCloseTime"] = infoDF["product"].apply(lambda x: str(self.infoDict[x]["dayTime"][1]).zfill(4) if self.infoDict[x]["dayTime"] else None)
    if currentMinute <= 230:    # 上一个交易日延续的夜盘
        infoDF["nightOpenTime"] = infoDF["nightOpenTime"].apply(lambda x:pd.Timestamp(lastDateStr+" "+x[:2]+":"+x[2:]+":00") if x else None)
        infoDF["nightCloseTime"] = infoDF["nightCloseTime"].apply(lambda x:pd.Timestamp(currentDateStr+" "+x[:2]+":"+x[2:]+":00") if x else None)
        infoDF["dayOpenTime"] = infoDF["dayOpenTime"].apply(lambda x:pd.Timestamp(currentDateStr+" "+x[:2]+":"+x[2:]+":00") if x else None)
        infoDF["dayCloseTime"] = infoDF["dayCloseTime"].apply(lambda x:pd.Timestamp(currentDateStr+" "+x[:2]+":"+x[2:]+":00") if x else None)
    elif 231 <= currentMinute <= 1500:  # 今天日盘
        infoDF["nightOpenTime"] = infoDF["nightOpenTime"].apply(lambda x:pd.Timestamp(currentDateStr+" "+x[:2]+":"+x[2:]+":00") if x else None)
        infoDF["nightCloseTime"] = infoDF["nightCloseTime"].apply(lambda x:pd.Timestamp({"2300": currentDateStr}.get(x, nextDateStr)+" "+x[:2]+":"+x[2:]+":00") if x else None)
        infoDF["dayOpenTime"] = infoDF["dayOpenTime"].apply(lambda x:pd.Timestamp(currentDateStr+" "+x[:2]+":"+x[2:]+":00") if x else None)
        infoDF["dayCloseTime"] = infoDF["dayCloseTime"].apply(lambda x:pd.Timestamp(currentDateStr+" "+x[:2]+":"+x[2:]+":00") if x else None)
    else:   # 今天夜盘
        infoDF["nightOpenTime"] = infoDF["nightOpenTime"].apply(lambda x:pd.Timestamp(currentDateStr+" "+x[:2]+":"+x[2:]+":00") if x else None)
        infoDF["nightCloseTime"] = infoDF["nightCloseTime"].apply(lambda x:pd.Timestamp({"2300": currentDateStr}.get(x, nextDateStr)+" "+x[:2]+":"+x[2:]+":00") if x else None)
        infoDF["dayOpenTime"] = infoDF["dayOpenTime"].apply(lambda x:pd.Timestamp(nextDateStr+" "+x[:2]+":"+x[2:]+":00") if x else None)
        infoDF["dayCloseTime"] = infoDF["dayCloseTime"].apply(lambda x:pd.Timestamp(nextDateStr+" "+x[:2]+":"+x[2:]+":00") if x else None)
        infoDF["openTime"] = infoDF.apply(lambda row: row["nightOpenTime"] if pd.notnull(row["nightOpenTime"]) else row["dayOpenTime"], axis=1)
        infoDF["closeTime"] = infoDF["dayCloseTime"]    # 必定有日盘 -> 收盘即为日盘时间
        infoDF = infoDF[["product","exchange","contract","multi","longMarginRate","shortMarginRate",
                         "hasNightTrade","openTime","closeTime",
                         "nightOpenTime","nightCloseTime","dayOpenTime","dayCloseTime",
                         "isMainContract"]]   # 调整列顺序
    return infoDF
