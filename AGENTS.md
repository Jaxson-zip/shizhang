# 拾账开发约定

先读 README.md、NOTICE.md 与 docs/SHIZHANG.md。拾账基于 BeeCount Cloud 修改，保留原作者版权、作者及许可。

保留原生认证、交易、分类、同步和备份设施。品牌修改不能改变 API、数据库结构、同步协议、存储键或客户端兼容性。

Claude Code 负责算法，Codex 负责验收、前端和运维。算法边界包括 src/services/payment_rules.py、src/services/alipay_rules.py、src/services/ai/payment_vision.py 和 src/routers/ai/parse_tx_text.py；跨边界修改先协调。

不 reset/clean/覆盖其他工作，不自动全部暂存。私有配置、凭据、数据库、备份、截图和真实账单不进仓库。只分发 shortcuts/ 中四项配置为空的通用模板。

OCR 明确的沿原生路径入账；视觉结果须核对，先写排除统计/预算的临时账目。不要擅自确认旧采集或改历史账目。

生产读取、推送、部署、隐藏或删除功能须先说明具体计划并取得当次批准。写入结果未知先核实，沿原生 CAS 和幂等路径处理。
