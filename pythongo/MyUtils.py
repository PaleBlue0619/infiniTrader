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
        idx = lower_product_list.index(formatted_product)
        resultList.append(format_product_list[idx])
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
        year = timeList[i] if integerList[i] == 4 else timeList[i][1:]
        resultList.append(str(product) + str(year))
    return resultList

def createInfoTable(session: ddb.session, tableName: str, dropTB: bool = False):
    """DolphinDB 合约信息流表"""
    colNames = ["product", "exchange", "contract", "multi", "longMarginRate", "shortMarginRate",
                "hasNightTrade", "openTime", "closeTime", "nightOpenTime", "nightCloseTime", "dayOpenTime", "dayCloseTime"]
    colTypes = ["SYMBOL", "SYMBOL", "SYMBOL", "INT", "DOUBLE", "DOUBLE", "INT", "INT", "INT", "INT", "INT", "INT", "INT"]
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
                "direction", "offset", "price", "volume", "currentTime"]
    colTypes = ["SYMBOL", "SYMBOL", "INT", "INT", "INT", "TIMESTAMP",
                "INT", "INT", "DOUBLE", "INT", "TIMESTAMP"]
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
    FROM九期量化: https://hq.9qihuo.com/shouxufei/heyue/all -> 规整的DataFrame格式
    product contract openMarginRate closeMarginRate margin
    savePath为None时不保存
    """
    # 尝试用 HTML 读取
    tables = pd.read_html(filePath,header=2,index_col=None,encoding="utf-8")
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
