# 拾账 / Shizhang

拾账是基于 **BeeCount Cloud 修改**的个人记账系统，以自己日常使用为主。通过 Web/PWA 查看和整理账目，兼容 BeeCount 手机 App 与 iPhone 快捷指令采集。

修改版源码地址：<https://github.com/Jaxson-zip/shizhang>。

## 构建与运行

从本仓库源码构建，请使用 [拾账构建说明](docs/SHIZHANG.md) 和 `docker-compose.source.yml`；它们构建本地 `shizhang-cloud` 镜像，不使用原作者发布的应用镜像。现有线上实例升级有单独的备份、回归、批准和回退流程。

本项目保留原生认证、交易、分类、数据库及同步契约。品牌更名不会更改 API、协议、数据库名或已签名快捷指令。OCR 明确的直接入账；视觉补读结果先保留为排除统计/预算的临时账目，核对后才计入。

## 来源与许可

- 原项目：[BeeCount Cloud](https://github.com/TNT-Likely/BeeCount-Cloud)
- 原作者：sunxiao（GitHub: TNT-Likely）
- 版权所有 (c) 2024-2026 sunxiao
- 完整原始许可：[LICENSE](LICENSE) / [LICENSE_EN](LICENSE_EN)
- 修改范围与上游基准：[NOTICE](NOTICE.md)

修改版必须公开源码并保留原作者版权、许可及作者信息。**商业使用前必须取得原作者书面商业授权。**

上游文档保留供参考：[English README](docs/UPSTREAM-README.en.md)、[中文 README](README.zh-CN.md)、[README.en.md](README.en.md)。其中上游产品和镜像信息不代表拾账自己的发布。

公开仓库只包含源码、合成测试与品牌资源，不包含个人配置、数据库、备份、截图或真实账单。
