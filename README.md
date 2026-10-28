# MaiBot Skills Support

以独立插件为 MaiBot 提供文档型 [Agent Skills](https://agentskills.io/specification) 支持。

采用 `SKILL.md`（YAML frontmatter + Markdown 正文），目录包含技能名称与适用说明，激活后才加入完整操作步骤。参考文档通过 `skill_read_reference` 按需加载。插件不修改 MaiBot 主程序。

## 能力

- WebUI：技能列表、正文查看、启停、移除、GitHub 安装/更新、管理员绑定和运行记录。
- 工具：`skill_control` 启动/查询/取消/结束任务，`skill_read_reference` 读取当前包参考资料，`skill_install_github` 安装技能。
- 聊天：`/install-skill <GitHub URL>`。只有后台指定的管理员可以安装；代码校验平台、机器人账号、用户身份和本条真实安装请求，模型或网页不能自行授予权限。
- 内置第一个技能 `deep-research`：用户明确要求查证时，在 Planner 请求前由代码创建任务、发送等待提示、加载技能。完成检查基于 Host Context 的真实搜索和正文工具结果，不能用模型自报代替。
- 同消息去重、话题更新、取消、有效期、任务额度、重载中断与工具执行日志。

## GitHub 安装

支持公开仓库地址（根目录为一个技能或仓库只含一个技能）、具体技能目录和 `SKILL.md` 链接，例如：

```text
/install-skill https://github.com/owner/repository/tree/main/skills/example
/install-skill https://github.com/owner/repository/blob/main/skills/example/SKILL.md
```

多技能仓库必须指定某个技能目录。分支名带 `/` 时使用仓库地址加 `?ref=feature%2Fbranch&path=skills%2Fexample`。安装先解析为固定 commit，记录来源、commit 与文档哈希；不会自动跟随上游更新，也不会静默覆盖同名技能。后台“更新”会重新读取原安装地址（保留原分支/路径；固定 SHA 的地址保持固定），校验通过后原子替换；保留原启停状态、旧版本和运行中任务的版本快照。网络/格式/名称校验失败时保留当前版本。旧版未记录原始地址的技能需在详情中补全更新地址，不能猜测分支。

最多40个技能、每包32个文档、单文件64KB、总量512KB。仅从固定 GitHub API/raw 主机读取，不跟随重定向、不克隆仓库、不解压第三方压缩包。保留包内 LICENSE/NOTICE 文档；安装者仍需遵守上游许可。

## 支持范围

这是通用格式的**文档型实现**，不是完整的代码执行环境。第一版只加载文本资料，跳过脚本与二进制。`scripts/`、终端、浏览器控制、文件写入等依赖不会因安装 Skill 而获得能力。`allowed-tools` 作为兼容信息展示，不授予权限或替换宿主权限控制。包内语义与来源可信度仍需管理员判断。

可选字符串 metadata 扩展：

```yaml
metadata:
  maibot-trigger-phrases: 深入调查|仔细查查
  maibot-required-tools: search_and_summarize|web_search;fetch_page|web_fetch
```

触发短语为普通字符串，非正则；引用/否定/取消消息不会自动启动。必要工具按分号分组，组内 `|` 为替代项。完成时验证当前任务开始后的真实成功调用记录。它证明步骤执行过，不证明资料质量、结论正确或最终回复已送达。Agent 仍负责选择工具、核对内容与组织回答。取消/额度不等于对宿主正在执行的请求做强制中断/限流。

内置深入调查只是首次安装的示例，可以关闭或移除；移除后不会因重载/升级重新出现。现有内置技能可用“更新”获取插件附带的新示例版本，保留启停状态。

引用要求由可选 `maibot-require-citations: "true"` 指定；插件会为回复补全本任务真实成功正文读取中的遗漏链接。该列表只是来源可见性保护，不保证链接支持回复中每一句话；Skill 仍需逐条核对。

第一版会话限私聊；管理员权限独立配置，默认未绑定时聊天安装被拒绝。WebUI 操作走宿主登录鉴权。普通聊天不写全局记忆，任务与技能记录仅在本插件本地数据目录。

## 开发与部署

源码独立 Git 仓库，运行目录仅接收构建输出。复制 `.env.example` 为 `.env.local` 并配置 `MAIBOT_PLUGINS_DIR`。

```shell
python -m unittest discover -s . -p "test_*.py"
python build.py --dry-run
python build.py --package-only
python build.py
```

构建使用显式文件白名单，保留实例 config.toml 和数据。MaiBot 会监听部署文件变化并自动重载，部署前须检查 Python 可以启动。升级前备份实例数据；不发布本机配置、聊天或凭据。

“深入调查”旧插件可以停用，保留旧任务记录作为历史；本插件的新运行记录使用独立数据库，不能将旧版“Agent自报完成”迁成新验证成功。
