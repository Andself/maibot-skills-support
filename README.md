# MaiBot Skills Support

**让麦麦办事更靠谱！**

给麦麦一本能随用随学的「办事手册」：查资料、做任务，按步骤来。

为 MaiBot 提供文档型 [Agent Skills](https://agentskills.io/specification) 支持：从 GitHub 安装技能，在聊天中创建技能，用 WebUI 管理、更新和还原，并查看实际工具执行记录。

[![Version](https://img.shields.io/badge/version-0.4.3-blue)](_manifest.json)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![MaiBot](https://img.shields.io/badge/MaiBot-1.3.14–1.3.16-orange)](_manifest.json)

## 从一句需求，到一套可复用的方法

Skill 使用 `SKILL.md` 描述适用场景与操作步骤。平时只向 Agent 提供名称和简介；激活后才加载完整说明，参考文档按需读取。

```text
用户提出需求 → 选择并激活 Skill → 按步骤调用宿主工具 → 核验执行记录 → 组织回答
```

插件内置「深入调查」作为第一个示例：先发送等待提示，再搜索、阅读正文、核对信息并给出来源。示例可以关闭或删除；删除后不会因重载或升级重新出现。

## 功能一览

| 能力 | 使用方式 |
| --- | --- |
| 安装在线技能 | WebUI 或 `/install-skill <GitHub 地址>` |
| 创建本地技能 | 管理员通过 `/create-skill <需求描述>` 调用宿主模型生成 |
| 管理技能 | 查看正文、启用、停用、移除、修改更新地址 |
| 更新与还原 | 按原安装地址更新，保留最近 3 个旧版本，离线还原 |
| 按需读取 | 完整指引在激活后加载，参考资料通过工具读取 |
| 执行记录 | 查看任务状态、真实工具调用、未完成步骤和来源 |
| 权限控制 | 独立指定管理员，代码校验真实身份与明确管理意图 |

## 快速开始

### 1. 安装插件

当前兼容范围为 **MaiBot 1.3.14–1.3.16 / Plugin SDK 2.16.x**，依赖 `PyYAML >=6,<7`。

从源码构建发布包：

```shell
git clone https://github.com/Andself/maibot-skills-support.git
cd maibot-skills-support
python build.py --package-only
```

将 `dist/` 生成的 ZIP 解压到实例插件目录下的 `anse.skills-support/`，确保 `_manifest.json` 位于该目录第一层。按宿主方式安装依赖、加载插件，并授予清单中声明的能力。

在 WebUI 的插件扩展页面打开 **Skills 技能管理**，启用功能。深入调查需要宿主已有可用的搜索、网页读取工具；插件本身不附带搜索服务或 API Key。

### 2. 指定管理员

先通过任意已接入 MaiBot 的渠道建立私聊，再在管理页选择该私聊用户并保存。

**本插件不依赖 iLink。** 管理员身份独立保存，按「平台 + 机器人账号 + 用户 ID」校验。未绑定管理员时，后台仍可管理技能，普通用户仍可使用已启用技能；聊天安装与创建会被拒绝。WebUI 管理操作使用宿主登录鉴权。

### 3. 开始使用

私聊中可以先试试内置示例：

```text
帮我深入调查这个说法的出处，并核对原始资料。
```

安装一个在线技能：

```text
/install-skill https://github.com/owner/repository/tree/main/skills/example
```

创建一个本地技能：

```text
/create-skill 设计一个整理会议纪要的技能，输出决策、负责人和待办事项
```

也可让 Agent 通过 `skill_control` 激活已安装技能。安装技能并不保证自动触发；自定义触发短语见下文。

## 技能来源与生命周期

### GitHub 安装

支持公开仓库地址、具体技能目录和 `SKILL.md` 文件链接。多技能仓库需要指定目录；仓库根地址仅在能够唯一确定技能时使用。

```text
https://github.com/owner/repository/tree/main/skills/example
https://github.com/owner/repository/blob/main/skills/example/SKILL.md
```

分支名包含 `/` 时，使用显式参数：

```text
https://github.com/owner/repository?ref=feature%2Fbranch&path=skills%2Fexample
```

下载先固定仓库 commit，再读取同一快照中的文件；记录原安装地址、版本和内容哈希。同名技能不会被静默覆盖。每包最多 32 个文档、单文件 64 KB、总计 512 KB，最多安装 40 个技能。

### 本地创建

`/create-skill` 使用宿主已配置的模型生成标准 `SKILL.md`，校验后保存到插件数据目录 `local-skills/<name>/SKILL.md` 并登记到列表。仅发送需求描述，不附带整段聊天，费用遵循宿主模型计费。

超时、格式无效或同名冲突不会覆盖现有技能。生成结果不会上传 GitHub，也不会自动获得触发、脚本或工具执行权限。本地技能可以关闭、移除；移除会删除本地文件，历史任务仍保留执行快照。

### 更新与版本还原

仅在线安装的技能显示「更新」和「版本管理」。内置与本地生成技能没有在线更新入口。

- **更新来源**：重新读取记录的原分支和路径；固定 SHA 地址仍保持固定。旧记录缺少安装地址时，需要在详情中手动补全。
- **版本号**：技能目录最后一次变更的 GitHub commit hash；另外记录下载时的仓库快照 SHA。
- **时间**：本地安装或应用该版本的日期。内容未变的检查不占历史名额，也不刷新应用日期。
- **保留范围**：当前版本，加最近 3 个不同内容的完整旧快照，包含参考文档。
- **离线还原**：选择历史版本并确认即可。还原前保存当前版本，可以再次切回；超出上限则淘汰最早归档项。

更新和还原保留启停状态，运行中任务继续使用启动时的版本。还原还会保留配置的更新地址。网络、格式或名称校验失败时保留当前版本；移除技能会清除其版本历史。

## 编写 Skill

最小示例：

```markdown
---
name: meeting-notes
description: 将会议内容整理为决策、负责人、待办和待确认问题。
---

先确认记录范围；区分已达成的决策和讨论建议。
按事项列出负责人、截止时间与依据；没有明确的信息标记为待确认。
```

可选的 MaiBot 扩展字段：

```yaml
metadata:
  maibot-trigger-phrases: 深入调查|仔细查查
  maibot-required-tools: search_and_summarize|web_search;fetch_page|web_fetch
  maibot-require-citations: "true"
```

| 字段 | 含义 |
| --- | --- |
| `maibot-trigger-phrases` | 使用 `\|` 分隔普通触发短语，非正则；明确否定、引用和取消场景不会自动启动 |
| `maibot-required-tools` | 用 `;` 分组，每组至少有一个真实成功调用；组内 `\|` 表示可替代工具 |
| `maibot-require-citations` | 为回复补充当前任务中真实读取、但回复遗漏的正文来源链接 |

工具名称需要匹配宿主实际提供的工具。生成的本地技能不会由模型自行添加上述行为扩展。

## 支持范围与执行边界

本插件实现文档加载、参考资料读取与任务记录，**目前仅支持私聊**。

- 不修改 MaiBot 主程序，不执行 Skill 内的脚本或二进制。`allowed-tools` 仅作为兼容信息，不授予新权限；实际工具由宿主发现与执行。
- 只从固定 GitHub API/raw 主机下载，不跟随重定向、不克隆第三方仓库、不解压第三方压缩包。包内 LICENSE/NOTICE 会保留，使用者需遵守上游许可。
- 步骤核验依据 Host Context 中的真实工具调用结果。它证明工具执行过，不证明资料可靠、答案正确或回复送达；来源链接也不等于每项结论都有支持。
- 取消、有效期和任务额度管理插件任务状态，不会强制中断宿主正在执行的外部请求。重载时未完成任务会标记为中断。
- 插件不将普通聊天写入全局记忆。技能、管理员设置与任务记录保存在实例的插件数据目录；卸载、分享或备份前应自行处理这些数据。

## 开发与部署

源码仓库与运行目录分离。复制 `.env.example` 为被 Git 忽略的 `.env.local`，配置 `MAIBOT_PLUGINS_DIR` 指向实例插件父目录。

```shell
python -m unittest discover -s . -p "test_*.py"
python build.py --dry-run
python build.py --package-only
python build.py
```

构建使用显式文件白名单，排除测试、构建工具、环境文件、缓存和运行数据。部署保留实例 `config.toml`；旧文件只按构建登记清单清理。部署后按宿主方式重载插件，升级前备份实例数据。

## 反馈与贡献

欢迎通过 [Issues](https://github.com/Andself/maibot-skills-support/issues) 提交问题或建议。反馈时请提供插件与宿主版本、复现步骤，以及脱敏后的错误信息；不要上传 API Key、账号标识或聊天记录。

[MIT License](LICENSE)

工具调用需携带当前请求的短期凭证，插件复核其会话与最新消息；凭证不持久化，重载或15分钟后失效。它用于阻止仅伪造会话 ID 的跨会话调用，不能替代宿主权限控制，也不保证模型不会泄露上下文。安装 ZIP 仅含运行文件、README 和 LICENSE；构建工具仍在源码仓库中。
