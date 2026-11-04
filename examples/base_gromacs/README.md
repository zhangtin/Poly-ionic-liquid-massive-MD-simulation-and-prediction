# base_gromacs — SPC/E 液态水基准工程

mdflow V0.1 的开发与测试基准工程：1728 个刚性 SPC/E 水分子（OPLS-AA 原子类型），立方周期盒 3.72412 nm，5184 个原子。

> 本工程是**测试体系**，用于验证 Script Builder，不是经过验证的科研体系。

## 文件来源一览

| 文件 | 来源 | 是否修改 |
|---|---|---|
| `oplsaa.ff/forcefield.itp` | GROMACS 2025.5 `share/top/oplsaa.ff/` | 未修改（逐字节复制） |
| `oplsaa.ff/ffnonbonded.itp` | 同上 | 未修改 |
| `oplsaa.ff/ffbonded.itp` | 同上 | 未修改 |
| `oplsaa.ff/spce.itp` | 同上 | 未修改 |
| `upstream/spc216.gro` | GROMACS 2025.5 `share/top/spc216.gro` | 未修改（仅作来源留存，不打包进任务） |
| `LICENSES/GROMACS-COPYING-LGPL-2.1.txt` | GROMACS 2025.5 `COPYING` | 未修改 |
| `conf.gro` | **项目生成**：`tools/make_conf.py` 将 `spc216.gro` 平移复制 2×2×2 | 派生文件 |
| `topol.top` | **项目创建** | — |
| `mdp/*.mdp.j2` | **项目创建**（参数依据 GROMACS 参考手册中的 mdp 选项说明自行编写） | — |
| `base_project.yaml` | **项目创建**（mdflow 基准工程描述文件） | — |
| `tools/make_conf.py`, `tools/fetch_upstream.sh` | **项目创建** | — |
| `SHA256SUMS` | **项目创建**（完整性参考，`mdflow validate` 会校验） | — |

详细的来源、许可证、校验和与修改记录见 [`docs/EXAMPLE_SOURCE.md`](../../docs/EXAMPLE_SOURCE.md)。

## 重新生成 / 校验

```bash
python3 tools/make_conf.py upstream/spc216.gro conf.gro --n 2   # 重新生成 conf.gro
bash tools/fetch_upstream.sh /tmp/upstream_check                # 从官方仓库重新获取并校验上游文件
sha256sum -c SHA256SUMS                                         # 检查本工程未被改动
```

修改本工程任何文件后，需要重新生成 `SHA256SUMS`，否则 mdflow 会报 `BASE_PROJECT_MODIFIED`；同时基准工程哈希改变，所有 Job ID 与随机种子也会随之改变（这是有意的设计）。
