# ADR-0006: 沙箱容器不做池化

- **状态**：已采纳（含事故记录）
- **日期**：2026-09-18
- **决策者**：@231dff

## 背景

早期实现 `SandboxPool` 缓存容器，`release` 时执行
`rm -rf /workspace/*` 清理后归还池子。

**2026-09-17 发生严重事故**：

Docker 容器的 volume 挂载在**容器启动时**就固定。运行期改
`sb.workspace` 只是改 Python 属性，容器内 `/workspace` 仍指向
首个任务的项目目录。

结果：
1. 第一个任务挂载 A 项目
2. 第二个任务请求 B 项目，复用了同一容器
3. release 时 `rm -rf` 删的其实是 **A 项目**的文件
4. **用户项目文件被删除**

## 决策

**完全废弃池化**。

- `SandboxPool` 保留类名和方法签名（兼容 import）
- `acquire(workspace)` 每次都新建容器
- `release(sb)` 只 `stop()` 容器，**绝不执行任何删除命令**
- 新增回归测试 `test_pool_module_has_no_rm_rf` 锁死行为

## 理由

### 为什么不做池化？

Docker volume 挂载不可热改，池化 + 多项目组合根本不成立。

正确的池化需要：
1. 每个项目一个 pool（进程级绑定项目）
2. 容器内区分 `/workspace`（只读挂载）和 `/sandbox`（可写临时区）
3. release 只清 `/sandbox`，绝不触碰 `/workspace`

这是**大改**，成本远超收益。现阶段每个任务 Docker 冷启动
2-5 秒可接受。

### 为什么保留 SandboxPool 类名？

`agent/core.py` 里已经 `from sandbox.pool import SandboxPool`。
改名要改调用方，风险大于收益。保留兼容层。

## 后果

### 正面
- **安全**：永远不会误删用户文件
- 简单：一容器一任务，无状态污染

### 负面
- 每个任务 Docker 冷启动 2-5 秒
- 无法复用已装依赖的环境

### 缓解
- 沙箱启动与代码库分析**并行**（`agent/core.py`）
- 如果未来确实需要池化，见上面"正确的池化"设计

## 回归保护

```python
# tests/test_sandbox_pool_safety.py
def test_pool_module_has_no_rm_rf():
    import sandbox.pool as pool_module
    src = inspect.getsource(pool_module)
    # 去掉注释和 docstring 后
    assert 'rm -rf' not in code