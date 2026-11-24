"""业务路由汇总：专用定制路由优先注册，通用资源路由兜底动态模块路径。"""
from __future__ import annotations

from app.routers import remap, resource

# remap 含 /api/remap_worklist 等静态路径，必须排在通配 /api/{module} 之前，
# 否则定制入口会被资源路由抢先匹配。
ROUTERS = [remap, resource]
