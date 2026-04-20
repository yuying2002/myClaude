# agent_loop.py

## 简介

`learn-claude-code` 是一个专注于探索 **AI Agent (智能体)** 核心机制的学习项目。本项目受 Anthropic Claude Code 启发，旨在通过动手实现（Hands-on）的方式，深入理解从“被动对话”到“主动工程化 Agent”的演进过程。

## 🎯 项目目标

在深入研究 LLM 优化技术（如 SFT, LoRA）和 RAG 的基础上，本项目侧重于：
* **Agent 循环 (The Agent Loop)**：理解感知-推理-行动（Perception-Reasoning-Action）的闭环。
* **工具调用 (Tool Use)**：实现 Agent 对文件系统、Shell 环境及外部 API 的控制。
* **上下文管理 (Context Management)**：探索长对话下的上下文压缩与 RAG 集成。
* **子智能体 (Sub-agents)**：实验复杂任务的多智能体拆解与协作模式。

## 🛠️ 技术栈

* **核心框架:** Anthropic Claude API / LangChain
* **关键协议:** MCP (Model Context Protocol)
* **开发环境:** GitHub Codespaces, GitHub CLI
* **辅助技术:** Agentic-RAG, Python

## 依赖

- Python 3.10+
- openai
- python-dotenv
- pyyaml（可选，用于解析技能 frontmatter）

## 主要类与结构

- `SkillLoader`：加载和管理技能（skills）元数据与内容。
- `TodoManager`：管理 todo 列表，支持渲染和状态校验。
- `agent_loop`：主循环函数，驱动多轮对话和工具调用。
- `run_subagent`：生成子代理处理子任务。
- 各种 run_xxx 工具函数：如 `run_bash`, `run_read`, `run_write`, `run_edit`。

## 快速开始

1. 克隆仓库到本地或 Codespaces：
```bash
git clone [https://github.com/yuying2002/learn-claude-code.git](https://github.com/yuying2002/learn-claude-code.git)
cd learn-claude-code
```

2. 安装必要依赖
```bash
pip install -r requirements.txt
```

3. 配置 `.env` 文件，设置 `OPENAI_API_KEY`、`MODEL_ID`、`OPENAI_BASE_URL` 等参数。
4. 在命令行运行：

```bash
python agent_loop.py
```

5. 按提示输入自然语言指令，代理将自动规划并执行任务。

## 目录结构示例

```
E:\agent\myClaude\
├── agent_loop.py
├── skills\
│   └── ...
├── .env
└── ...
```

## 注意事项

- 目前支持 Windows cmd 语法，可以通过修改prompt内容来支持 Linux shell。
- 所有文件操作均限制在当前工作目录及其子目录内。
- 子代理上下文与主代理隔离，但共享文件系统。
- 任务完成前需有实际文件/代码产出，否则无法全部标记为完成。

## 核心理念
通过学习Claude Code的harness机制，实现让agent在特定领域高效工作的harness。

## 贡献
欢迎提交 Issue 或 Pull Request 来完善这个学习项目。

...
Author: yuying2002
Research Focus: SDN, P4 Programming, LLM Optimization (RAG/Agent), Software Engineering