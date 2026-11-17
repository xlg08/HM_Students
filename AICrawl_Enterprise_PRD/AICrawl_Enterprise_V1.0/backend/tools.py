"""Report capabilities truthfully; installed does not mean integrated."""
import importlib.metadata
import platform


def tool_catalog():
    items = [dict(name="HTTPS Single Page", status="READY", detail="URL 输入、robots、IP 固定与 HTML 解析；访问受限停止"),dict(name="PyPI JSON Connector", status="READY", detail="官方公开 API，限三个固定项目，手动执行时联网"),
             dict(name="JSON Schema Rules", status="READY", detail="内置确定性字段规则，非通用 JSON Schema 实现"),
             dict(name="CSV Export / SHA-256 / Audit", status="READY", detail="CSV 导出、校验和及内存审计"),
             dict(name="Python", status="READY", detail=platform.python_version())]
    for package in ("fastapi", "scrapy", "playwright", "celery", "redis"):
        try:
            version = importlib.metadata.version(package)
            detail = "已安装 " + version + "；未集成执行链路"
        except importlib.metadata.PackageNotFoundError:
            detail = "未安装；未集成执行链路"
        items.append(dict(name=package, status="NOT_INTEGRATED", detail=detail))
    items.extend([dict(name="企业 IdP / OIDC", status="NOT_CONFIGURED", detail="尚未配置，未连接企业服务"),
                  dict(name="LLM 模型网关", status="NOT_CONFIGURED", detail="尚未配置，未连接企业服务"),
                  dict(name="PostgreSQL / Redis 服务", status="NOT_CONFIGURED", detail="内存模式，未连接服务")])
    return items
