# 拾账：源码构建与使用边界

拾账基于 BeeCount Cloud 修改。原作者版权与许可见 [NOTICE](../NOTICE.md)、[LICENSE](../LICENSE) 和 [LICENSE_EN](../LICENSE_EN)。

## 从自己的源码构建

要求：Git、Docker Engine 与 Compose；前端单独开发使用 Node 20 和项目声明的 pnpm 10.15.1。

仓库公开后可使用：

```sh
git clone https://github.com/Jaxson-zip/shizhang.git
cd shizhang
# 在本机创建私有 .env，写入 JWT_SECRET=<至少 32 字节的随机密钥>
docker compose -f docker-compose.source.yml build
docker compose -f docker-compose.source.yml up -d
```

访问 `http://localhost:8869`。该模板只绑定本机，适合新建独立测试实例；外网访问需要单独配置 HTTPS 反向代理。
空实例首次启动会沿原生逻辑创建管理员。建议在私有 `.env` 中预先设置自己的 `BOOTSTRAP_ADMIN_EMAIL` 与 `BOOTSTRAP_ADMIN_PASSWORD`；未设置时，原生逻辑使用 `owner@example.com` 并生成随机密码，保存在私有 `data/.initial_admin_password`。已有用户时跳过创建；这些变量不用于重置现有账号。默认关闭公开注册，不需要为本人首次登录开放注册。
版本可在 `.env` 中设置 `SHIZHANG_VERSION`；它同时用于本地镜像标签与前端显示。
默认 [docker-compose.yml](../docker-compose.yml) 是保留的上游镜像模板，拾账源码构建请显式使用 `docker-compose.source.yml`。

前端独立检查：

```sh
cd frontend
corepack enable
pnpm install --frozen-lockfile
pnpm --filter @beecount/web test
pnpm --filter @beecount/web build
```

Dockerfile 的可选文档问答索引仍来自上游 BeeCount Website；它不是本项目代码或用户账目。后端、前端和数据库迁移均从本次检出的源码构建。
后端依赖目前使用上游 `requirements.txt` 范围声明，基础镜像也未锁定摘要，因此此流程不声称能逐字节重现旧镜像。新镜像须单独回归后才能用于生产。

## 现有生产实例升级

以上 `up` 命令不用于直接替换已有生产部署。升级前须获实例所有者批准，并完成：

1. 只读确认当前镜像、覆盖挂载、数据卷、配置和运行版本。
2. 确认当天原生加密备份与本机副本可用，保留恢复密钥及原定时任务。
3. 为新源码构建唯一版本的镜像，隔离回归；核对原生手机 App 和快捷指令契约。
4. 保持原数据路径、JWT 密钥、数据库、附件、备份配置及调度，只替换明确的应用发布内容。
5. 记录回退镜像和配置；升级前后核对账目摘要与待核对状态，异常先核实实际结果。

未验收新镜像前，现有线上发布继续使用。不能以新建空实例成功代替生产升级验证。

## 品牌、兼容与使用

- 界面产品名为拾账，保留 BeeCount Cloud 的来源、版权和许可说明。
- API 前缀、认证、数据库名/结构、同步协议、存储键、`web+beecount` 协议和已签名快捷指令不因品牌更名而改动。
- 官方 BeeCount App 仍称 BeeCount，作为兼容客户端使用；它不是拾账自行开发的原生客户端。
- 付款截图经 Apple 端侧提取文字后发到自己的服务器；规则不明确时可能调用配置的视觉服务商。视觉结果必须核对。
- 当前以本人使用为目标；实体 iPhone、弱网和多人实际使用的结果须另行记录。
- 商业使用前必须取得原作者书面商业授权。公开源码不代表已获得商业授权。

## 公开源码检查

只公开源码、合成测试及品牌资源；不公开私有配置、数据库、备份、截图和真实账单。
提交前检查当前文件和可推送历史，运行 Gitleaks；扫描通过仍需人工检查文件清单及二进制来源。
不要直接推送个人工作目录的旧分支，旧提交可能仍含已从当前文件删除的私人内容。

原作者的发布工作流在本修改版中保留，其执行条件限制为原作者仓库。自己的构建先使用上述本地命令；镜像发布、GitHub 推送和生产部署分别确认后执行。

自己的仓库还提供手动运行的 `Shizhang source build` 工作流：校验通用快捷指令、运行前端测试并从本次源码构建完整镜像。它不推送镜像、不发布 Release、不连接生产服务器；首次运行结果须另行确认，不能把工作流文件存在当成已构建成功。
通用快捷指令的可编辑源码、签名副本和配置方法见 [shortcuts](../shortcuts/README.md)。
