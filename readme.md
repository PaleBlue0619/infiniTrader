# 预计实现功能
1. 根据开仓csv信号文件,实现下单(盘前启动则开盘下单, 盘中启动则盘中下单) <br>
2. 订单/仓位对象加载与保存, 自定义MyOrder与MyPosition类序列化为json5文件 <br>
3. 支持止盈止损+最短/最长持仓时间设置, 在开仓csv信号文件中设置即可(FIFO触发, 时间优先:最短持仓时间前禁止平仓) <br>
4. 实时订单/交易行为写入DolphinDB流表, 后续将设置为持久化, 便于事后交易分析 <br>

# 注: 
pythongo与self_strategy文件夹分别对应C:\Users\Admin\AppData\Roaming\InfiniTrader_WxyAllProgramX64\pyStrategy下的对应文件夹的新增/修改文件 -> 基于pythongo源码进行魔改