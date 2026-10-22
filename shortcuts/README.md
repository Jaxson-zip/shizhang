# 拾账 OCR 通用快捷指令

`Shizhang-OCR-public.plist` 是可检查、可编辑的原生快捷指令源码；`Shizhang-OCR-public.shortcut` 是已签名的分发文件。Web 下载地址沿用 `/validation/BeeCount-OCR.shortcut`，该文件与这里的签名副本一致。

导入模板 `Shizhang OCR public v9` 时，依次填写：

1. 自己的拾账 HTTPS 地址（如 `https://ledger.example.com`，末尾无斜杠）。
2. 自己的登录邮箱。
3. 账本 ID：网页“账本”中编辑目标账本，可见其 ID；不要填写账本名称。
4. 拾账账号密码；不是服务器 root 密码。

四项默认均为空，缺项时在发送登录请求前停止。请勿分享配置后的快捷指令。
可以把导入后的名称改为“拾账 OCR 记账”，再绑定 iPhone 轻点背面。
旧实例中已经安装的快捷指令继续保留，不需要为公开源码重新安装。

截图 → Apple 端侧 OCR → 自己的服务器。只有规则不明确时，服务器才把截图交给配置的视觉服务商；视觉结果先作临时账目，核对后才计入统计。
原生登录、采集、注销 API，采集请求标识和时间字段沿用现有契约。

## 验证与重新签名

```sh
python -m pytest -q tests/test_public_shortcut.py
```

本次通用模板只将四个实例配置改为导入问题，并给新增必填字段加停止保护。
签名只提交空配置的公开 XML 给 RoutineHub HubSign，未提交用户凭据、账单、截图或私有模板。
签名证据及散列见 [public-proof.json](public-proof.json)。证书链校验通过；AEA 签名载荷尚未独立解包验证，实体 iPhone 导入与真实采集也尚未验收。

以后也可在自己的 Mac 上使用 Apple 的签名命令：

```sh
shortcuts sign --mode anyone --input shortcuts/Shizhang-OCR-public.plist --output shortcuts/Shizhang-OCR-public.shortcut
```

Apple 说明签名时会接收一份快捷指令进行验证，因此仍只能签署空配置模板。见 [Apple 命令行与签名说明](https://support.apple.com/en-nz/guide/shortcuts-mac/apd455c82f02/mac)。
重新签名后同步更新 Web 下载副本与散列记录，再在实体 iPhone 验收。
